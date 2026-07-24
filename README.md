# trm2prs2 — Geração de regras SPARQL de inferência de CID-10

Converte regras de inferência de CID-10 definidas em planilha Excel para
queries SPARQL `CONSTRUCT`, usando uma ontologia OWL como referência de URIs.
As queries geradas são pensadas para execução com **pyoxigraph**.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `excel_to_sparql.py` | Gerador principal: lê a planilha e a ontologia e produz `sparql_rules.json`, `rules_uri.json` e `listas_de_termos.json`. |
| `MODIFICATION_PLAN.md` | Plano de modificação para tornar o matching de termos **case-insensitive** (obrigatório) e **fuzzy** (até 1 erro de digitação — opcional). Descreve, função a função, o que muda no gerador e os riscos de regressão/performance. |
| `FUZZY_IMPLEMENTATION_PLAN.md` | Desenho detalhado da Fase 2 (algoritmo de geração do padrão `REGEX`, escopo por função, escaping regex→SPARQL). |
| `FUZZY_IMPLEMENTATION_REPORT.md` | Relatório da primeira rodada de implementação/testes da Fase 2 (histórico — o defeito de dado do `FUZZY-12` relatado ali já foi corrigido em `TEST_CASES.json`). |
| `TEST_CASES.json` | 34 casos de teste (`LEGACY`, `CASE`, `FUZZY`) para validar o matching de termos, cobrindo os 8 pontos do código identificados no plano. |
| `run_tests.py` | Executa `TEST_CASES.json` contra a implementação real, rodando as cláusulas SPARQL geradas em um `pyoxigraph.Store` isolado por caso, **nos dois algoritmos** (fuzzy e não-fuzzy) para todo caso com adaptador — não reimplementa a lógica de matching. |
| `BUG_INVESTIGATION_REPORT.md` | Investigação de um bug relatado em dados reais: `CAMPO_ORIGEM`/`VALOR_ORIGEM` às vezes eram fabricados a partir de um campo vazio. Documento histórico (estado pré-correção) — a correção já foi aplicada, ver os dois arquivos abaixo. |
| `BUG_FIX_PLAN.md` | Plano de correção do bug acima: 3 regiões de código com o mesmo defeito, risco de regressão e priorização (P0 já implementado; P1-P3 pendentes). |
| `test_bugfix_origem.py` | Testes dedicados à correção do bug de `CAMPO_ORIGEM`/`VALOR_ORIGEM` — 16 casos cobrindo os 4 consumidores da lógica corrigida (campo ausente vs. presente-mas-vazio, com e sem campo posterior preenchido). |
| `requirements.txt` | Dependências para rodar o gerador e os testes. |

## Status da implementação

- ✅ **Fase 1 — case-insensitive (obrigatório)**: aplicada. Todas as comparações
  termo-lista usam `LCASE(STR(...))`, e o bug pré-existente em `_resolve_terms`
  (que deixava de normalizar para minúsculas no caso de lista única) foi
  corrigido.
- ✅ **Fase 2 — fuzzy (opcional, até 1 erro: substituição/deleção/duplicação)**:
  implementada nos caminhos de inclusão (`filter_exists_list_in_value`,
  `filter_list_agente_origem`, `filter_list_inline`, `regra_volume_iii_cid`),
  opt-in por campo via `Config.fuzzy_fields` (vazio por padrão = desligado).
  Caminhos de exclusão (`filter_not_list`, `filtro_not_exists_agente`,
  `_disjuncoes_padroes_irmas`) e o Ramo B do X70 **não** recebem fuzzy nesta
  fase — ver `FUZZY_IMPLEMENTATION_PLAN.md` para o desenho e
  `FUZZY_IMPLEMENTATION_REPORT.md` para os achados da implementação
  (incluindo um caminho ainda não coberto por teste, `filter_list_agente_origem`,
  e uma ambiguidade de escopo identificada em `regra_local_exposicao`).
- ✅ **Correção de bug — origem fabricada a partir de campo vazio**: a lógica
  de "primeiro campo de agente preenchido" (`_origem_agente_lines`,
  `regra_complexa_agente_x70` Ramo A, `regra_agente_tox_qualquer_conteudo`)
  usava só `BOUND()`, que não distingue campo ausente de campo presente com
  valor vazio — corrigido acrescentando `STRLEN(STR(...))>0` às 3
  ocorrências. Ver `BUG_INVESTIGATION_REPORT.md` (diagnóstico),
  `BUG_FIX_PLAN.md` (plano, P0 concluído) e `test_bugfix_origem.py`
  (16/16 casos, sem regressão na suíte principal).

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

Saída esperada atualmente: **32 PASS, 0 FAIL, 2 SKIP** — os `SKIP` são
`LEGACY-10` (controle categórico, sem adaptador — não usa string literal) e
`FUZZY-10` (colisão entre termos distintos a 1 edição, marcado desde a
criação de `TEST_CASES.json` como ambíguo/não-automatizável, exige revisão
humana).

Todo caso com adaptador roda **nos dois algoritmos** (`fuzzy=False` e
`fuzzy=True`), independente da sua categoria original — o PASS/FAIL continua
avaliado apenas contra o algoritmo que o `modo_avaliado` do caso indica
(LEGACY/CASE contra não-fuzzy, FUZZY contra fuzzy); o resultado do outro
algoritmo aparece no detalhe de cada linha só como informação (ex.: um caso
`FUZZY` roda também sem fuzzy, mostrando que o typo não seria encontrado sem
a Fase 2 — o que é o comportamento esperado, não uma falha).

## Medições de tempo de execução das queries

`run_tests.py` cronometra **apenas** a chamada `store.query(query)` de cada
caso — a montagem do `Store`, das listas de termos e da string da query fica
fora da medição. Use `python3 run_tests.py --tabela-markdown` para gerar a
tabela abaixo automaticamente.

A partir da implementação da Fase 2, **todo caso com adaptador roda nos dois
algoritmos** (independente de sua categoria original), então as duas colunas
ficam preenchidas para os 32 casos executáveis — só `LEGACY-10` (controle
categórico, sem adaptador, não executa nenhum dos dois) fica "—" em ambas.

Para os caminhos de exclusão e o Ramo B do X70 (`filter_not_list`,
`filtro_not_exists_agente`, `_disjuncoes_padroes_irmas`,
`regra_complexa_agente_x70`), fuzzy é ignorado por design — as duas colunas
mostram tempos parecidos (mesma query nos dois casos), o que é o resultado
esperado, não um erro.

> Nota: são medições de uma única execução, em milissegundos, num `Store`
> pyoxigraph em memória minúsculo (uma tripla por caso) — servem como
> referência relativa entre os casos, não como benchmark de produção. A
> primeira query de cada algoritmo executada no processo tende a ter
> overhead de "aquecimento" (carregamento/JIT interno do pyoxigraph): no
> exemplo abaixo isso aparece de forma bem visível em `LEGACY-01` (primeira
> query não-fuzzy do processo) e principalmente na primeira query fuzzy —
> `REGEX` parece custar ~27× mais que o não-fuzzy ali, um valor bem acima do
> overhead típico visto nas linhas seguintes (tipicamente ~3×–10×). Não
> interprete a primeira linha de cada bloco como representativa por si só.

| numero do teste | tempo (não fuzzy) | tempo (fuzzy) |
|---|---|---|
| LEGACY-01 | 0.672 ms | 18.444 ms |
| LEGACY-02 | 0.205 ms | 3.803 ms |
| LEGACY-03 | 0.112 ms | 2.260 ms |
| LEGACY-04 | 0.206 ms | 0.108 ms |
| LEGACY-05 | 0.150 ms | 0.108 ms |
| LEGACY-06 | 0.118 ms | 0.959 ms |
| LEGACY-07 | 0.541 ms | 0.461 ms |
| LEGACY-08 | 0.314 ms | 0.256 ms |
| LEGACY-09 | 0.147 ms | 0.145 ms |
| LEGACY-10 | — | — |
| CASE-01 | 0.092 ms | 0.996 ms |
| CASE-02 | 0.100 ms | 1.024 ms |
| CASE-03 | 0.097 ms | 1.002 ms |
| CASE-04 | 0.108 ms | 0.128 ms |
| CASE-05 | 0.089 ms | 0.625 ms |
| CASE-06 | 0.090 ms | 0.669 ms |
| CASE-07 | 0.322 ms | 0.324 ms |
| CASE-08 | 0.234 ms | 0.187 ms |
| CASE-09 | 0.240 ms | 0.193 ms |
| CASE-10 | 0.099 ms | 0.789 ms |
| FUZZY-01 | 0.089 ms | 0.604 ms |
| FUZZY-02 | 0.091 ms | 0.543 ms |
| FUZZY-03 | 0.086 ms | 0.418 ms |
| FUZZY-04 | 0.130 ms | 0.810 ms |
| FUZZY-05 | 0.083 ms | 1.092 ms |
| FUZZY-06 | 0.091 ms | 0.609 ms |
| FUZZY-07 | 0.121 ms | 0.676 ms |
| FUZZY-08 | 0.120 ms | 0.155 ms |
| FUZZY-09 | 0.082 ms | 0.593 ms |
| FUZZY-10 | 0.088 ms | 0.536 ms |
| FUZZY-11 | 0.127 ms | 2.895 ms |
| FUZZY-12 | 0.098 ms | 2.954 ms |
| FUZZY-13 | 0.115 ms | 0.101 ms |
| FUZZY-14 | 0.107 ms | 0.468 ms |

Os casos `LEGACY-04/05/07/08/09`, `FUZZY-13` (caminhos de exclusão/X70 Ramo
B) mostram os dois tempos próximos, confirmando que fuzzy não altera nada
ali. `FUZZY-11`/`FUZZY-12` (termo com parênteses, o mais longo do conjunto)
seguem sendo os mais caros em modo fuzzy, como já observado na Fase 2.
