#!/usr/bin/env python3
"""
test_p2_whitespace_trim.py
===========================
Testes da correção P2 de BUG_FIX_PLAN.md: normalização de espaços em
branco no início/fim antes de comparar termos (achado secundário 5.1 de
BUG_INVESTIGATION_REPORT.md — ex.: ID_TRAUMA_VITIMA=85, P_ATIVO_1=" BEBIDA
ALCOOLICA" com espaço à esquerda não casava com o termo da lista).

SPARQL 1.1 não tem TRIM() nativo — a correção usa
LCASE(REPLACE(STR(?v), "^\\s+|\\s+$", "")), aplicado nos mesmos 8 pontos
das Fases 1/2, e .strip() no lado Python ao preparar as listas de termos.

Cobre, para cada função corrigida:
  - termo com espaço à esquerda/direita no valor comparado -> deve casar
  - termo com espaço duplo NO MEIO -> NÃO deve casar (controle negativo:
    o trim só remove espaços nas pontas, não normaliza espaços internos)
  - combinação trim + fuzzy (garante que as duas correções coexistem)

Não reimplementa a lógica de matching — executa o SPARQL real gerado pelo
código de produção contra um pyoxigraph.Store sintético.

Uso:
    python3 test_p2_whitespace_trim.py
"""

from __future__ import annotations

import pyoxigraph as ox

from excel_to_sparql import SparqlClauseBuilder, SparqlVarCounter

NS = "https://ontologia.trauma.einstein.br/intox#"
PREFIX = f"PREFIX intox: <{NS}>"
REGISTRO = ox.NamedNode("urn:test:registro1")


def _iri(local: str) -> ox.NamedNode:
    return ox.NamedNode(NS + local)


def _make_list(term_lists: dict, index: str, termos: list[str]) -> str:
    uri = f"intox:lista_{index}"
    term_lists[uri] = {"rdf:label": f"LISTA {index}", "termos": list(termos)}
    return uri


def _ask(where_lines: list[str], prop: str, valor: str) -> bool:
    store = ox.Store()
    store.add(ox.Quad(REGISTRO, _iri(prop), ox.Literal(valor)))
    query = (
        f"{PREFIX}\nASK {{\n  VALUES ?registro {{ <{REGISTRO.value}> }}\n"
        + "\n".join(where_lines) + "\n}"
    )
    return bool(store.query(query))


CASOS_TRIM = [
    ("espaço à esquerda", " BEBIDA ALCOOLICA", True),
    ("espaço à direita", "BEBIDA ALCOOLICA ", True),
    ("espaços dos dois lados", "  BEBIDA ALCOOLICA  ", True),
    ("sem espaço (controle positivo)", "BEBIDA ALCOOLICA", True),
    ("espaço duplo NO MEIO (controle negativo)", "BEBIDA  ALCOOLICA", False),
]


def test_filter_exists_list_in_value() -> list[tuple[str, bool, str]]:
    resultados = []
    for desc, valor, esperado in CASOS_TRIM:
        term_lists: dict = {}
        uri = _make_list(term_lists, "950", ["BEBIDA ALCOOLICA"])
        builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists)
        lines = builder.filter_exists_list_in_value(["AGENTE_1"], [uri])
        obtido = _ask(lines, "AGENTE_1", valor)
        ok = obtido == esperado
        resultados.append((f"filter_exists_list_in_value [{desc}] {valor!r}", ok,
                            f"esperado={esperado} obtido={obtido}"))
    return resultados


def test_filter_list_agente_origem() -> list[tuple[str, bool, str]]:
    resultados = []
    for desc, valor, esperado in CASOS_TRIM:
        term_lists: dict = {}
        uri = _make_list(term_lists, "951", ["BEBIDA ALCOOLICA"])
        builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists)
        lines = builder.filter_list_agente_origem(["AGENTE_1"], [uri])
        obtido = _ask(lines, "AGENTE_1", valor)
        ok = obtido == esperado
        resultados.append((f"filter_list_agente_origem [{desc}] {valor!r}", ok,
                            f"esperado={esperado} obtido={obtido}"))
    return resultados


def test_filter_list_inline() -> list[tuple[str, bool, str]]:
    resultados = []
    for desc, valor, esperado in CASOS_TRIM:
        term_lists: dict = {}
        uri = _make_list(term_lists, "952", ["BEBIDA ALCOOLICA"])
        builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists)
        lines = builder.filter_list_inline(["LOC_EXP_DE"], [uri])
        obtido = _ask(lines, "LOC_EXP_DE", valor)
        ok = obtido == esperado
        resultados.append((f"filter_list_inline [{desc}] {valor!r}", ok,
                            f"esperado={esperado} obtido={obtido}"))
    return resultados


def test_filter_not_list_exclusao() -> list[tuple[str, bool, str]]:
    """Filtro de exclusão: 'esperado' aqui é se o registro SERIA excluído
    (ou seja, membership=True). Convertemos para o booleano do ASK."""
    resultados = []
    for desc, valor, membership_esperada in CASOS_TRIM:
        term_lists: dict = {}
        uri = _make_list(term_lists, "953", ["BEBIDA ALCOOLICA"])
        builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists)
        lines = builder.filter_not_list(["LOC_EXP_DE"], [uri])
        ask_result = _ask(lines, "LOC_EXP_DE", valor)
        # FILTER NOT EXISTS: ask=True significa "não achou" (membership=False).
        membership_obtida = not ask_result
        ok = membership_obtida == membership_esperada
        resultados.append((f"filter_not_list [{desc}] {valor!r}", ok,
                            f"esperado={membership_esperada} obtido={membership_obtida}"))
    return resultados


def test_fuzzy_com_trim() -> list[tuple[str, bool, str]]:
    """Combinação trim + fuzzy: valor com espaço extra E 1 erro de digitação."""
    resultados = []
    casos = [
        ("espaço + substituição", " BEBIDA ALCOOLECA", True),
        ("espaço + 2 erros (controle negativo)", " BEBIDA ALCOOLECX", False),
    ]
    for desc, valor, esperado in casos:
        term_lists: dict = {}
        uri = _make_list(term_lists, "954", ["BEBIDA ALCOOLICA"])
        builder = SparqlClauseBuilder(SparqlVarCounter(), term_lists)
        lines = builder.filter_exists_list_in_value(["AGENTE_1"], [uri], fuzzy=True)
        obtido = _ask(lines, "AGENTE_1", valor)
        ok = obtido == esperado
        resultados.append((f"filter_exists_list_in_value fuzzy+trim [{desc}] {valor!r}", ok,
                            f"esperado={esperado} obtido={obtido}"))
    return resultados


def main() -> int:
    todos = (
        test_filter_exists_list_in_value()
        + test_filter_list_agente_origem()
        + test_filter_list_inline()
        + test_filter_not_list_exclusao()
        + test_fuzzy_com_trim()
    )
    falhas = 0
    for nome, ok, detalhe in todos:
        marker = "✓" if ok else "✗"
        print(f"[{marker}] {nome:<70} {detalhe}")
        if not ok:
            falhas += 1

    print("\n" + "-" * 60)
    print(f"Total: {len(todos)}  PASS: {len(todos) - falhas}  FAIL: {falhas}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
