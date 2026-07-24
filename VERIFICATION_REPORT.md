# Verificação das Correções contra os Dados Reais (IEXOBR19_PREPARADO_100)

> Nota sobre escopo: `excel_to_sparql.py` **gera** queries a partir da
> planilha de regras + ontologia OWL — ele não processa o CSV de instâncias
> (`IEXOBR19_PREPARADO_100.csv`) diretamente, e a planilha/ontologia/parquet
> reais não estão disponíveis neste repositório (só os dois CSVs da
> investigação). Não é possível, portanto, rodar o pipeline completo
> (`python3 excel_to_sparql.py` → executar as ~500 queries geradas) e
> comparar `sparql_rules.json` de ponta a ponta.
>
> O que **é** possível e foi feito aqui: executar as funções corrigidas de
> `SparqlClauseBuilder` diretamente contra os dados reais de cada registro
> do CSV de entrada (o mesmo padrão de `test_bugfix_origem.py`/
> `test_p2_whitespace_trim.py`, mas com os valores reais em vez de
> sintéticos), e comparar o resultado contra o que o `_inferido.csv`
> mostrava antes da correção.

## 1. Achado principal (P0) — os 7 registros confirmados no relatório

Para cada um dos 7 `_ORIGINAL_ID` que `BUG_INVESTIGATION_REPORT.md` apontou
como afetados (todos os campos de agente vazios, mas `CAMPO_ORIGEM`/
`VALOR_ORIGEM` eram fabricados a partir de `AGENTE_1`), reconstruí o grafo
do registro (campos vazios como literal `""`, replicando a causa raiz) e
executei `_origem_agente_lines` corrigido:

| ID | Antes (`_inferido.csv`) | Agora (código corrigido) | Resultado |
|---|---|---|---|
| 4 | `CAMPO_ORIGEM='intox:AGENTE_1'` `VALOR_ORIGEM=''` | `None` / `None` (não materializa) | ✅ |
| 15 | idem | `None` / `None` | ✅ |
| 74 | idem | `None` / `None` | ✅ |
| 75 | idem | `None` / `None` | ✅ |
| 79 | idem | `None` / `None` | ✅ |
| 87 | idem | `None` / `None` | ✅ |
| 89 | idem | `None` / `None` | ✅ |

**Os 7/7 casos confirmam a correção**: o nó de inferência deixa de expor
`CAMPO_ORIGEM`/`VALOR_ORIGEM` fabricados quando nenhum campo de agente tem
conteúdo real — exatamente o comportamento documentado no código-fonte.

## 2. Regressão (P0) — registros com origem legítima

Reexecutei `_origem_agente_lines` corrigido para **todos os 57 registros**
do `_inferido.csv` cujo `CAMPO_ORIGEM` era `intox:AGENTE_1` com um
`VALOR_ORIGEM` não-vazio (ou seja, os casos onde a origem já estava certa
antes da correção), usando o conteúdo real de cada registro.

**Resultado: 57/57 continuam corretos** — mesmo `CAMPO_ORIGEM=AGENTE_1` e
mesmo `VALOR_ORIGEM`, sem nenhuma regressão.

## 3. Achado secundário (P2) — espaço em branco, caso real `id=85`

`ID_TRAUMA_VITIMA=85` tem `P_ATIVO_1=' BEBIDA ALCOOLICA'` (espaço à
esquerda) no CSV de entrada — o valor exato relatado em
`BUG_INVESTIGATION_REPORT.md` seção 5.1. Como a lista de termos real (aba
`LISTAS` da planilha) não está disponível, usei uma lista sintética
contendo apenas `"bebida alcoolica"` e testei `filter_list_agente_origem`
com o valor **real** desse registro:

```
P_ATIVO_1 real: ' BEBIDA ALCOOLICA'
Resultado da query corrigida (P2): True  (antes da correção, não batia)
```

**Confirmado**: o valor real do registro 85, que falhava antes por causa do
espaço à esquerda, agora casa corretamente contra o termo da lista.

## 4. Conclusão

Os 3 pontos verificáveis com os dados disponíveis neste repositório
(achado principal, regressão, achado de espaço em branco) confirmam a
correção contra dados reais, não apenas sintéticos. A verificação completa
de ponta a ponta (rodar `excel_to_sparql.py` com a planilha/ontologia reais
e comparar o CSV de saída inteiro) continua pendente por falta desses
arquivos neste ambiente — ver `BUG_FIX_PLAN.md` seção 5.
