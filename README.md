# trm2prs2 — Geração de regras SPARQL de inferência de CID-10

Converte regras de inferência de CID-10 definidas em planilha Excel para
queries SPARQL `CONSTRUCT`, usando uma ontologia OWL como referência de URIs.
As queries geradas são pensadas para execução com **pyoxigraph**.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `excel_to_sparql.py` | Gerador principal: lê a planilha e a ontologia e produz `sparql_rules.json`, `rules_uri.json` e `listas_de_termos.json`. |
| `MODIFICATION_PLAN.md` | Plano de modificação para tornar o matching de termos **case-insensitive** (obrigatório) e **fuzzy** (até 1 erro de digitação — opcional, ainda não implementado). Descreve, função a função, o que muda no gerador e os riscos de regressão/performance. |
| `TEST_CASES.json` | 34 casos de teste (`LEGACY`, `CASE`, `FUZZY`) para validar o matching de termos, cobrindo os 8 pontos do código identificados no plano. |
| `run_tests.py` | Executa `TEST_CASES.json` contra a implementação real, rodando as cláusulas SPARQL geradas em um `pyoxigraph.Store` isolado por caso (não reimplementa a lógica de matching). |
| `requirements.txt` | Dependências para rodar o gerador e os testes. |

## Status da implementação

- ✅ **Fase 1 — case-insensitive (obrigatório)**: aplicada. Todas as comparações
  termo-lista usam `LCASE(STR(...))`, e o bug pré-existente em `_resolve_terms`
  (que deixava de normalizar para minúsculas no caso de lista única) foi
  corrigido.
- ⏳ **Fase 2 — fuzzy (opcional, até 1 erro: substituição/deleção/duplicação)**:
  ainda **não implementada**. Ver seção 3.2 e 7 do `MODIFICATION_PLAN.md` para
  o desenho proposto (padrão `REGEX` gerado em Python, sem UDFs, já que
  pyoxigraph não suporta funções de extensão).

## Como rodar

```bash
pip install -r requirements.txt
```

### Gerar as queries (requer planilha Excel + ontologia OWL + parquet de substâncias — não incluídos neste repositório)

```bash
python3 excel_to_sparql.py
```

### Rodar os testes de matching

```bash
python3 run_tests.py
# ou filtrando por categoria:
python3 run_tests.py --categoria CASE
```

Saída esperada atualmente: **19 PASS, 0 FAIL, 15 SKIP** — os `SKIP` são os 14
casos `FUZZY` (Fase 2 pendente) e 1 caso de controle categórico (`LEGACY-10`,
que usa URI de opção da ontologia e não é afetado pelo patch). Quando a Fase 2
for implementada, os adaptadores de `run_tests.py` precisarão ser estendidos
para exercitar o modo fuzzy e esses casos passam a ser executados.
