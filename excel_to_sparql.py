"""
excel_to_sparql.py
==================
Converte regras de inferência de CID-10 definidas em planilha Excel para
queries SPARQL CONSTRUCT, usando a ontologia OWL como referência de URIs.

Uso:
    python excel_to_sparql.py

Saída:
    sparql_rules.json  – regras SPARQL indexadas por aba
    rules_uri.json     – regras com URIs resolvidas
    listas_de_termos.json – listas de termos extraídas da aba LISTAS

Estrutura do módulo
-------------------
  config.py              → caminhos e constantes
  ontology_loader.py     → carrega a OWL e expõe helpers de URI
  excel_reader.py        → lê a planilha (listas + abas de regras)
  sparql_builders.py     → funções puras de geração de cláusulas SPARQL
  rule_processor.py      → orquestra a conversão de uma linha → SPARQL
  json_exporters.py      → serializa as saídas JSON
  main.py / este módulo  → ponto de entrada
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import owlready2
import pandas as pd
import regex as re
from openpyxl import load_workbook


# ===========================================================================
# CONFIGURAÇÃO
# ===========================================================================

@dataclass
class Config:
    """Centraliza todos os caminhos e constantes do pipeline."""

    # Entradas
    excel_path: str = "regras_ontologias_IEXOGENA_valida_MS.xlsx"
    ontology_path: str = "ontologia_intox.owl"
    substances_parquet: str = "substancias_cid.parquet"

    # Saídas
    output_sparql_json: str = "sparql_rules.json"
    output_uri_json: str = "rules_uri.json"
    output_listas_json: str = "listas_de_termos.json"

    # Namespace da ontologia
    ontology_namespace: str = "https://ontologia.trauma.einstein.br/intox#"

    # Propriedade que será inferida (CID-10)
    inferred_cid_prop: str = "INFERRED_DIAG_CONF"

    # Prefixo SPARQL adicionado a cada query
    sparql_prefix: str = (
        "PREFIX intox: <https://ontologia.trauma.einstein.br/intox#>"
    )

    # Abas com regras de inferência e seus intervalos de linhas
    rule_sheets: list[dict] = field(default_factory=lambda: [
        {"nome": "X40-X49", "linha_inicial": 18, "linha_final": 117},
        {"nome": "X60-X69", "linha_inicial": 18, "linha_final": 117},
        {"nome": "X85-X90", "linha_inicial": 17, "linha_final":  76},
        {"nome": "Y10-Y19", "linha_inicial": 18, "linha_final": 117},
        {"nome": "Y40-Y59", "linha_inicial": 17, "linha_final": 188},
    ])

    # Aba que contém as listas de termos
    lists_sheet: str = "LISTAS"

    # Limites da seção de metadados das listas (linhas com "LISTA N: …")
    lists_meta_first_row: int = 4
    lists_meta_last_row: int = 43

    # Linha onde os nomes das listas aparecem como cabeçalho
    lists_header_row: int = 45

    # Primeira linha de termos das listas
    lists_terms_first_row: int = 46


# ===========================================================================
# CARREGAMENTO DA ONTOLOGIA
# ===========================================================================

class OntologyLoader:
    """
    Carrega a ontologia OWL e expõe helpers para busca de URIs de instâncias.
    """

    def __init__(self, config: Config):
        self._config = config
        self._ontology = owlready2.get_ontology(config.ontology_path).load()
        self.namespace = self._ontology.get_namespace(config.ontology_namespace)

    def get_uri_for_option(self, var_name: str, option_description: str):
        """
        Retorna a instância cujo label começa com o primeiro número encontrado
        em *option_description*, dentro da classe de range de *var_name*.

        Retorna None se não encontrar correspondência.
        """
        option_index = self._get_first_number(option_description)
        if option_index is None:
            return None

        for opt in self.namespace[var_name].range[0].instances():
            # D6: aceita código sem zero à esquerda ("2" ≡ "02"), mantendo o match antigo
            if opt.label[0].startswith(option_index) or opt.label[0].startswith(option_index.zfill(2)):
                return opt

        available = [i.label[0] for i in self.namespace[var_name].range[0].instances()]
        print(
            f"get_uri_for_option: instância não encontrada para "
            f"'{option_description}'. Opções: {available}"
        )
        return None

    @staticmethod
    def _get_first_number(description: str) -> str | None:
        """Extrai o número inteiro que inicia *description*, ou None."""
        m = re.match(r"^([0-9]+)", description)
        return m[1] if m else None


# ===========================================================================
# LEITURA DA PLANILHA
# ===========================================================================

class ExcelReader:
    """
    Lê a planilha Excel e extrai listas de termos e regras de inferência.
    """

    def __init__(self, config: Config):
        self._config = config
        self._wb = load_workbook(filename=config.excel_path)

    # ------------------------------------------------------------------
    # Listas de termos (aba LISTAS)
    # ------------------------------------------------------------------

    def read_term_lists(self) -> dict[str, dict]:
        """
        Retorna um dicionário indexado pela URI da lista, contendo
        label, descrição, CIDs e termos de cada lista.
        """
        cfg = self._config
        aba = self._wb[cfg.lists_sheet]

        metadata = self._read_list_metadata(aba, cfg.lists_meta_first_row, cfg.lists_meta_last_row)
        terms = self._read_list_terms(aba, metadata, cfg.lists_header_row, cfg.lists_terms_first_row)

        for uri, list_data in metadata.items():
            list_data["termos"] = terms[uri]

        if not metadata:
            raise RuntimeError("Lista de termos vazia — verifique a aba LISTAS.")

        return metadata

    def _read_list_metadata(
        self,
        aba,
        first_row: int,
        last_row: int,
    ) -> dict[str, dict]:
        """Lê as linhas de metadados das listas (tipo 'LISTA N: descrição')."""
        cid_pattern = re.compile(r"[A-Z][0-9]{2}")
        result: dict[str, dict] = {}

        for i in range(first_row, last_row + 1):
            cell_value = aba[f"A{i}"].value
            if not cell_value:
                continue
            if not cell_value.startswith("LISTA"):
                raise ValueError(f"Linha inesperada na aba LISTAS (linha {i}): {cell_value!r}")

            nome_lista, descricao_lista = cell_value.split(": ", 1)
            cids = cid_pattern.findall(descricao_lista)
            uri = self._list_uri(nome_lista)
            result[uri] = {
                "rdf:label": nome_lista,
                "rdf:description": descricao_lista,
                "intox:codigo_cid10": cids,
            }

        return result

    def _read_list_terms(
        self,
        aba,
        metadata: dict[str, dict],
        header_row: int,
        first_terms_row: int,
    ) -> dict[str, list[str]]:
        """
        Lê os termos de cada lista, coluna a coluna, a partir de *first_terms_row*.
        """
        result: dict[str, list[str]] = {}

        for col_index, (uri, list_data) in enumerate(metadata.items()):
            col = _index_to_excel_column(col_index)
            lista_nome = list_data["rdf:label"]

            header_value = aba[f"{col}{header_row}"].value
            if lista_nome != header_value:
                raise ValueError(
                    f"Coluna {col} contém '{header_value}', esperado '{lista_nome}'."
                )

            terms: list[str] = []
            row = first_terms_row
            while True:
                value = aba[f"{col}{row}"].value
                if value is None or (isinstance(value, str) and value.strip() == ""):
                    # Verifica se há mais termos abaixo (célula vazia interna)
                    next_value = aba[f"{col}{row + 1}"].value
                    if next_value is not None and (
                        not isinstance(next_value, str) or next_value.strip() != ""
                    ):
                        print(
                            f"Warning: célula vazia em {col}{row} da lista '{lista_nome}' "
                            f"(próxima célula={next_value!r}). Termos abaixo serão ignorados."
                        )
                    break
                terms.append(_remove_source_tag(str(value)))
                row += 1

            result[uri] = terms

        return result

    # ------------------------------------------------------------------
    # Regras de inferência (demais abas)
    # ------------------------------------------------------------------

    def read_rules(
        self,
        sheet_name: str,
        first_row: int,
        last_row: int,
        inferred_prop: str,
    ) -> list[dict[str, list[str]]]:
        """
        Lê as linhas de regras de uma aba e retorna uma lista de dicts,
        onde cada chave é um campo e o valor é a lista de condições da célula.

        A aba Y40-Y59 tem uma coluna a menos (sem LOC_EXPO;LOC_EXP_DE).
        """
        aba = self._wb[sheet_name]
        campos_agente = ";".join(["AGENTE_1", "AGENTE_2", "AGENTE_3",
                                  "P_ATIVO_1", "P_ATIVO_2", "P_ATIVO_3"])
        regras = []

        for i in range(first_row, last_row + 1):
            regra: dict[str, list[str]] = {}

            if sheet_name == "Y40-Y59":
                regra["CIRCUNSTAN"]      = _split_nvl(aba[f"A{i}"].value)
                regra["AGENTE_TOX"]      = _split_nvl(aba[f"B{i}"].value)
                regra[campos_agente]     = _split_nvl(aba[f"C{i}"].value)
                regra[inferred_prop]     = _split_nvl(aba[f"D{i}"].value)
            else:
                regra["CIRCUNSTAN"]          = _split_nvl(aba[f"A{i}"].value)
                regra["AGENTE_TOX"]          = _split_nvl(aba[f"B{i}"].value)
                regra[campos_agente]         = _split_nvl(aba[f"C{i}"].value)
                regra["LOC_EXPO;LOC_EXP_DE"] = _split_nvl(aba[f"D{i}"].value)
                regra[inferred_prop]         = _split_nvl(aba[f"E{i}"].value)

            # D2/D4: faixa de CID de exclusão (coluna G); vazia nas planilhas antigas
            regra["CID_EXCLUSAO"] = _split_nvl(aba[f"G{i}"].value)
            regras.append(regra)

        return regras

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_uri(nome_lista: str) -> str:
        return f"intox:lista_{_extract_list_index(nome_lista)}"


# ===========================================================================
# CARREGAMENTO DE SUBSTÂNCIAS (CID → lista de substâncias)
# ===========================================================================

def load_icd_to_substances(parquet_path: str) -> dict[str, list[str]]:
    """
    Lê o parquet de substâncias e retorna um dicionário CID → [substâncias].
    Filtra apenas CIDs que começam com 'Y' e exclui linhas de subtítulo (–).
    Retorna dict vazio se o arquivo não existir (regras Y40-Y59 serão puladas).
    """
    if not Path(parquet_path).exists():
        print(f"Warning: {parquet_path!r} não encontrado. Regras Y40-Y59 serão ignoradas.")
        return {}
    df = pd.read_parquet(parquet_path, columns=["Substância", "Efeito adverso em uso terapêutico"])
    df.columns = ["substancia", "icd_10"]
    df.dropna(inplace=True)
    df = df[df.icd_10.str.startswith("Y")]
    df = df[~df.substancia.str.startswith("–")]
    return df.groupby("icd_10")["substancia"].apply(list).to_dict()


# ===========================================================================
# HELPERS GENÉRICOS (funções puras, sem estado)
# ===========================================================================

def _split_nvl(value: Any, sep: str = "\n") -> list[str]:
    """Divide uma string pelo separador; retorna [] se *value* for None.

    Remove elementos vazios no FINAL da lista (trailing), que surgem quando a
    célula do Excel termina com uma quebra de linha extra (ex.: '02 X\\n03 Y\\n').
    Esses '' finais quebravam o processamento de campos categóricos
    (CIRCUNSTAN/AGENTE_TOX). Vazios INTERNOS são preservados, pois os padrões
    especiais (X70, X89, AGENTE_TOX=99) dependem deles.
    """
    if value is None:
        return []
    parts = value.split(sep)
    while parts and parts[-1].strip() == "":
        parts.pop()
    return parts


def _index_to_excel_column(index: int) -> str:
    """
    Converte índice numérico (base-0) para nome de coluna do Excel.
      0 → 'A', 25 → 'Z', 26 → 'AA', 27 → 'AB', 51 → 'AZ', 52 → 'BA', …

    O Excel usa numeração bijetiva (sem zero), portanto cada "dígito"
    precisa de um ajuste de -1 antes de calcular o resto.
    """
    result = ""
    n = index + 1  # converte base-0 para base-1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _remove_source_tag(term: str) -> str:
    """Remove sufixos de origem adicionados ao final de cada termo (e.g. '#fonte')."""
    return re.sub(r"#.*", "", term)


def _extract_list_index(list_name: str) -> str:
    """Extrai o número de um nome de lista (ex. 'LISTA 3' → '3')."""
    return re.compile(r"[0-9]+").findall(list_name)[0]


def _list_uri_from_name(list_name: str) -> str:
    """Cria a URI de uma lista a partir do seu nome textual."""
    return f"intox:lista_{_extract_list_index(list_name)}"


def _parse_cid_token(cid: str) -> tuple[str, int]:
    """Converte 'X43' em ('X', 43). Ignora a parte decimal/subcategoria."""
    cid = cid.strip()
    m = re.match(r"([A-Za-z])([0-9]{2})", cid)
    if not m:
        raise ValueError(f"CID inválido: {cid!r}")
    return m.group(1).upper(), int(m.group(2))


def _parse_cid_faixas(cid_ranges: list[str]) -> list[tuple[tuple[str, int], tuple[str, int]]]:
    """
    Lê os valores da coluna G (ex.: ['X40–X43']) e devolve as faixas de CID
    normalizadas [(('X',40),('X',43))]. Aceita hífen, en-dash e em-dash.
    """
    faixas: list[tuple[tuple[str, int], tuple[str, int]]] = []
    for token in cid_ranges:
        if not token:
            continue
        for a, b in re.findall(
            r"([A-Za-z][0-9]{2})\s*[-\u2010\u2011\u2012\u2013\u2014]\s*([A-Za-z][0-9]{2})",
            str(token),
        ):
            faixas.append((_parse_cid_token(a), _parse_cid_token(b)))
    return faixas


def _cid_dentro_faixa(cid: str, faixas: list) -> bool:
    """Verdadeiro se o CID (categoria de 3 caracteres) cai em alguma faixa."""
    try:
        p = _parse_cid_token(cid)
    except (ValueError, IndexError):
        return False
    return any(ini <= p <= fim for ini, fim in faixas)


def _listas_exclusao_das_regras_irmas(
    sheet_rules: list[dict],
    cid_faixas: list,
    inferred_prop: str,
) -> list[str]:
    """
    Deriva as URIs das listas de exclusão a partir das *regras irmãs* da mesma
    aba cujo CID inferido cai na(s) faixa(s) da coluna G (CID_EXCLUSAO).

    Para cada regra irmã dentro da faixa, coleta as LISTAS citadas em sua
    coluna de agentes (AGENTE_*/P_ATIVO_*). Retorna a união (ordenada e
    deduplicada) das URIs dessas listas.

    Exemplo: regra X440 (coluna G = 'X40-X43') → varre X400..X439 → une as
    LISTAS 9-16, 25-27 usadas por elas.
    """
    numeros_listas: set[int] = set()
    for irma in sheet_rules:
        cids_inferidos = irma.get(inferred_prop) or []
        if not cids_inferidos:
            continue
        cid = cids_inferidos[0]
        if not _cid_dentro_faixa(cid, cid_faixas):
            continue
        for campo, valores in irma.items():
            if not campo.startswith(("AGENTE_", "P_ATIVO_")) and "AGENTE_1" not in campo:
                continue
            for v in valores or []:
                for m in re.findall(r"LISTA\s+([0-9]{1,2})", str(v)):
                    numeros_listas.add(int(m))
    return [f"intox:lista_{n}" for n in sorted(numeros_listas)]


def _parse_agente_tox_categorias(texto: str) -> list[str]:
    """
    Extrai os códigos de categoria AGENTE_TOX citados em um texto de regra,
    ex.: 'quando AGENTE_TOX = 02, 03, 04 ou 05' -> ['02','03','04','05'].
    """
    categorias: list[str] = []
    for bloco in re.findall(r"AGENTE_TOX\s*=\s*([0-9,\s eou]+)", texto):
        for cod in re.findall(r"[0-9]{2}", bloco):
            if cod not in categorias:
                categorias.append(cod)
    return categorias


def _padroes_agente_das_regras_irmas(
    sheet_rules: list[dict],
    faixa_prefixos: tuple[str, ...],
    inferred_prop: str,
) -> list[dict]:
    """
    Deriva DINAMICAMENTE os padrões de agente das regras IRMÃS cujo CID inferido
    começa por um dos prefixos informados (ex.: ('X86','X87','X88')). Substitui
    as listas hard-coded do filtro X89 (`filtro_not_exists_agente`) pela leitura
    real das regras X86-X88 na planilha, análogo à correção da coluna G.

    Cada padrão devolvido é um dict com uma destas formas:
      • {'tipo': 'lista', 'listas': [21, 22]}
          → agente pertence à união dos termos dessas LISTAS.
      • {'tipo': 'agente_tox', 'categorias': ['02','03','04','05'], 'listas': []}
          → basta AGENTE_TOX ∈ categorias (qualquer conteúdo de agente).
      • {'tipo': 'agente_tox', 'categorias': ['07','09','14'], 'listas': [23,24]}
          → AGENTE_TOX ∈ categorias E agente ∈ termos dessas LISTAS.

    A união (deduplicada) desses padrões é exatamente o conjunto de registros
    que as regras X86-X88 já inferem; o filtro X89 usa NOT EXISTS sobre ele.
    """
    padroes: list[dict] = []
    vistos: set = set()

    for irma in sheet_rules:
        cids_inferidos = irma.get(inferred_prop) or []
        if not cids_inferidos:
            continue
        cid = str(cids_inferidos[0])
        if not cid.startswith(faixa_prefixos):
            continue

        # Coleta os valores das colunas de agente desta irmã, PRESERVANDO a ordem
        # das células (cada item da lista é uma célula da planilha). A ordem é
        # semântica: os qualificadores (LISTA / '(qualquer conteúdo)') aparecem
        # imediatamente ANTES da cláusula 'quando AGENTE_TOX = ...' que governam.
        tokens: list[str] = []
        for campo, valores in irma.items():
            if not campo.startswith(("AGENTE_", "P_ATIVO_")) and "AGENTE_1" not in campo:
                continue
            tokens += [str(v).strip() for v in (valores or []) if str(v).strip()]
        if not tokens:
            continue

        # Padrão estilo X70: cláusulas condicionadas por AGENTE_TOX. Percorre os
        # tokens acumulando qualificadores até encontrar um 'quando AGENTE_TOX',
        # e então vincula os qualificadores acumulados àquelas categorias.
        if any("AGENTE_TOX" in t for t in tokens):
            pend_listas: list[int] = []
            pend_qualquer = False
            houve_agente_tox = False
            for tok in tokens:
                if "AGENTE_TOX" in tok:
                    categorias = _parse_agente_tox_categorias(tok)
                    if not categorias:
                        continue
                    houve_agente_tox = True
                    listas_bloco = [] if pend_qualquer else sorted(set(pend_listas))
                    pad = {
                        "tipo": "agente_tox",
                        "categorias": categorias,
                        "listas": listas_bloco,
                    }
                    chave = ("agente_tox", tuple(sorted(categorias)), tuple(listas_bloco))
                    if chave not in vistos:
                        vistos.add(chave)
                        padroes.append(pad)
                    pend_listas, pend_qualquer = [], False
                else:
                    if "(qualquer conteúdo)" in tok:
                        pend_qualquer = True
                    pend_listas += [int(m) for m in re.findall(r"LISTA\s+([0-9]{1,2})", tok)]
            if houve_agente_tox:
                continue

        # Padrão simples: apenas LISTAs (ex.: X86x=28,29 / X88x=21,22).
        listas = sorted({int(m) for t in tokens for m in re.findall(r"LISTA\s+([0-9]{1,2})", t)})
        if listas:
            chave = ("lista", tuple(listas))
            if chave not in vistos:
                vistos.add(chave)
                padroes.append({"tipo": "lista", "listas": listas})

    return padroes


def _get_list_range(text: str) -> range:
    """
    Extrai faixa de listas de textos como 'listas 1 a 8'.
    Retorna range vazio se não encontrar.
    """
    m = re.findall(r"listas ([0-9]{1,2}) a ([0-9]{1,2})", text)
    return range(int(m[0][0]), int(m[0][1]) + 1) if m else range(0)


def _consolidate_lists(
    list_uris: list[str],
    term_lists: dict[str, dict],
) -> tuple[str, list[str]]:
    """
    Consolida os termos de múltiplas listas em uma única lista deduplicada e
    ordenada. Retorna (nome_variavel, termos).
    """
    var_name = "lista_termos_consolidados_" + "_".join(u.split("_")[1] for u in list_uris)
    terms: list[str] = []
    for uri in list_uris:
        terms += [t.lower() for t in term_lists[uri]["termos"]]
    return var_name, sorted(set(terms))


def _list_var_name(list_index: str) -> str:
    return f"lista_termos_{list_index}"


# ===========================================================================
# CONSTRUTORES DE CLÁUSULAS SPARQL (funções puras + contador via objeto)
# ===========================================================================

class SparqlVarCounter:
    """
    Mantém um contador de variáveis SPARQL para evitar colisões dentro de
    uma única query. Substitui o uso de `global query_variable_index`.
    """
    def __init__(self):
        self._index = 0

    def next(self) -> int:
        val = self._index
        self._index += 1
        return val

    def reset(self):
        self._index = 0


class SparqlClauseBuilder:
    """
    Constrói cláusulas SPARQL como listas de strings.

    Recebe um SparqlVarCounter para manter unicidade de variáveis dentro
    de uma query, e o dicionário de listas de termos.
    """

    def __init__(
        self,
        counter: SparqlVarCounter,
        term_lists: dict[str, dict],
        icd_to_substances: dict[str, list[str]] | None = None,
    ):
        self._c = counter
        self._term_lists = term_lists
        self._icd_to_substances = icd_to_substances or {}
        # cache de listas já declaradas com VALUES (reutilização dentro da query)
        self._declared_values: dict[str, str] = {}
        # Bindings de ORIGEM do agente expostos no corpo do WHERE (fora de
        # FILTER EXISTS), para o CONSTRUCT emitir o nó intox:temInferencia.
        # Cada item: (var_prop, var_val) = (variável do campo, variável do valor).
        self.origem_bindings: list[tuple[str, str]] = []
        # Sinaliza que a regra usa a rota X70 (UNION auto-contida): os ramos do
        # WHERE já vinculam ?_campo_x70/?_valor_x70/?_inf_x70 internamente, então
        # o CONSTRUCT deve emitir o nó temInferencia referenciando essas variáveis
        # SEM adicionar um BIND externo (que quebraria o escopo do UNION).
        # None = rota não usada; caso contrário guarda as vars fixas usadas.
        self.origem_x70: dict | None = None
        # Análogo ao origem_x70, porém para a rota X89 (X891-X897): a origem é o
        # PRIMEIRO campo de agente preenchido (a mesma semântica do Ramo A do X70).
        # Sem UNION — o binding fica direto no corpo do WHERE.
        self.origem_x89: dict | None = None
        # Caminho UNIVERSAL: rotas que não têm campo de agente casado (puramente
        # categóricas, agente-exclusão, Volume III, local de exposição) também
        # passam a emitir o nó intox:temInferencia. A origem, quando existir, é o
        # PRIMEIRO campo de agente preenchido do registro (mesma semântica das
        # demais rotas); se não houver, emite-se apenas o nó + CID. Preenchido
        # em rule_to_sparql quando nenhuma outra rota de origem foi acionada.
        self.origem_universal: dict | None = None

    # ------------------------------------------------------------------
    # Origem da inferência (helper universal)
    # ------------------------------------------------------------------

    # Ordem canônica dos campos de agente para resolução do PRIMEIRO preenchido.
    _CAMPOS_AGENTE_PADRAO = [
        "AGENTE_1", "AGENTE_2", "AGENTE_3",
        "P_ATIVO_1", "P_ATIVO_2", "P_ATIVO_3",
    ]

    @staticmethod
    def _origem_agente_lines(
        inferred_value: str,
        sufixo: str,
        campos: list[str] | None = None,
    ) -> tuple[list[str], dict]:
        """
        Gera as linhas SPARQL que expõem a ORIGEM da inferência a partir do
        PRIMEIRO campo de agente preenchido (ordem AGENTE_1 → … → P_ATIVO_3),
        via OPTIONAL + COALESCE, e vinculam o nó ?_inf_<sufixo> com IRI
        determinístico (registro + CID). Reutilizável por qualquer rota.

        Retorna (linhas, meta) onde meta = {campo, valor, inf, cid} com os
        NOMES das variáveis (sem '?') para o CONSTRUCT referenciar.

        Semântica: se NENHUM campo de agente estiver preenchido, ?_valor/?_campo
        ficam unbound e os triplos CAMPO_ORIGEM/VALOR_ORIGEM não materializam —
        porém o nó (?_inf) e o CID SEMPRE são emitidos (IRI só depende de
        ?registro, sempre vinculado no escopo externo, inclusive após UNION).
        """
        campos = campos or SparqlClauseBuilder._CAMPOS_AGENTE_PADRAO
        v_campo = f"_campo_{sufixo}"
        v_val = f"_valor_{sufixo}"
        v_inf = f"_inf_{sufixo}"
        meta = {"campo": v_campo, "valor": v_val, "inf": v_inf, "cid": inferred_value}

        lines: list[str] = []
        coalesce_val_args: list[str] = []
        coalesce_campo_args: list[str] = []
        for i, c in enumerate(campos):
            a = f"?_a{i}_{sufixo}"
            lines.append(f"\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
            coalesce_val_args.append(a)
            # 1/0 dispara erro → COALESCE pula para o próximo campo bound.
            coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")
        lines += [
            f"\tBIND( COALESCE({', '.join(coalesce_val_args)}) AS ?{v_val} )",
            f"\tBIND( COALESCE({', '.join(coalesce_campo_args)}) AS ?{v_campo} )",
            # Nó sempre materializado (IRI determinístico registro+CID). O IRI
            # depende apenas de ?registro, então sobrevive mesmo após UNION.
            f'\tBIND( IRI(CONCAT( STR(?registro), "_inf_{inferred_value}" )) AS ?{v_inf} )',
        ]
        return lines, meta

    # ------------------------------------------------------------------
    # Cláusula IN (lista de strings ou variáveis)
    # ------------------------------------------------------------------

    @staticmethod
    def in_clause(terms: list[str], kind: str = "str") -> str:
        """
        Gera '( "a", "b", … )' para kind='str'
        ou '( ?a, ?b, … )'    para kind='var'.
        """
        if kind == "str":
            inner = '", "'.join(terms)
            return f'( "{inner}")'
        elif kind == "var":
            inner = ", ".join(f"?{t}" for t in terms)
            return f"( {inner})"
        raise ValueError(f"kind desconhecido: {kind!r}")

    # ------------------------------------------------------------------
    # VALUES clause
    # ------------------------------------------------------------------

    def values_clause(self, var_name: str, terms: list[str], kind: str = "str") -> str:
        """
        Gera 'VALUES ?var_name { "a" "b" … }\\n' com cache por var_name.
        """
        if var_name in self._declared_values:
            return self._declared_values[var_name]

        if kind == "str":
            inner = '" "'.join(terms)
            clause = f'VALUES ?{var_name} {{ "{inner}" }}\n'
        elif kind == "var":
            inner = " ".join(f"?{t}" for t in terms)
            clause = f"VALUES ?{var_name} {{ {inner} }}\n"
        else:
            raise ValueError(f"kind desconhecido: {kind!r}")

        self._declared_values[var_name] = clause
        return clause

    # ------------------------------------------------------------------
    # FILTER EXISTS com lista (IN)
    # ------------------------------------------------------------------

    def filter_exists_list_in_value(
        self,
        prop_vars: list[str],
        list_uris: list[str],
    ) -> list[str]:
        """
        Gera:
            FILTER EXISTS {
                ?registro ?_propr_N ?_value_M.
                FILTER ( ?_propr_N IN ( intox:P1, … ) ).
                FILTER ( ?_value_M IN ( "t1", "t2", … ) ).
            }
        """
        list_var_name, terms = self._resolve_terms(list_uris)
        props_str = ", ".join(f"intox:{p}" for p in prop_vars)
        values_str = ", ".join(f'"{t}"' for t in terms)

        v_prop = f"_propr_{self._c.next()}"
        v_val = f"_value_{self._c.next()}"

        return [
            "\tFILTER EXISTS {",
            f"\t\t?registro ?{v_prop} ?{v_val}.",
            f"\t\tFILTER ( ?{v_prop} IN ( {props_str})  ).",
            f"\t\tFILTER ( LCASE(STR(?{v_val})) IN ( {values_str})  ).",
            "\t}",
        ]

    def filter_list_agente_origem(
        self,
        prop_vars: list[str],
        list_uris: list[str],
    ) -> list[str]:
        """
        Igual a `filter_exists_list_in_value`, porém traz o casamento agente→lista
        para o CORPO do WHERE (fora de FILTER EXISTS), de modo que a propriedade
        que casou (?{v_prop}) e o valor casado (?{v_val}) fiquem VISÍVEIS ao
        CONSTRUCT. Registra o par em `self.origem_bindings` para o CONSTRUCT
        emitir o nó intox:temInferencia (CID + CAMPO_ORIGEM + VALOR_ORIGEM).

        Observação: como o casamento passa a estar no corpo, um registro cujos
        MÚLTIPLOS campos casem a MESMA lista gerará M bindings distintos (um por
        campo casado). Isso é exatamente a semântica desejada de rastreabilidade
        por campo de origem; a de-duplicação por CID (quando pertinente) fica a
        cargo do consumidor/tester.
        """
        _, terms = self._resolve_terms(list_uris)
        props_str = ", ".join(f"intox:{p}" for p in prop_vars)
        values_str = ", ".join(f'"{t}"' for t in terms)

        v_prop = f"_campo_origem_{self._c.next()}"
        v_val = f"_valor_origem_{self._c.next()}"

        self.origem_bindings.append((v_prop, v_val))

        return [
            f"\t?registro ?{v_prop} ?{v_val}.",
            f"\tFILTER ( ?{v_prop} IN ( {props_str})  ).",
            f"\tFILTER ( LCASE(STR(?{v_val})) IN ( {values_str})  ).",
        ]

    # ------------------------------------------------------------------
    # FILTER NOT EXISTS com lista (VALUES + STR match)
    # ------------------------------------------------------------------

    def filter_not_list(
        self,
        prop_vars: list[str],
        list_uris: list[str],
    ) -> list[str]:
        """
        Gera:
            FILTER NOT EXISTS {
                ?registro intox:P1|intox:P2 ?_vN.
                VALUES ?lista_termos_X { "t1" "t2" … }
                FILTER( ?_vN != "" && ?lista_termos_X = STR( ?_vN ) )
            }
        """
        if len(list_uris) > 1:
            list_var_name, terms = _consolidate_lists(list_uris, self._term_lists)
        else:
            idx = _extract_list_index(self._term_lists[list_uris[0]]["rdf:label"])
            list_var_name = _list_var_name(idx)
            # Normaliza para minúsculo para manter consistência com _consolidate_lists,
            # que sempre faz .lower() nos termos quando há múltiplas listas.
            terms = [t.lower() for t in self._term_lists[list_uris[0]]["termos"]]

        declaration = self.values_clause(list_var_name, terms)
        variable = f"_v{self._c.next()}"
        property_path = "|".join(f"intox:{p}" for p in prop_vars)

        return [
            "FILTER NOT EXISTS {",
            f"\t?registro {property_path} ?{variable}.",
            "\t" + declaration,
            f"\tFILTER( ?{variable} != \"\" && ?{list_var_name} = LCASE(STR( ?{variable} )) ) ",
            "}",
        ]

    # ------------------------------------------------------------------
    # FILTER inline (para LOC_EXP_DE dentro de LOC_EXPO)
    # ------------------------------------------------------------------

    def filter_list_inline(
        self,
        prop_vars: list[str],
        list_uris: list[str],
    ) -> list[str]:
        """
        Gera cláusula FILTER( ?v IN (...) ) inline, sem FILTER EXISTS.

        Nota: o código original usa o MESMO índice para _propN e _vN
        (ambos gerados em uma única incrementação), preservamos isso aqui.
        """
        shared_idx = self._c.next()
        v_prop = f"_prop{shared_idx}"
        v_val = f"_v{shared_idx}"

        _, terms = self._resolve_terms(list_uris)
        in_str = self.in_clause(terms)

        clauses: list[str] = []
        filters: list[str] = []

        if len(prop_vars) > 1:
            prop_list = "intox:" + ", intox:".join(prop_vars)
            clauses.append(f"?registro ?{v_prop} ?{v_val}.")
            filters.append(f"?{v_prop} IN ( {prop_list} )")
        else:
            clauses.append(f"?registro intox:{prop_vars[0]} ?{v_val}.")

        filters.append(f"LCASE(STR(?{v_val})) IN {in_str}")

        clauses.append("FILTER( ")
        add_and = False
        for f in filters:
            clauses.append("\t" + ("&& " if add_and else "") + "( " + f + " )")
            add_and = True
        clauses.append(")")
        return clauses

    # ------------------------------------------------------------------
    # Dispatcher: filter_list (escolhe EXISTS ou NOT dependendo do flag)
    # ------------------------------------------------------------------

    def filter_list(
        self,
        prop_vars: list[str],
        list_uris: list[str],
        not_exists: bool = False,
        filter_exists: bool = True,
    ) -> list[str]:
        if not_exists:
            if filter_exists:
                raise ValueError("not_exists=True é deprecado. Use filter_not_list diretamente.")
            return self.filter_not_list(prop_vars, list_uris)
        if filter_exists:
            return self.filter_exists_list_in_value(prop_vars, list_uris)
        return self.filter_list_inline(prop_vars, list_uris)

    # ------------------------------------------------------------------
    # Regra especial: agente com lógica para X70
    # ------------------------------------------------------------------

    def regra_complexa_agente_x70(
        self,
        var_name: str,
        var_value: str,
        inferred_value: str | None = None,
        campos_agente: list[str] | None = None,
    ) -> list[str]:
        """Gera cláusula para a regra especial de agente do X70, expondo a ORIGEM
        da inferência (nó intox:temInferencia) para AMBOS os ramos.

        Estrutura (UNION auto-contida no topo do WHERE — cada ramo vincula ?tox,
        ?_campo_x70, ?_valor_x70 e ?_inf_x70 internamente; NUNCA deixar essas vars
        cruzarem a fronteira do UNION para um BIND externo, sob pena de o CONSTRUCT
        não materializar nada):

          Ramo A (AGENTE_TOX ∈ {02,03,04,05}, qualquer conteúdo):
            • O CID é inferido independentemente do agente estar preenchido.
            • CAMPO_ORIGEM = PRIMEIRO campo de agente preenchido (ordem AGENTE_1 →
              AGENTE_2 → AGENTE_3 → P_ATIVO_1 → P_ATIVO_2 → P_ATIVO_3), via
              OPTIONAL + COALESCE; VALOR_ORIGEM = o texto desse campo.
            • Se NENHUM campo estiver preenchido, ?_campo_x70/?_valor_x70 ficam
              unbound — o nó ainda é materializado (IRI só do registro+CID) com o
              CID, e os triplos CAMPO/VALOR_ORIGEM simplesmente não são gerados
              (sem perda de cobertura de inferência).

          Ramo B (AGENTE_TOX ∈ {07,09,14} E agente casa lista_23/lista_24):
            • CAMPO_ORIGEM = a propriedade que casou; VALOR_ORIGEM = o valor casado.
        """
        list_var_name, terms = _consolidate_lists(
            ["intox:lista_23", "intox:lista_24"], self._term_lists
        )
        values_str = ", ".join(f'"{t}"' for t in terms)

        # Ordem de prioridade dos campos de agente para o Ramo A.
        campos = campos_agente or [
            "AGENTE_1", "AGENTE_2", "AGENTE_3",
            "P_ATIVO_1", "P_ATIVO_2", "P_ATIVO_3",
        ]
        cid = inferred_value or ""

        # Variáveis fixas de saída (referenciadas pelo CONSTRUCT).
        v_campo = "_campo_x70"
        v_val = "_valor_x70"
        v_inf = "_inf_x70"
        self.origem_x70 = {"campo": v_campo, "valor": v_val, "inf": v_inf, "cid": cid}

        # ---- Ramo A: OPTIONAL por campo + COALESCE do primeiro preenchido ----
        opt_lines: list[str] = []
        coalesce_val_args: list[str] = []
        coalesce_campo_args: list[str] = []
        for i, c in enumerate(campos):
            a = f"?_a{i}_x70"
            opt_lines.append(f"\t\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
            coalesce_val_args.append(a)
            # 1/0 dispara erro → COALESCE pula para o próximo campo bound.
            coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")

        ramo_a = [
            "\t{",
            "\t\t?registro intox:AGENTE_TOX ?AGENTE_TOX_value.",
            "\t\tFILTER( ?AGENTE_TOX_value IN ( intox:categoria_AGENTE_TOX_02, "
            "intox:categoria_AGENTE_TOX_03, intox:categoria_AGENTE_TOX_04, "
            "intox:categoria_AGENTE_TOX_05 ) )",
            *opt_lines,
            f"\t\tBIND( COALESCE({', '.join(coalesce_val_args)}) AS ?{v_val} )",
            f"\t\tBIND( COALESCE({', '.join(coalesce_campo_args)}) AS ?{v_campo} )",
            # Nó SEMPRE materializado (IRI só do registro+CID): garante que o Ramo A
            # infira o CID mesmo com agente vazio.
            f'\t\tBIND( IRI(CONCAT( STR(?registro), "_inf_{cid}" )) AS ?{v_inf} )',
            "\t}",
        ]

        # ---- Ramo B: casamento do agente com lista_23/24, origem explícita ----
        props_str = ", ".join(f"intox:{p}" for p in campos)
        ramo_b = [
            "\tUNION",
            "\t{",
            "\t\t?registro intox:AGENTE_TOX ?AGENTE_TOX_value.",
            "\t\tFILTER( ?AGENTE_TOX_value IN ( intox:categoria_AGENTE_TOX_07, "
            "intox:categoria_AGENTE_TOX_09, intox:categoria_AGENTE_TOX_14 ) )",
            f"\t\t?registro ?{v_campo} ?{v_val}.",
            f"\t\tFILTER( ?{v_campo} IN ( {props_str} ) )",
            f"\t\tFILTER( LCASE(STR(?{v_val})) IN ( {values_str} ) )",
            f'\t\tBIND( IRI(CONCAT( STR(?registro), "_inf_{cid}_", '
            f"ENCODE_FOR_URI(STR(?{v_campo})), \"_\", "
            f"ENCODE_FOR_URI(STR(?{v_val})) )) AS ?{v_inf} )",
            "\t}",
        ]

        return ramo_a + ramo_b

    def regra_agente_tox_qualquer_conteudo(
        self,
        campos_agente: list[str],
        categorias: list[str],
        inferred_value: str,
    ) -> list[str]:
        """Forma REDUZIDA do padrão X70 (planilha nova):

            (qualquer conteúdo)
            quando AGENTE_TOX = <categorias>

        Semântica (confirmada com o PO): infere o CID quando
        AGENTE_TOX ∈ {categorias lidas da planilha}, aceitando QUALQUER conteúdo
        nos campos de agente (sem exigir termo em lista) e SEM o antigo Ramo B
        (listas 23/24 + AGENTE_TOX 07,09,14).

        Equivale ao Ramo A de `regra_complexa_agente_x70`, porém com as categorias
        PARAMETRIZADAS (não mais fixas em {02,03,04,05}) e sem UNION. Expõe a
        origem (CAMPO_ORIGEM/VALOR_ORIGEM) do PRIMEIRO campo de agente preenchido
        via OPTIONAL + COALESCE; se nenhum estiver preenchido, o nó ainda é
        materializado só com o CID (sem perda de cobertura).
        """
        campos = campos_agente or [
            "AGENTE_1", "AGENTE_2", "AGENTE_3",
            "P_ATIVO_1", "P_ATIVO_2", "P_ATIVO_3",
        ]
        cid = inferred_value or ""

        v_campo = "_campo_x70"
        v_val = "_valor_x70"
        v_inf = "_inf_x70"
        self.origem_x70 = {"campo": v_campo, "valor": v_val, "inf": v_inf, "cid": cid}

        # Filtro de categorias AGENTE_TOX vindas da planilha (parametrizado).
        cats_str = ", ".join(f"intox:categoria_AGENTE_TOX_{c}" for c in categorias)

        # OPTIONAL por campo + COALESCE do primeiro preenchido (idêntico ao Ramo A).
        opt_lines: list[str] = []
        coalesce_val_args: list[str] = []
        coalesce_campo_args: list[str] = []
        for i, c in enumerate(campos):
            a = f"?_a{i}_x70"
            opt_lines.append(f"\t\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
            coalesce_val_args.append(a)
            coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")

        return [
            "\t{",
            "\t\t?registro intox:AGENTE_TOX ?AGENTE_TOX_value.",
            f"\t\tFILTER( ?AGENTE_TOX_value IN ( {cats_str} ) )",
            *opt_lines,
            f"\t\tBIND( COALESCE({', '.join(coalesce_val_args)}) AS ?{v_val} )",
            f"\t\tBIND( COALESCE({', '.join(coalesce_campo_args)}) AS ?{v_campo} )",
            f'\t\tBIND( IRI(CONCAT( STR(?registro), "_inf_{cid}" )) AS ?{v_inf} )',
            "\t}",
        ]

    # ------------------------------------------------------------------
    # Regra especial: agente com filtro NOT EXISTS complexo
    # ------------------------------------------------------------------

    def filtro_not_exists_agente(
        self,
        var_name: str,
        not_empty: bool = False,
        padroes_irmas: list[dict] | None = None,
        inferred_value: str | None = None,
        campos_agente: list[str] | None = None,
    ) -> list[str]:
        """
        Filtro X89: exclui os registros que JÁ são inferidos pelas regras irmãs
        X86-X88 (coluna G = 'CID não foi inferido nas regras de X86-X88').

        Se `padroes_irmas` for fornecido (derivado dinamicamente das regras
        X86-X88 pela função `_padroes_agente_das_regras_irmas`), o filtro é
        construído a partir dele. Caso contrário, mantém o comportamento antigo
        (listas hard-coded 21,22,28,29 / 23,24) como fallback de compatibilidade.

        Se `inferred_value` for fornecido, também expõe a ORIGEM da inferência
        (nó intox:temInferencia): CAMPO_ORIGEM = PRIMEIRO campo de agente
        preenchido (ordem AGENTE_1 → … → P_ATIVO_3), VALOR_ORIGEM = seu texto,
        via OPTIONAL + COALESCE (mesma semântica do Ramo A do X70). O nó é
        materializado com IRI determinístico (registro+CID); os triplos
        CAMPO/VALOR_ORIGEM só aparecem quando há campo preenchido — o que, no
        X89, é sempre verdade dado o pré-requisito positivo (`not_empty`).
        """
        all_variables = var_name.replace(";", ", intox:")
        var_value = "agente_path_value"

        if padroes_irmas:
            disjuncoes = self._disjuncoes_padroes_irmas(padroes_irmas, var_value)
        else:
            # Fallback (comportamento legado com listas hard-coded).
            _, terms1 = _consolidate_lists(
                ["intox:lista_21", "intox:lista_22", "intox:lista_28", "intox:lista_29"],
                self._term_lists,
            )
            _, terms2 = _consolidate_lists(
                ["intox:lista_23", "intox:lista_24"], self._term_lists
            )
            disjuncoes = [
                [f"LCASE(STR(?{var_value})) IN " + self.in_clause(terms1)],
                ["?AGENTE_TOX_value IN ( intox:categoria_AGENTE_TOX_02, intox:categoria_AGENTE_TOX_03, intox:categoria_AGENTE_TOX_04, intox:categoria_AGENTE_TOX_05 )"],
                [
                    "?AGENTE_TOX_value IN ( intox:categoria_AGENTE_TOX_07, intox:categoria_AGENTE_TOX_09, intox:categoria_AGENTE_TOX_14 )",
                    "&&",
                    f"LCASE(STR(?{var_value})) IN " + self.in_clause(terms2),
                ],
            ]

        v_prop = f"_v{self._c.next()}"

        lines: list[str] = []
        # Pré-requisito POSITIVO da coluna C do X89: "se pelo menos um dos campos
        # de texto livre estiver preenchido". Sem esta cláusula, registros com
        # agente vazio satisfaziam X89 E X90 (AGENTE_TOX≠99 + agente vazio),
        # gerando dupla inferência X89x↔X90x. Exigir a EXISTÊNCIA de ao menos um
        # AGENTE_*/P_ATIVO_* não-vazio torna X89 e X90 mutuamente exclusivos.
        if not_empty:
            v_ok = f"_v{self._c.next()}"
            v_ok_val = f"{v_ok}_value"
            lines += [
                "\tFILTER EXISTS {",
                f"\t\t?registro ?{v_ok} ?{v_ok_val}.",
                "\t\tFILTER (",
                f"\t\t\t?{v_ok} IN ( intox:{all_variables} )",
                "\t\t\t&&",
                f"\t\t\t( STRLEN(STR(?{v_ok_val}))>0 )",
                "\t\t).",
                "\t}",
            ]

        lines += [
            "\tFILTER NOT EXISTS {",
            f"\t\t?registro ?{v_prop} ?{var_value}.",
            f"\t\tFILTER ( ",
            f"\t\t\t?{v_prop} IN ( intox:{all_variables} )",
            "\t\t\t&&",
        ]
        if not_empty:
            lines += [
                f"\t\t\t( STRLEN(STR(?{var_value}))>0 )",
                "\t\t\t&&",
            ]
        # Une as disjunções (uma por padrão irmão) com '||'.
        for i, bloco in enumerate(disjuncoes):
            lines.append("\t\t\t(" if i == 0 else "\t\t\t) || (")
            for ln in bloco:
                lines.append(f"\t\t\t\t{ln}")
        lines += [
            "\t\t\t)",
            "\t\t).",
            "\t}",
        ]

        # ---- Origem da inferência (nó intox:temInferencia) ----
        # PRIMEIRO campo de agente preenchido, via helper universal (idêntico
        # ao Ramo A do X70). Sem UNION aqui, então o BIND do nó fica no corpo.
        if inferred_value is not None:
            origem_lines, meta = self._origem_agente_lines(
                inferred_value, sufixo="x89", campos=campos_agente
            )
            lines += origem_lines
            self.origem_x89 = meta

        return lines

    def _disjuncoes_padroes_irmas(
        self,
        padroes_irmas: list[dict],
        var_value: str,
    ) -> list[list[str]]:
        """
        Converte os padrões derivados das regras irmãs (X86-X88) em blocos de
        disjunção SPARQL para o FILTER NOT EXISTS do X89. Cada bloco é uma lista
        de linhas que serão unidas por '||' no chamador.
        """
        blocos: list[list[str]] = []
        for pad in padroes_irmas:
            if pad["tipo"] == "lista":
                uris = [f"intox:lista_{n}" for n in pad["listas"]]
                _, termos = _consolidate_lists(uris, self._term_lists)
                blocos.append([f"LCASE(STR(?{var_value})) IN " + self.in_clause(termos)])
            elif pad["tipo"] == "agente_tox":
                cats = ", ".join(
                    f"intox:categoria_AGENTE_TOX_{c}" for c in pad["categorias"]
                )
                bloco = [f"?AGENTE_TOX_value IN ( {cats} )"]
                if pad["listas"]:
                    uris = [f"intox:lista_{n}" for n in pad["listas"]]
                    _, termos = _consolidate_lists(uris, self._term_lists)
                    bloco += ["&&", f"LCASE(STR(?{var_value})) IN " + self.in_clause(termos)]
                blocos.append(bloco)
        return blocos

    # ------------------------------------------------------------------
    # Regra especial: campos de texto livre preenchidos + CID não inferido
    # ------------------------------------------------------------------

    def regra_agente_preenchimento_e_cid_nao_inferido(
        self,
        campos: str,
        inferred_prop: str,
    ) -> list[str]:
        union_clauses = []
        for c in campos.split(";"):
            uri = f"intox:{c}"
            var = f"not_empty_{c}"
            union_clauses.append(
                f"\t\t?registro {uri} ?{var}.\n\t\tFILTER( STRLEN(STR(?{var})) > 0 )"
            )

        lines = ["{"]
        lines.append("\t{\n" + "\n\t}\n\tUNION {\n".join(union_clauses) + "\n\t}\n")
        lines.append("}")
        lines.append("FILTER NOT EXISTS { ")
        lines.append(f"\t?registro intox:{inferred_prop} ?somecid.")
        lines.append('\tFILTER( REGEX(STR(?somecid), "^X8(6|7|8)\\\\b") )\n}\n')
        return lines

    # ------------------------------------------------------------------
    # Regra especial: agente com exclusão de lista
    # ------------------------------------------------------------------

    def regra_agente_lista_exclusao(
        self,
        campos: str,
        values: list[str],
        cid_exclusao: list[str] | None = None,
        exclusao_uris: list[str] | None = None,
    ) -> list[str]:
        # Prefixo comum aos dois formatos:
        #   antigo: "...não for rastreado pelas listas 1-8"
        #   novo (D2/D4): "...não for rastreado nos CIDS de exclusão" (faixa na col. G)
        if values[1].startswith(
            "ou quando o texto preenchido nos campos não for rastreado"
        ):
            range_lists_str = re.findall(r"([0-9]{1,2}-[0-9]{1,2})", values[1])
            if range_lists_str:
                uri_listas: list[str] = []
                for r in range_lists_str:
                    inicio, fim = (int(v) for v in r.split("-"))
                    uri_listas += [_list_uri_from_name(f"LISTA {i}") for i in range(inicio, fim + 1)]
                return self.filter_not_list(campos.split(";"), uri_listas)
            # Formato novo (D2/D4): faixa de CID na coluna G.
            # Fonte primária: listas derivadas das regras IRMÃS (X400-X439)
            # cujo CID inferido cai na faixa (união das LISTAS que elas usam).
            if exclusao_uris:
                return self.filter_not_list(campos.split(";"), exclusao_uris)
            # Fallback: mapeamento por codigo_cid10 dos metadados da aba LISTAS.
            uri_listas = self._listas_por_faixa_cid(cid_exclusao or [])
            if uri_listas:
                return self.filter_not_list(campos.split(";"), uri_listas)
            raise ValueError(
                f"Faixas de exclusão não encontradas: {values[1]!r} / "
                f"CID_EXCLUSAO={cid_exclusao!r}"
            )

        if values == ["null", "", "qualquer valor, quando AGENTE_TOX = 99"]:
            campos_uri = " ".join(f"intox:{c}" for c in campos.split(";"))
            return [
                "\t{",
                "\t\t?registro intox:AGENTE_TOX intox:categoria_AGENTE_TOX_99.",
                f"\t\tVALUES ?agente_prop {{ {campos_uri} }}.",
                "\t\t?registro ?agente_prop ?agente_value.",
                '\t\tFILTER ( ?agente_value != "" ).',
                "\t} UNION {",
                "\t\t?registro intox:AGENTE_TOX ?agente_tox",
                "\t\tFILTER(?agente_tox != intox:categoria_AGENTE_TOX_99). ",
                "\t\tFILTER NOT EXISTS {",
                f"\t\t\tVALUES ?agente_prop {{ {campos_uri} }}.",
                "\t\t\t?registro ?agente_prop ?agente_value.",
                '\t\t\tFILTER ( ?agente_value != "" ).',
                "\t\t}",
                "\t}",
            ]

        raise ValueError(f"Regra de exclusão desconhecida: {''.join(values)!r}")

    def _listas_por_faixa_cid(self, cid_ranges: list[str]) -> list[str]:
        """
        Mapeia faixa(s) de CID (ex.: 'X40-X43', da coluna G) para as URIs das
        listas cujo intox:codigo_cid10 cai dentro da faixa (migração D2/D4).
        """
        def parse_cid(c: str) -> tuple[str, int]:
            c = c.strip()
            return c[0], int(c[1:])

        faixas: list[tuple] = []
        for token in cid_ranges:
            for a, b in re.findall(r"([A-Za-z][0-9]{2})\s*[-–—]\s*([A-Za-z][0-9]{2})", token):
                faixas.append((parse_cid(a), parse_cid(b)))
        if not faixas:
            return []

        uris: list[str] = []
        for uri, dados in self._term_lists.items():
            for cid in dados.get("intox:codigo_cid10", []):
                try:
                    p = parse_cid(cid)
                except (ValueError, IndexError):
                    continue
                if any(ini <= p <= fim for ini, fim in faixas):
                    uris.append(uri)
                    break
        return uris

    # ------------------------------------------------------------------
    # Regra especial: Volume III CID-10 (lista de substâncias por CID)
    # ------------------------------------------------------------------

    def regra_volume_iii_cid(
        self,
        var_name: str,
        inferred_cid: str,
    ) -> list[str]:
        """Filtra pelos termos do Volume III do CID-10 para o CID inferido."""
        icd = inferred_cid[0:3] + "." + inferred_cid[3]
        substances = self._icd_to_substances.get(icd)
        if substances is None:
            raise KeyError(f"CID {icd} não encontrado na tabela de substâncias.")

        # Insere lista temporária diretamente em self._term_lists para que
        # _resolve_terms consiga encontrá-la; remove após o uso.
        self._term_lists["intox:lista_99"] = {
            "rdf:label": "Lista 99",
            "termos": substances,
        }
        old_declared = self._declared_values.copy()
        self._declared_values.clear()

        try:
            clause = self.filter_exists_list_in_value(var_name.split(";"), ["intox:lista_99"])
        finally:
            # Garante remoção mesmo em caso de exceção
            self._term_lists.pop("intox:lista_99", None)
            self._declared_values = old_declared

        return clause

    # ------------------------------------------------------------------
    # LOC_EXPO / LOC_EXP_DE
    # ------------------------------------------------------------------

    def regra_local_exposicao(
        self,
        values: list[str],
        ontology: "OntologyLoader",
    ) -> list[str]:
        """
        Gera a cláusula SPARQL para o campo LOC_EXPO;LOC_EXP_DE.
        Pode combinar valores de opção categórica com referências a listas.
        """
        values_option: list[str] = []
        values_listas: list[str] = []
        negation_list = False

        for v in values:
            if "LISTA" in v:
                values_listas.append(v)
            elif v.startswith(
                "7. Outro, quando o texto preenchido em LOC_EX_DE não for rastreado pelas listas"
            ):
                list_range = _get_list_range(v)
                values_listas += [f"LISTA {i}" for i in list_range]
                negation_list = True
            else:
                prop = ontology.get_uri_for_option("LOC_EXPO", v)
                try:
                    values_option.append(f"intox:{prop.name}")
                except Exception:
                    print(">", v)
                    raise

        # O contador é sempre avançado aqui para manter compatibilidade com o
        # comportamento original: o índice é consumido independente de haver
        # values_option ou não.
        prop_val = f"_v{self._c.next()}"
        results: list[str] = []

        if values_option:
            results.append("\t{")
            results.append(f"\t\t?registro intox:LOC_EXPO ?{prop_val}.")
            results.append(
                f"\t\tFILTER( ?{prop_val} IN ( " + ",".join(values_option) + " ) )."
            )
            results.append("\t}")

        if values_listas:
            q = ["\t\t?registro intox:LOC_EXPO intox:categoria_LOC_EXPO_7."]

            if negation_list:
                # O join posterior usa "\n\t\t" como separador, acrescentando
                # \t\t a cada elemento a partir do segundo. Para obter
                # "\t\t\tFILTER NOT EXISTS {" na saída, o elemento deve
                # ter apenas um \t (1 + 2 do join = 3 tabs).
                q += ["\tFILTER NOT EXISTS {"]

            uri_listas = [_list_uri_from_name(v) for v in values_listas]
            inner = self.filter_list_inline(["LOC_EXP_DE"], uri_listas)
            q += inner

            if negation_list:
                # O join adiciona \t\t antes deste elemento.
                # Referência quer "\t\t}" (2 tabs) → elemento precisa de 0 tabs
                # pois o join já contribui com 2.
                q += ["}"]

            if values_option:
                results.append("\tUNION {")
            results.append("\n\t\t".join(q))
            if values_option:
                results.append("\t}")

        return results

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _resolve_terms(
        self, list_uris: list[str]
    ) -> tuple[str, list[str]]:
        """Retorna (var_name, termos) de uma ou mais listas."""
        if len(list_uris) > 1:
            return _consolidate_lists(list_uris, self._term_lists)
        idx = _extract_list_index(self._term_lists[list_uris[0]]["rdf:label"])
        terms = [t.lower() for t in self._term_lists[list_uris[0]]["termos"]]
        return _list_var_name(idx), terms


# ===========================================================================
# PROCESSADOR DE REGRAS (converte uma linha da planilha em SPARQL)
# ===========================================================================

class RuleProcessor:
    """
    Converte uma linha da planilha (dict campo → valores) em uma query
    SPARQL CONSTRUCT completa.
    """

    _AGENTE_X70_PATTERN = (
        "(qualquer conteúdo)|quando AGENTE_TOX = 02, 03, 04 ou 05"
        "||LISTA 23|LISTA 24|quando AGENTE_TOX = 07, 09 ou 14"
    )
    _AGENTE_X89_PATTERN = (
        "se pelo menos um dos campos de texto livre estiver preenchido"
        "||E||CID não foi inferido nas regras de X86-X88"
    )

    def __init__(
        self,
        ontology: OntologyLoader,
        term_lists: dict[str, dict],
        icd_to_substances: dict[str, list[str]],
        config: Config,
    ):
        self._ontology = ontology
        self._term_lists = term_lists
        self._icd_to_substances = icd_to_substances
        self._config = config

    def rule_to_sparql(
        self, rule: dict[str, list[str]], line_number: int = 0
    ) -> list[str]:
        """
        Transforma uma linha de regras em uma query SPARQL CONSTRUCT.
        Retorna uma lista de linhas (strings) da query.
        """
        counter = SparqlVarCounter()
        builder = SparqlClauseBuilder(counter, self._term_lists, self._icd_to_substances)
        inferred_prop = self._config.inferred_cid_prop

        inferred_value = rule[inferred_prop][0]

        # Processa PRIMEIRO o corpo do WHERE; assim `builder.origem_bindings`
        # fica populado com os pares (campo, valor) do casamento agente→lista
        # ANTES de montarmos o CONSTRUCT (que passa a referenciá-los).
        where_lines: list[str] = []
        for var_name, values in rule.items():
            if var_name in (
                inferred_prop,
                "CID_EXCLUSAO",
                "_EXCLUSAO_LISTAS_URIS",
                "_PADROES_IRMAS_X89",
            ):
                continue

            if not values or (
                var_name.startswith("AGENTE") and len(values) == 1
                and values[0] == "(qualquer conteúdo)"
            ):
                continue

            where_lines += self._process_field(
                var_name, values, rule, builder, inferred_prop, line_number
            )

        # Monta o CONSTRUCT. Se houve casamento de agente com origem exposta,
        # emite o nó intox:temInferencia (CID + CAMPO_ORIGEM + VALOR_ORIGEM),
        # um por binding. Caso contrário (regras sem campo de agente padrão —
        # ex.: rotas AGENTE_TOX-condicionada/X89 ou puramente categóricas),
        # mantém o formato antigo `?registro intox:<prop> "CID"`.
        construct: list[str] = ["CONSTRUCT {"]
        bind_lines: list[str] = []
        if builder.origem_x70 or builder.origem_x89:
            # Rotas X70/X89: o WHERE já vinculou ?_campo/?_valor/?_inf (no X70,
            # dentro de cada ramo da UNION auto-contida; no X89, direto no corpo).
            # O CONSTRUCT apenas referencia essas vars; NENHUM BIND externo
            # (no X70 quebraria o escopo do UNION; no X89 já está no corpo).
            ox = builder.origem_x70 or builder.origem_x89
            inf = f"?{ox['inf']}"
            construct += [
                f"?registro intox:temInferencia {inf}.",
                f'{inf} intox:CID "{ox["cid"]}".',
                f"{inf} intox:CAMPO_ORIGEM ?{ox['campo']}.",
                f"{inf} intox:VALOR_ORIGEM ?{ox['valor']}.",
            ]
        elif builder.origem_bindings:
            for idx, (v_prop, v_val) in enumerate(builder.origem_bindings):
                inf = f"?_inf_{idx}"
                construct += [
                    f"?registro intox:temInferencia {inf}.",
                    f'{inf} intox:CID "{inferred_value}".',
                    f"{inf} intox:CAMPO_ORIGEM ?{v_prop}.",
                    f"{inf} intox:VALOR_ORIGEM ?{v_val}.",
                ]
                # O nó de inferência precisa estar VINCULADO no WHERE, senão o
                # CONSTRUCT não materializa os triplos. Gera um IRI determinístico
                # a partir do registro + CID + campo + valor de origem, de modo
                # que cada (registro, campo, valor) distinto vire um nó único.
                # ATENÇÃO: o IRI resultante precisa ser VÁLIDO, senão IRI() devolve
                # unbound e o CONSTRUCT não materializa nada. Por isso NUNCA inserir
                # um segundo '#' nem concatenar um IRI cru (que já contém '#'):
                # os componentes dinâmicos (propriedade e valor) são ENCODADOS via
                # ENCODE_FOR_URI e apenas ANEXADOS ao IRI do registro (que termina
                # em '#<id>'), formando um sufixo seguro no mesmo fragmento.
                bind_lines.append(
                    f"\tBIND( IRI(CONCAT( STR(?registro), "
                    f'"_inf_{inferred_value}_", ENCODE_FOR_URI(STR(?{v_prop})), '
                    f'"_", ENCODE_FOR_URI(STR(?{v_val})) )) AS {inf} )'
                )
        else:
            # Caminho UNIVERSAL: nenhuma rota especializada expôs origem (rotas
            # puramente categóricas, agente-exclusão, Volume III, local de
            # exposição). Emite o nó intox:temInferencia com o CID sempre; se o
            # registro tiver algum campo de agente preenchido, expõe o PRIMEIRO
            # como CAMPO_ORIGEM/VALOR_ORIGEM (via helper). As linhas de origem
            # vão para o FIM do WHERE (após o corpo), pois o BIND do nó depende
            # apenas de ?registro — sempre vinculado no escopo externo, inclusive
            # após UNION — sem tocar variáveis internas de nenhum ramo.
            origem_lines, meta = builder._origem_agente_lines(
                inferred_value, sufixo="univ"
            )
            builder.origem_universal = meta
            where_lines += origem_lines
            inf = f"?{meta['inf']}"
            construct += [
                f"?registro intox:temInferencia {inf}.",
                f'{inf} intox:CID "{meta["cid"]}".',
                f"{inf} intox:CAMPO_ORIGEM ?{meta['campo']}.",
                f"{inf} intox:VALOR_ORIGEM ?{meta['valor']}.",
            ]
        construct.append("} WHERE {")

        query: list[str] = construct + where_lines + bind_lines
        query.append("}")
        return query

    # ------------------------------------------------------------------
    # Despacho por tipo de campo / conteúdo
    # ------------------------------------------------------------------

    def _process_field(
        self,
        var_name: str,
        values: list[str],
        full_rule: dict,
        builder: SparqlClauseBuilder,
        inferred_prop: str,
        line_number: int,
    ) -> list[str]:
        joined = "|".join(values)

        # Regra especial: agente com lógica X70
        if var_name.startswith("AGENTE") and joined == self._AGENTE_X70_PATTERN:
            clean_name = var_name.replace(";", "|intox:")
            return builder.regra_complexa_agente_x70(
                clean_name,
                "agente_path_value",
                inferred_value=full_rule[inferred_prop][0],
                campos_agente=var_name.split(";"),
            )

        # Regra especial: forma REDUZIDA do X70 (planilha nova) —
        # '(qualquer conteúdo) quando AGENTE_TOX = <cats>' SEM listas/Ramo B.
        # Detecção: campo de agente cujo 1º token é '(qualquer conteúdo)', que
        # tem ao menos uma cláusula 'quando AGENTE_TOX = ...' e NENHUM 'LISTA'
        # (a presença de LISTA caracterizaria o antigo padrão X70 completo, já
        # capturado acima por igualdade exata). As categorias são lidas da
        # própria planilha (parametrizadas), não mais fixas em {02,03,04,05}.
        if (
            var_name.startswith("AGENTE")
            and values
            and values[0].strip() == "(qualquer conteúdo)"
            and any("AGENTE_TOX" in v for v in values)
            and not any("LISTA" in v for v in values)
        ):
            categorias = _parse_agente_tox_categorias(" ".join(values))
            return builder.regra_agente_tox_qualquer_conteudo(
                campos_agente=var_name.split(";"),
                categorias=categorias,
                inferred_value=full_rule[inferred_prop][0],
            )

        # Regra especial: campos de texto livre preenchidos + CID não inferido
        if var_name.startswith("AGENTE") and joined == self._AGENTE_X89_PATTERN:
            return builder.filtro_not_exists_agente(
                var_name,
                not_empty=True,
                padroes_irmas=full_rule.get("_PADROES_IRMAS_X89"),
                inferred_value=full_rule[inferred_prop][0],
                campos_agente=var_name.split(";"),
            )

        # Regra especial: LOC_EXPO + LOC_EXP_DE combinados
        if var_name == "LOC_EXPO;LOC_EXP_DE":
            return builder.regra_local_exposicao(values, self._ontology)

        # Regra especial: agente com exclusão de lista
        if var_name.startswith("AGENTE") and values[0] == "null":
            return builder.regra_agente_lista_exclusao(
                var_name,
                values,
                full_rule.get("CID_EXCLUSAO"),
                full_rule.get("_EXCLUSAO_LISTAS_URIS"),
            )

        # Termos do Volume III do CID-10
        if values[0] == "Termos do volume III do CID-10 vinculados a esse código":
            return builder.regra_volume_iii_cid(var_name, full_rule[inferred_prop][0])

        # Campo com valores que referenciam listas de termos
        if "LISTA" in values[0]:
            uri_listas = [_list_uri_from_name(v) for v in values]
            campos = var_name.split(";")
            # Caminho PADRÃO agente→lista: expor o campo/valor de origem (nó
            # intox:temInferencia). Demais campos com LISTA seguem o filtro
            # existencial usual (sem exposição de origem).
            if var_name.startswith("AGENTE"):
                return builder.filter_list_agente_origem(campos, uri_listas) + [""]
            return builder.filter_list(campos, uri_listas) + [""]

        # Campo com valores de opção categórica (ou regra CLASSI_FIN especial)
        return self._process_categorical_field(var_name, values, builder, inferred_prop, line_number)

    def _process_categorical_field(
        self,
        var_name: str,
        values: list[str],
        builder: SparqlClauseBuilder,
        inferred_prop: str,
        line_number: int,
    ) -> list[str]:
        """Trata campos cujos valores são opções categóricas da ontologia."""
        var_value = f"{var_name}_value"
        my_uris = []
        lines: list[str] = []

        for v in values:
            # Caso especial: "01 Uso habitual, se CLASSI_FIN == N"
            classi_match = re.findall(
                r"^01 Uso habitual, se CLASSI_FIN\s*==\s*([0-9]{1,2})", v
            )
            if classi_match:
                circunstan = self._ontology.get_uri_for_option("CIRCUNSTAN", "01")
                classi_fin = self._ontology.get_uri_for_option("CLASSI_FIN", classi_match[0])
                circ_name = circunstan.name.replace(".", ":")
                classi_name = classi_fin.name.replace(".", ":")
                lines += [
                    "\t{",
                    f"\t\t?registro intox:CIRCUNSTAN intox:{circ_name}.",
                    "\t\t?registro intox:CLASSI_FIN ?valor_classi_fin.",
                    f"\t\tFILTER ( ?valor_classi_fin = intox:{classi_name} )",
                    "\t} UNION ",
                ]
                continue

            prop = self._ontology.get_uri_for_option(var_name, v)
            if prop is None:
                print(values)
                raise ValueError(
                    f"Valor '{v}' não encontrado para coluna '{var_name}' "
                    f"na linha {line_number} da planilha."
                )
            my_uris.append(prop)

        if len(values) > 1:
            values_txt = ",".join(f"intox:{p.name}" for p in my_uris)
            lines += [
                "\t{",
                f"\t\t?registro intox:{var_name} ?{var_value}.",
                f"\t\tFILTER ( ?{var_value} IN ( {values_txt} ) ).",
                "\t}",
                "",
            ]
        elif my_uris:
            lines += [
                "\t{",
                f"?registro intox:{var_name} intox:{my_uris[0].name}.",
                "\t}",
                "",
            ]

        return lines


# ===========================================================================
# EXPORTADORES JSON
# ===========================================================================

def build_sparql_rules_json(
    workbook_data: dict[str, list[dict]],
    rule_processor: RuleProcessor,
    icd_to_substances: dict[str, list[str]],
    config: Config,
) -> dict[str, list[dict]]:
    """
    Processa todas as abas de regras e retorna o dicionário
    { nome_aba: [ { inferred_cid, aba_excel, sparql }, … ] }.
    """
    result: dict[str, list[dict]] = {}

    for aba_cfg in config.rule_sheets:
        nome = aba_cfg["nome"]
        regras = workbook_data[nome]
        print(nome, aba_cfg["linha_inicial"], aba_cfg["linha_final"])
        result[nome] = []
        line_num = aba_cfg["linha_inicial"]

        # Deriva as listas de exclusão das regras "catch-all" (null / não
        # rastreado) a partir das regras IRMÃS da mesma aba cujo CID inferido
        # cai na faixa da coluna G (CID_EXCLUSAO). Injetado na regra sob a
        # chave interna _EXCLUSAO_LISTAS_URIS para uso na geração do SPARQL.
        for regra in regras:
            cid_exclusao = regra.get("CID_EXCLUSAO") or []
            if not cid_exclusao:
                continue
            faixas = _parse_cid_faixas(cid_exclusao)
            if not faixas:
                continue
            regra["_EXCLUSAO_LISTAS_URIS"] = _listas_exclusao_das_regras_irmas(
                regras, faixas, config.inferred_cid_prop
            )

        # Deriva DINAMICAMENTE os padrões das regras irmãs X86-X88 para as regras
        # X89x (coluna G = 'CID não foi inferido nas regras de X86-X88'). Substitui
        # as listas hard-coded do filtro `filtro_not_exists_agente`. Aplica-se às
        # regras cujo texto de agente casa com o padrão X89 (Mecanismo B).
        for regra in regras:
            colg = " ".join(str(v) for v in (regra.get("CID_EXCLUSAO") or []))
            m = re.search(
                r"não foi inferido nas regras de\s+([A-Za-z][0-9]{2})\s*[-\u2010\u2011\u2012\u2013\u2014]\s*([A-Za-z][0-9]{2})",
                colg,
            )
            if not m:
                continue
            ini, fim = _parse_cid_token(m.group(1)), _parse_cid_token(m.group(2))
            # Prefixos de CID de 3 caracteres cobertos pela faixa (ex.: X86,X87,X88).
            prefixos = tuple(
                f"{ini[0]}{n:02d}" for n in range(ini[1], fim[1] + 1)
            )
            regra["_PADROES_IRMAS_X89"] = _padroes_agente_das_regras_irmas(
                regras, prefixos, config.inferred_cid_prop
            )

        for regra in regras:
            if nome == "Y40-Y59":
                icd_val = regra[config.inferred_cid_prop][0]
                icd_dotted = icd_val[0:3] + "." + icd_val[3]
                if icd_dotted not in icd_to_substances:
                    print(f"Warning! ICD={icd_dotted} não tem lista de substâncias! pulando a regra")
                    line_num += 1
                    continue

            sparql_lines = rule_processor.rule_to_sparql(regra, line_num)
            result[nome].append({
                "inferred_cid": regra[config.inferred_cid_prop],
                "aba_excel": nome,
                "sparql": config.sparql_prefix + "\n" + "\n".join(sparql_lines),
            })
            line_num += 1

    return result


def build_uri_rules_json(
    workbook_data: dict[str, list[dict]],
    ontology: OntologyLoader,
    term_lists: dict[str, dict],
    config: Config,
) -> list[dict]:
    """
    Cria uma lista de dicts com as URIs já resolvidas para cada regra,
    sem gerar SPARQL.
    """
    result: list[dict] = []

    for aba_cfg in config.rule_sheets:
        nome = aba_cfg["nome"]
        for regra in workbook_data[nome]:
            result.append(_resolve_rule_uris(regra, ontology, term_lists, config))

    return result


def _resolve_rule_uris(
    rule: dict[str, list[str]],
    ontology: OntologyLoader,
    term_lists: dict[str, dict],
    config: Config,
) -> dict:
    """Converte os valores de uma regra em URIs / termos resolvidos."""
    tmp: dict = {}

    for field_txt, vals in rule.items():
        if not vals or field_txt in ("_EXCLUSAO_LISTAS_URIS", "_PADROES_IRMAS_X89"):
            continue

        if ";" in field_txt:
            fields = field_txt.split(";")
        else:
            fields = [field_txt]

        if field_txt == "LOC_EXPO;LOC_EXP_DE":
            tmp["intox:LOC_EXPO"] = []
            tmp["intox:LOC_EXP_DE"] = []
            for v in vals:
                v = v.strip()
                if re.match(r"^[0-9]+", v):
                    tmp["intox:LOC_EXPO"].append(
                        str(ontology.get_uri_for_option("LOC_EXPO", v))
                    )
                elif "LISTA" in v:
                    uri = _list_uri_from_name(v)
                    _, lista = _consolidate_lists([uri], term_lists)
                    tmp["intox:LOC_EXP_DE"] += list(set(lista))
                else:
                    tmp["intox:LOC_EXP_DE"].append(v)
        else:
            for campo in fields:
                campo_uri = f"intox:{campo}"
                tmp[campo_uri] = []
                for v in vals:
                    if ", se" in v:
                        m = re.findall(r"^([0-9]+).*, se CLASSI_FIN == ([0-9]+)$", v)
                        cf = ontology.get_uri_for_option("CLASSI_FIN", m[0][1])
                        opt = ontology.get_uri_for_option(campo, v)
                        tmp[campo_uri].append(
                            f"intox.CLASSI_FIN == {cf}  AND {opt}"
                        )
                    elif re.match(r"^[0-9]+", v):
                        tmp[campo_uri].append(
                            str(ontology.get_uri_for_option(campo, v))
                        )
                    elif "LISTA" in v:
                        uri = _list_uri_from_name(v)
                        _, lista = _consolidate_lists([uri], term_lists)
                        tmp[campo_uri] += list(set(lista))
                    else:
                        tmp[campo_uri].append(v)

    return tmp


# ===========================================================================
# PONTO DE ENTRADA
# ===========================================================================

def main(config: Config | None = None) -> None:
    if config is None:
        config = Config()

    print("=== Carregando ontologia ===")
    ontology = OntologyLoader(config)

    print("=== Carregando planilha ===")
    reader = ExcelReader(config)
    term_lists = reader.read_term_lists()

    print("=== Carregando substâncias ===")
    icd_to_substances = load_icd_to_substances(config.substances_parquet)

    print("=== Lendo regras das abas ===")
    workbook_data: dict[str, list[dict]] = {}
    for aba_cfg in config.rule_sheets:
        workbook_data[aba_cfg["nome"]] = reader.read_rules(
            aba_cfg["nome"],
            aba_cfg["linha_inicial"],
            aba_cfg["linha_final"],
            config.inferred_cid_prop,
        )

    print("=== Gerando SPARQL ===")
    rule_proc = RuleProcessor(ontology, term_lists, icd_to_substances, config)
    sparql_rules = build_sparql_rules_json(
        workbook_data, rule_proc, icd_to_substances, config
    )

    print("=== Gerando JSON de URIs ===")
    uri_rules = build_uri_rules_json(workbook_data, ontology, term_lists, config)

    print("=== Salvando saídas ===")
    with open(config.output_sparql_json, "w", encoding="utf-8") as f:
        json.dump(sparql_rules, f, ensure_ascii=False)

    with open(config.output_uri_json, "w", encoding="utf-8") as f:
        json.dump(uri_rules, f, ensure_ascii=False)

    with open(config.output_listas_json, "w", encoding="utf-8") as f:
        json.dump(term_lists, f, ensure_ascii=False)

    print("Concluído.")
    for nome, regras in sparql_rules.items():
        print(f"  {nome}: {len(regras)} regras geradas")


if __name__ == "__main__":
    main()
