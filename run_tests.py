#!/usr/bin/env python3
"""
run_tests.py
============
Executor de TEST_CASES.json contra a implementação real de excel_to_sparql.py.

Para cada caso, monta um pyoxigraph.Store isolado, popula os dados mínimos
descritos no caso (lista de termos + valor de entrada) e executa a cláusula
SPARQL gerada pelo método real de SparqlClauseBuilder (nenhuma lógica de
matching é reimplementada aqui — o teste roda o código de produção).

Casos FUZZY passam fuzzy=True aos adaptadores que suportam matching fuzzy
(caminhos de inclusão); os demais adaptadores (caminhos de exclusão e o
Ramo B do X70) ignoram o flag de propósito, pois esses caminhos não
recebem fuzzy nesta fase (ver FUZZY_IMPLEMENTATION_PLAN.md). Casos
categóricos (URIs de opção da ontologia) são SKIP — não usam string
literal e estão fora do escopo do patch de case-insensitive/fuzzy.

Uso:
    python3 run_tests.py [--categoria LEGACY|CASE|FUZZY]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pyoxigraph as ox

sys.path.insert(0, str(Path(__file__).parent))
from excel_to_sparql import SparqlClauseBuilder, SparqlVarCounter  # noqa: E402

NS = "https://ontologia.trauma.einstein.br/intox#"
PREFIX = f"PREFIX intox: <{NS}>"
REGISTRO = ox.NamedNode("urn:test:registro1")


def _iri(local: str) -> ox.NamedNode:
    return ox.NamedNode(NS + local)


def _seed(store: ox.Store, prop: str, value: str) -> None:
    """Adiciona ?registro intox:<prop> <valor>. Trata valores 'intox:X' como IRI."""
    if value.startswith("intox:"):
        obj = _iri(value.split(":", 1)[1])
    else:
        obj = ox.Literal(value)
    store.add(ox.Quad(REGISTRO, _iri(prop), obj))


def _make_list(term_lists: dict, index: str, termos: list[str]) -> str:
    uri = f"intox:lista_{index}"
    term_lists[uri] = {"rdf:label": f"LISTA {index}", "termos": list(termos)}
    return uri


# ---------------------------------------------------------------------------
# Adaptadores: um por função de SparqlClauseBuilder exercitada nos testes.
# Cada adaptador popula o Store e o dicionário de listas, chama o método real
# e devolve as linhas de cláusula SPARQL que ele gera.
# ---------------------------------------------------------------------------

def _adapt_filter_exists_list_in_value(tc, store, term_lists, icd_map, fuzzy):
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    prop_vars = tc["campo_regra"].split(";")
    uri = _make_list(term_lists, "900", tc["lista_termos"])
    _seed(store, prop_vars[0], tc["valor_entrada"])
    return builder.filter_exists_list_in_value(prop_vars, [uri], fuzzy=fuzzy)


def _adapt_filter_list_agente_origem(tc, store, term_lists, icd_map, fuzzy):
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    prop_vars = tc["campo_regra"].split(";")
    uri = _make_list(term_lists, "901", tc["lista_termos"])
    _seed(store, prop_vars[0], tc["valor_entrada"])
    return builder.filter_list_agente_origem(prop_vars, [uri], fuzzy=fuzzy)


def _adapt_filter_not_list(tc, store, term_lists, icd_map, fuzzy):
    # filter_not_list não tem parâmetro fuzzy (fora de escopo — filtro de
    # exclusão). `fuzzy` é ignorado de propósito: mesmo quando um caso FUZZY
    # exercita este caminho (ex.: FUZZY-13), o teste deve continuar rodando
    # em modo exato, validando a fronteira de escopo da Fase 2.
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    prop_vars = tc["campo_regra"].split(";")
    uri = _make_list(term_lists, "902", tc["lista_termos"])
    _seed(store, prop_vars[0], tc["valor_entrada"])
    return builder.filter_not_list(prop_vars, [uri])


def _adapt_filter_list_inline(tc, store, term_lists, icd_map, fuzzy):
    # A produção sempre chama filter_list_inline(["LOC_EXP_DE"], ...), mesmo
    # quando campo_regra do teste é o par combinado "LOC_EXPO;LOC_EXP_DE".
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    uri = _make_list(term_lists, "903", tc["lista_termos"])
    _seed(store, "LOC_EXP_DE", tc["valor_entrada"])
    return builder.filter_list_inline(["LOC_EXP_DE"], [uri], fuzzy=fuzzy)


def _adapt_x70_ramo_b(tc, store, term_lists, icd_map, fuzzy):
    # regra_complexa_agente_x70 não tem parâmetro fuzzy (fora de escopo nesta
    # fase) — `fuzzy` é ignorado de propósito.
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    campos = tc["campo_regra"].split(";")
    term_lists["intox:lista_23"] = {"rdf:label": "LISTA 23", "termos": list(tc["lista_termos"])}
    term_lists["intox:lista_24"] = {"rdf:label": "LISTA 24", "termos": []}
    # AGENTE_TOX em {07,09,14} isola o Ramo B (Ramo A dispara para {02..05}).
    _seed(store, "AGENTE_TOX", "intox:categoria_AGENTE_TOX_07")
    _seed(store, campos[0], tc["valor_entrada"])
    return builder.regra_complexa_agente_x70(
        "dummy", "dummy", inferred_value="X700", campos_agente=campos
    )


def _adapt_x89_fallback(tc, store, term_lists, icd_map, fuzzy):
    # filtro_not_exists_agente não tem parâmetro fuzzy (fora de escopo —
    # filtro de exclusão) — `fuzzy` é ignorado de propósito.
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    campos = tc["campo_regra"].split(";")
    term_lists["intox:lista_21"] = {"rdf:label": "LISTA 21", "termos": list(tc["lista_termos"])}
    for idx in ("22", "28", "29", "23", "24"):
        term_lists.setdefault(f"intox:lista_{idx}", {"rdf:label": f"LISTA {idx}", "termos": []})
    # AGENTE_TOX categoria 99 não participa de nenhuma disjunção do fallback,
    # isolando o teste na disjunção de lista (cond1).
    _seed(store, "AGENTE_TOX", "intox:categoria_AGENTE_TOX_99")
    _seed(store, campos[0], tc["valor_entrada"])
    return builder.filtro_not_exists_agente(
        ";".join(campos), not_empty=True, padroes_irmas=None,
        inferred_value=None, campos_agente=campos,
    )


def _adapt_disjuncoes_padroes_irmas(tc, store, term_lists, icd_map, fuzzy):
    # _disjuncoes_padroes_irmas não tem parâmetro fuzzy (fora de escopo —
    # filtro de exclusão) — `fuzzy` é ignorado de propósito.
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    campos = tc["campo_regra"].split(";")
    term_lists["intox:lista_905"] = {"rdf:label": "LISTA 905", "termos": list(tc["lista_termos"])}
    padroes = [{"tipo": "lista", "listas": [905]}]
    _seed(store, campos[0], tc["valor_entrada"])
    return builder.filtro_not_exists_agente(
        ";".join(campos), not_empty=True, padroes_irmas=padroes,
        inferred_value=None, campos_agente=campos,
    )


def _adapt_volume_iii(tc, store, term_lists, icd_map, fuzzy):
    icd_map["Y45.0"] = list(tc["lista_termos"])
    builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists, icd_map)
    campos = tc["campo_regra"].split(";")
    _seed(store, campos[0], tc["valor_entrada"])
    return builder.regra_volume_iii_cid(";".join(campos), "Y450", fuzzy=fuzzy)


ADAPTERS = {
    "filter_exists_list_in_value": _adapt_filter_exists_list_in_value,
    "filter_list_agente_origem": _adapt_filter_list_agente_origem,
    "filter_not_list": _adapt_filter_not_list,
    "filter_list_inline": _adapt_filter_list_inline,
    "regra_complexa_agente_x70": _adapt_x70_ramo_b,
    "filtro_not_exists_agente": _adapt_x89_fallback,
    "_disjuncoes_padroes_irmas": _adapt_disjuncoes_padroes_irmas,
    "regra_volume_iii_cid": _adapt_volume_iii,
}


def _base_func_name(funcao_alvo: str) -> str:
    return funcao_alvo.split(" (")[0].split(" / ")[0].strip()


def run_case(tc: dict) -> tuple[str, str, float | None]:
    """Executa um caso e devolve (status, detalhe, tempo_query_ms).

    status: PASS|FAIL|SKIP|ERROR. tempo_query_ms é None quando nenhuma query
    chegou a ser executada (SKIP, ou erro antes de store.query()). Apenas a
    chamada store.query(query) é cronometrada — a montagem do Store, das
    listas de termos e da string da query ficam de fora da medição.
    """
    if tc.get("tipo_filtro") == "categorico":
        return "SKIP", "campo categórico (URI de opção) — fora do escopo do patch de case-insensitive", None

    expected = tc.get("resultado_esperado")
    if not isinstance(expected, bool):
        return "SKIP", f"resultado_esperado não é booleano ({expected!r}) — requer revisão manual", None

    base_func = _base_func_name(tc["funcao_alvo"])
    adapter = ADAPTERS.get(base_func)
    if adapter is None:
        return "SKIP", f"sem adaptador de teste para {tc['funcao_alvo']!r}", None

    fuzzy = tc.get("modo_avaliado") == "fuzzy"
    term_lists: dict = {}
    icd_map: dict = {}
    store = ox.Store()

    try:
        where_lines = adapter(tc, store, term_lists, icd_map, fuzzy)
        query = f"{PREFIX}\nASK {{\n  VALUES ?registro {{ <{REGISTRO.value}> }}\n" \
                + "\n".join(where_lines) + "\n}"
    except Exception as exc:  # noqa: BLE001 — erro do gerador, antes de qualquer query
        return "ERROR", f"{type(exc).__name__}: {exc}", None

    t0 = time.perf_counter()
    try:
        ask_result = bool(store.query(query))
    except Exception as exc:  # noqa: BLE001 — erro do próprio pyoxigraph ao executar
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return "ERROR", f"{type(exc).__name__}: {exc}", elapsed_ms
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Para filtros de exclusão, resultado_esperado=True significa "o termo
    # pertence à lista, logo o registro seria excluído" — o que corresponde a
    # ASK=False (a FILTER NOT EXISTS falha quando a lista casa o termo).
    invert = tc.get("tipo_filtro") == "exclusao"
    actual_membership = (not ask_result) if invert else ask_result

    if actual_membership == expected:
        return "PASS", f"esperado={expected} obtido={actual_membership}", elapsed_ms
    return "FAIL", f"esperado={expected} obtido={actual_membership}", elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--categoria", choices=["LEGACY", "CASE", "FUZZY"], default=None,
                         help="Executa apenas os casos dessa categoria.")
    parser.add_argument("--casos", default="TEST_CASES.json",
                         help="Caminho do arquivo de casos de teste.")
    parser.add_argument("--tabela-markdown", action="store_true",
                         help="Ao final, imprime a tabela de tempos em Markdown "
                              "(numero do teste | tempo (não fuzzy) | tempo (fuzzy)) "
                              "pronta para colar no README.md.")
    args = parser.parse_args()

    data = json.loads(Path(args.casos).read_text(encoding="utf-8"))
    casos = data["casos_de_teste"]
    if args.categoria:
        casos = [tc for tc in casos if tc["categoria"] == args.categoria]

    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}
    resultados = []
    for tc in casos:
        status, detalhe, tempo_ms = run_case(tc)
        tally[status] += 1
        resultados.append((tc, status, detalhe, tempo_ms))
        marker = {"PASS": "✓", "FAIL": "✗", "SKIP": "·", "ERROR": "!"}[status]
        tempo_str = f"{tempo_ms:.3f} ms" if tempo_ms is not None else "—"
        print(f"[{marker}] {tc['id']:<12} {status:<5} {tempo_str:>12}  {detalhe}")

    total = sum(tally.values())
    print("\n" + "-" * 60)
    print(
        f"Total: {total}  PASS: {tally['PASS']}  FAIL: {tally['FAIL']}  "
        f"SKIP: {tally['SKIP']}  ERROR: {tally['ERROR']}"
    )

    if args.tabela_markdown:
        print("\n| numero do teste | tempo (não fuzzy) | tempo (fuzzy) |")
        print("|---|---|---|")
        for tc, _status, _detalhe, tempo_ms in resultados:
            fuzzy = tc.get("modo_avaliado") == "fuzzy"
            tempo_str = f"{tempo_ms:.3f} ms" if tempo_ms is not None else "—"
            nao_fuzzy_col = "—" if fuzzy else tempo_str
            fuzzy_col = tempo_str if fuzzy else "—"
            print(f"| {tc['id']} | {nao_fuzzy_col} | {fuzzy_col} |")

    return 1 if (tally["FAIL"] or tally["ERROR"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
