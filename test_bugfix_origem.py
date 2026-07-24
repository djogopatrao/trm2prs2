#!/usr/bin/env python3
"""
test_bugfix_origem.py
======================
Testes dedicados à correção P0 de BUG_FIX_PLAN.md: BOUND() sozinho não
distingue "campo ausente" de "campo presente com literal vazio" na lógica
de "primeiro campo de agente preenchido".

Cobre os 4 cenários de BUG_INVESTIGATION_REPORT.md (seção 3):
  A. campo ausente, campo posterior preenchido      -> deve escolher o posterior
  B. 1º campo presente-mas-vazio, posterior preenchido -> deve escolher o posterior
  C. nenhum campo presente                           -> CAMPO/VALOR_ORIGEM unbound
  D. todos os campos presentes-mas-vazios            -> CAMPO/VALOR_ORIGEM unbound

Testado contra as 3 funções que compartilhavam o defeito:
  - SparqlClauseBuilder._origem_agente_lines
  - SparqlClauseBuilder.regra_complexa_agente_x70 (Ramo A)
  - SparqlClauseBuilder.regra_agente_tox_qualquer_conteudo

Não reimplementa a lógica de correção — executa o SPARQL real gerado pelo
código de produção contra um pyoxigraph.Store sintético.

Uso:
    python3 test_bugfix_origem.py
"""

from __future__ import annotations

import sys

import pyoxigraph as ox

from excel_to_sparql import SparqlClauseBuilder, SparqlVarCounter

NS = "https://ontologia.trauma.einstein.br/intox#"
PREFIX = f"PREFIX intox: <{NS}>"
REGISTRO = ox.NamedNode("urn:test:registro1")


def _iri(local: str) -> ox.NamedNode:
    return ox.NamedNode(NS + local)


def _store(quads: list[tuple[str, str]]) -> ox.Store:
    store = ox.Store()
    for prop, val in quads:
        if val.startswith("intox:"):
            obj = _iri(val.split(":", 1)[1])
        else:
            obj = ox.Literal(val)
        store.add(ox.Quad(REGISTRO, _iri(prop), obj))
    return store


def _select_origem(store: ox.Store, where_lines: list[str], v_campo: str, v_val: str):
    query = (
        f"{PREFIX}\nSELECT ?{v_campo} ?{v_val} WHERE {{\n"
        f"  VALUES ?registro {{ <{REGISTRO.value}> }}\n"
        + "\n".join(where_lines) + "\n}"
    )
    rows = list(store.query(query))
    assert len(rows) == 1, f"esperava exatamente 1 solução, obteve {len(rows)}"
    row = rows[0]
    campo = row[v_campo]
    valor = row[v_val]
    return (campo.value if campo is not None else None), (valor.value if valor is not None else None)


CASOS: list[tuple[str, str, list[tuple[str, str]], str | None, str | None]] = [
    # (id, descricao, quads, campo_esperado (None=unbound), valor_esperado (None=unbound))
    ("A", "campo ausente, posterior preenchido", [("AGENTE_2", "CLONAZEPAM")],
     NS + "AGENTE_2", "CLONAZEPAM"),
    ("B", "1o campo presente-vazio, posterior preenchido",
     [("AGENTE_1", ""), ("AGENTE_2", "CLONAZEPAM")], NS + "AGENTE_2", "CLONAZEPAM"),
    ("C", "nenhum campo presente", [], None, None),
    ("D", "todos os campos presentes-vazios",
     [(c, "") for c in ("AGENTE_1", "AGENTE_2", "AGENTE_3", "P_ATIVO_1", "P_ATIVO_2", "P_ATIVO_3")],
     None, None),
]


def test_origem_agente_lines() -> list[tuple[str, bool, str]]:
    resultados = []
    for cid, desc, quads, campo_esp, valor_esp in CASOS:
        lines, meta = SparqlClauseBuilder._origem_agente_lines(f"X{cid}", f"t{cid}")
        store = _store(quads)
        campo, valor = _select_origem(store, lines, meta["campo"], meta["valor"])
        ok = (campo == campo_esp) and (valor == valor_esp)
        resultados.append((
            f"_origem_agente_lines [{cid}] {desc}", ok,
            f"esperado=({campo_esp!r},{valor_esp!r}) obtido=({campo!r},{valor!r})",
        ))
    return resultados


def test_x70_ramo_a() -> list[tuple[str, bool, str]]:
    resultados = []
    for cid, desc, quads, campo_esp, valor_esp in CASOS:
        counter = SparqlVarCounter()
        builder = SparqlClauseBuilder(counter, term_lists={"intox:lista_23": {"rdf:label": "LISTA 23", "termos": []},
                                                            "intox:lista_24": {"rdf:label": "LISTA 24", "termos": []}})
        lines = builder.regra_complexa_agente_x70("dummy", "dummy", inferred_value=f"X{cid}")
        # Ramo A dispara com AGENTE_TOX em {02,03,04,05}; usamos 02.
        store = _store(quads + [("AGENTE_TOX", "intox:categoria_AGENTE_TOX_02")])
        campo, valor = _select_origem(store, lines, builder.origem_x70["campo"], builder.origem_x70["valor"])
        ok = (campo == campo_esp) and (valor == valor_esp)
        resultados.append((
            f"regra_complexa_agente_x70 Ramo A [{cid}] {desc}", ok,
            f"esperado=({campo_esp!r},{valor_esp!r}) obtido=({campo!r},{valor!r})",
        ))
    return resultados


def test_agente_tox_qualquer_conteudo() -> list[tuple[str, bool, str]]:
    resultados = []
    for cid, desc, quads, campo_esp, valor_esp in CASOS:
        counter = SparqlVarCounter()
        builder = SparqlClauseBuilder(counter, term_lists={})
        lines = builder.regra_agente_tox_qualquer_conteudo(
            campos_agente=SparqlClauseBuilder._CAMPOS_AGENTE_PADRAO,
            categorias=["02", "03"],
            inferred_value=f"X{cid}",
        )
        store = _store(quads + [("AGENTE_TOX", "intox:categoria_AGENTE_TOX_02")])
        campo, valor = _select_origem(store, lines, builder.origem_x70["campo"], builder.origem_x70["valor"])
        ok = (campo == campo_esp) and (valor == valor_esp)
        resultados.append((
            f"regra_agente_tox_qualquer_conteudo [{cid}] {desc}", ok,
            f"esperado=({campo_esp!r},{valor_esp!r}) obtido=({campo!r},{valor!r})",
        ))
    return resultados


def test_filtro_not_exists_agente_origem_x89() -> list[tuple[str, bool, str]]:
    """
    Cobre o segundo consumidor de _origem_agente_lines: filtro_not_exists_agente
    (rota X89), quando chamado com inferred_value definido (popula
    builder.origem_x89). not_empty=False e padroes_irmas com listas vazias
    para que o FILTER NOT EXISTS nunca exclua o registro, isolando o teste
    na parte de origem.
    """
    resultados = []
    campos = SparqlClauseBuilder._CAMPOS_AGENTE_PADRAO
    for cid, desc, quads, campo_esp, valor_esp in CASOS:
        counter = SparqlVarCounter()
        # Nota: term_lists NÃO pode usar "termos": [] aqui — in_clause([])
        # gera 'IN ( "")' (um conjunto com a string vazia), não um conjunto
        # vazio, o que faria o valor "" (campo presente-mas-vazio) bater por
        # acidente. Usamos um termo placeholder que nunca aparece nos dados.
        term_lists = {f"intox:lista_{n}": {"rdf:label": f"LISTA {n}", "termos": ["zzz_termo_inexistente"]}
                      for n in (21, 22, 23, 24, 28, 29)}
        builder = SparqlClauseBuilder(counter, term_lists)
        lines = builder.filtro_not_exists_agente(
            ";".join(campos), not_empty=False, padroes_irmas=None,
            inferred_value=f"X{cid}", campos_agente=campos,
        )
        # Em produção, ?AGENTE_TOX_value (referenciado dentro do FILTER NOT
        # EXISTS) já vem vinculado por um campo categórico processado antes
        # na mesma regra — reproduzimos isso aqui com uma categoria neutra
        # (99), que não participa de nenhuma das disjunções do fallback.
        lines = ["\t?registro intox:AGENTE_TOX ?AGENTE_TOX_value."] + lines
        store = _store(quads + [("AGENTE_TOX", "intox:categoria_AGENTE_TOX_99")])
        campo, valor = _select_origem(store, lines, builder.origem_x89["campo"], builder.origem_x89["valor"])
        ok = (campo == campo_esp) and (valor == valor_esp)
        resultados.append((
            f"filtro_not_exists_agente (origem_x89) [{cid}] {desc}", ok,
            f"esperado=({campo_esp!r},{valor_esp!r}) obtido=({campo!r},{valor!r})",
        ))
    return resultados


def main() -> int:
    todos = (
        test_origem_agente_lines()
        + test_x70_ramo_a()
        + test_agente_tox_qualquer_conteudo()
        + test_filtro_not_exists_agente_origem_x89()
    )
    falhas = 0
    for nome, ok, detalhe in todos:
        marker = "✓" if ok else "✗"
        print(f"[{marker}] {nome:<65} {detalhe}")
        if not ok:
            falhas += 1

    print("\n" + "-" * 60)
    print(f"Total: {len(todos)}  PASS: {len(todos) - falhas}  FAIL: {falhas}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
