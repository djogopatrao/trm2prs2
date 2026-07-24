# Verificação das Correções contra os Dados Reais (IEXOBR19_PREPARADO_100)

## 1. Verificação de ponta a ponta (`inference.py`)

Com `ontologia_intox.owl` e `sparql_rules_iexogena.json` anexados, foi
possível rodar o pipeline completo de verdade:

```
python3 inference.py intox ontologia_intox.owl sparql_rules_iexogena.json \
    IEXOBR19_PREPARADO_100.csv resultado.csv
```

O `sparql_rules_iexogena.json` anexado **já foi gerado com o código
corrigido** — confirmado inspecionando o texto da query (contém
`IF(BOUND(?_aN) && STRLEN(STR(?_aN))>0, ...)`, o padrão da correção P0, em
vez do antigo `IF(BOUND(?_aN), ...)` sem `STRLEN`). Isso permitiu comparar
diretamente:

- **Antes**: `IEXOBR19_PREPARADO_100_inferido.csv` (anexado na investigação
  original, gerado com as queries **anteriores** à correção).
- **Depois**: saída de rodar `inference.py` com o mesmo CSV de entrada e o
  `sparql_rules_iexogena.json` **já corrigido**, usando a ontologia real e
  o conjunto completo de ~500 regras (não um subconjunto sintético).

### Resultado da comparação

| Métrica | Antes | Depois |
|---|---|---|
| Total de linhas inferidas | 94 | 94 |
| Combinações únicas (`_ORIGINAL_ID`, CID) | 82 | 82 |
| Combinações removidas/adicionadas | — | **0** |
| Combinações com `CAMPO_ORIGEM`/`VALOR_ORIGEM` diferente | — | **7** |

As **7 diferenças** são exatamente os 7 casos documentados em
`BUG_INVESTIGATION_REPORT.md` (registros sem nenhum campo de agente
preenchido):

| (`_ORIGINAL_ID`, CID) | Antes | Depois |
|---|---|---|
| (4, Y149) | `CAMPO_ORIGEM='intox:AGENTE_1'`, `VALOR_ORIGEM=''` | `CAMPO_ORIGEM=''`, `VALOR_ORIGEM=''` (não materializa) |
| (15, X690) | idem | idem |
| (74, X690) | idem | idem |
| (75, X640) | idem | idem |
| (79, Y190) | idem | idem |
| (87, X440) | idem | idem |
| (89, X490) | idem | idem |

**Nenhuma outra diferença em nenhum dos outros 75 registros/82 combinações.**
Isso confirma, com o conjunto completo de regras reais e a ontologia real
(não apenas testes isolados/sintéticos), que:
1. A correção elimina exatamente os 7 casos de origem fabricada.
2. Nenhum outro registro foi afetado — nem os que tinham origem legítima
   via `AGENTE_1` (todos os outros permanecem idênticos), nem nenhuma regra
   passou a inferir (ou deixar de inferir) um CID diferente.

## 2. Achado secundário (P2) — espaço em branco, caso real `id=85`

O registro 85 (`P_ATIVO_1=' BEBIDA ALCOOLICA'`, espaço à esquerda) aparece
na saída real com uma única linha: `CAMPO_ORIGEM=intox:AGENTE_1`,
`VALOR_ORIGEM='BEBIDA ALCOOLICA'` — **sem mudança em relação ao "antes"**.
Isso é esperado e não indica falha da correção P2: a regra que gera o CID
X449 para este registro usa o caminho **universal** (primeiro campo
preenchido, `_origem_agente_lines`), não o casamento de lista via
`filter_list_agente_origem`/`filter_exists_list_in_value` — os únicos
pontos onde a normalização de espaço (P2) se aplica. Como `AGENTE_1` (sem
espaço) já é o primeiro campo preenchido, o valor de `P_ATIVO_1` (com
espaço) nunca chega a ser comparado contra uma lista nesta regra
específica, então o P2 não tem o que corrigir aqui.

Uma verificação isolada do mecanismo em si (independente desta regra
específica), usando o valor real de `P_ATIVO_1` contra uma lista de termos
sintética contendo `"bebida alcoolica"`, confirma que a comparação passa a
casar corretamente depois da correção P2 (não batia antes, por causa do
espaço à esquerda) — ver histórico deste documento/commits para o teste
isolado. O `sparql_rules_iexogena.json` anexado não tem nenhuma ocorrência
de `REGEX(LCASE` (fuzzy desligado — `Config.fuzzy_fields` vazio), então a
Fase 2 (fuzzy) não pôde ser verificada de ponta a ponta com este arquivo.

## 3. Conclusão

A correção do achado principal (P0) foi verificada de ponta a ponta com
sucesso: ontologia real, conjunto completo de regras reais, dados reais.
94 linhas antes e depois, 82 combinações (id, CID) idênticas, e as únicas 7
diferenças são exatamente as esperadas — nenhum efeito colateral em
nenhum outro registro.

A correção P2 (espaço em branco) permanece verificada apenas de forma
isolada (função corrigida testada diretamente com dados reais contra uma
lista sintética) — o conjunto de regras real fornecido não contém nenhuma
regra cujo caminho de origem dependa de casamento de lista para os
registros com espaço em branco disponíveis nesta amostra de 100 linhas.
