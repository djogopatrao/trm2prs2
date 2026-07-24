# Relatório de Investigação — VALOR_ORIGEM não corresponde ao campo de origem

> **Status: corrigido.** Este documento registra o estado do código **antes**
> da correção — mantido como evidência/histórico do diagnóstico. A correção
> em si está em `BUG_FIX_PLAN.md` (itens P0, já implementados) e validada em
> `test_bugfix_origem.py` (16/16 casos passam, cobrindo os 4 consumidores da
> lógica corrigida). Os achados secundários das seções 5.1/5.2 (espaço em
> branco, valores compostos) **continuam pendentes** (P2/P3 em
> `BUG_FIX_PLAN.md`).
>
> Investigação apenas. Nenhuma alteração foi feita em `excel_to_sparql.py`
> nem em nenhum outro arquivo do repositório **durante esta investigação**
> (a correção veio depois, num commit separado). Todas as evidências abaixo
> vêm de (1) inspeção cruzada dos dois CSVs anexados
> (`IEXOBR19_PREPARADO_100.csv` = entrada, `IEXOBR19_PREPARADO_100_inferido.csv`
> = saída da query) e (2) execução isolada, via `pyoxigraph`, do trecho de
> SPARQL realmente gerado por `SparqlClauseBuilder._origem_agente_lines`
> (e das duas cópias equivalentes do mesmo padrão em `regra_complexa_agente_x70`
> e `regra_agente_tox_qualquer_conteudo`).

## 1. Resumo do achado principal

O sintoma relatado ("`valor_origem` não corresponde ao valor preenchido no
campo de origem") **não é uma discrepância entre as duas colunas do CSV de
saída** — cruzei programaticamente as 94 linhas do arquivo `_inferido.csv`
contra a coluna correspondente do CSV de entrada (por `_ORIGINAL_ID` +
`CAMPO_ORIGEM`) e as duas sempre coincidem como strings.

O problema real é mais sutil e mais grave: **a lógica de "primeiro campo de
agente preenchido" (usada para popular `CAMPO_ORIGEM`/`VALOR_ORIGEM` sempre
que nenhuma rota mais específica expõe a origem) usa `BOUND()` para decidir
se um campo está "preenchido", mas `BOUND()` só verifica se a variável tem
ALGUM valor — inclusive uma string vazia.** Se o grafo RDF que serviu de
base às consultas representa uma célula vazia da planilha como uma tripla
com objeto `""` (string vazia) — em vez de simplesmente omitir a tripla —
essa lógica quebra: ela sempre relata `AGENTE_1` como origem (mesmo vazio),
**ignorando silenciosamente qualquer campo posterior que tenha conteúdo
real**. Isso foi confirmado tanto nos dados reais quanto por um teste
controlado isolado do trecho de SPARQL gerado (seção 3).

## 2. Método de investigação

1. Carreguei os dois CSVs e indexei o de entrada por `ID_TRAUMA_VITIMA`.
2. Para cada linha do CSV de saída, comparei `VALOR_ORIGEM` com o valor da
   coluna indicada por `CAMPO_ORIGEM` (removendo o prefixo `intox:`) na
   linha correspondente do CSV de entrada — **0 divergências em 94 linhas**.
3. Como a comparação direta não revelou nada, examinei manualmente os casos
   com múltiplos campos preenchidos e/ou valores duplicados entre campos
   (ex.: `AGENTE_1` e `P_ATIVO_1` com o mesmo texto), procurando por
   inconsistências de comportamento entre registros estruturalmente
   parecidos.
4. Isso revelou um padrão: registros em que **nenhum campo de agente está
   preenchido** ainda assim aparecem no CSV de saída com
   `CAMPO_ORIGEM=intox:AGENTE_1` (em vez de em branco). Segundo o próprio
   comentário do código-fonte (`_origem_agente_lines`, linhas 726-729:
   *"se NENHUM campo de agente estiver preenchido, ?_valor/?_campo ficam
   unbound e os triplos CAMPO_ORIGEM/VALOR_ORIGEM não materializam"*), isso
   não deveria acontecer.
5. Extraí o trecho de SPARQL realmente gerado por `_origem_agente_lines` e
   o executei isoladamente contra um `pyoxigraph.Store` sintético, com
   cenários controlados (campo *ausente* vs. campo *presente com string
   vazia*), para isolar a causa raiz (seção 3).

## 3. Evidência técnica — teste controlado do SPARQL gerado

Trecho de SPARQL gerado por `SparqlClauseBuilder._origem_agente_lines("X999", "test")`
(linhas 712-753 de `excel_to_sparql.py`):

```sparql
OPTIONAL { ?registro intox:AGENTE_1 ?_a0_test. }
OPTIONAL { ?registro intox:AGENTE_2 ?_a1_test. }
OPTIONAL { ?registro intox:AGENTE_3 ?_a2_test. }
OPTIONAL { ?registro intox:P_ATIVO_1 ?_a3_test. }
OPTIONAL { ?registro intox:P_ATIVO_2 ?_a4_test. }
OPTIONAL { ?registro intox:P_ATIVO_3 ?_a5_test. }
BIND( COALESCE(?_a0_test, ?_a1_test, ?_a2_test, ?_a3_test, ?_a4_test, ?_a5_test) AS ?_valor_test )
BIND( COALESCE(
    IF(BOUND(?_a0_test), intox:AGENTE_1, 1/0),
    IF(BOUND(?_a1_test), intox:AGENTE_2, 1/0),
    IF(BOUND(?_a2_test), intox:AGENTE_3, 1/0),
    IF(BOUND(?_a3_test), intox:P_ATIVO_1, 1/0),
    IF(BOUND(?_a4_test), intox:P_ATIVO_2, 1/0),
    IF(BOUND(?_a5_test), intox:P_ATIVO_3, 1/0)
) AS ?_campo_test )
```

Executando esse trecho isoladamente contra 4 cenários sintéticos (pyoxigraph):

| Cenário | Dados do registro | `CAMPO_ORIGEM` obtido | `VALOR_ORIGEM` obtido |
|---|---|---|---|
| A — AGENTE_1 verdadeiramente **ausente**, AGENTE_2 preenchido | `AGENTE_2="CLONAZEPAM"` (sem tripla para AGENTE_1) | `intox:AGENTE_2` ✅ | `"CLONAZEPAM"` ✅ |
| B — AGENTE_1 **presente com string vazia**, AGENTE_2 preenchido | `AGENTE_1=""`, `AGENTE_2="CLONAZEPAM"` | `intox:AGENTE_1` ❌ | `""` ❌ (ignora CLONAZEPAM) |
| C — nenhum campo presente | (nenhuma tripla) | `None` (não materializa) ✅ | `None` ✅ |
| D — todos os 6 campos presentes com string vazia | `AGENTE_1=""`, …, `P_ATIVO_3=""` | `intox:AGENTE_1` | `""` |

O cenário **B é a causa raiz**: quando um campo está *presente no grafo mas
vazio* (em vez de ausente), `BOUND()` retorna verdadeiro assim mesmo, então
`COALESCE` para no **primeiro** candidato (`AGENTE_1`) e nunca chega a
avaliar `AGENTE_2`, mesmo este tendo conteúdo real. O cenário C confirma que
a lógica funciona corretamente **apenas quando a ausência é representada
pela ausência da tripla** — não quando é representada por um valor vazio.

## 4. Evidência nos dados reais (10 casos investigados)

| # | `_ORIGINAL_ID` | CID inferido | Campos preenchidos na entrada | `CAMPO_ORIGEM`/`VALOR_ORIGEM` na saída | Diagnóstico |
|---|---|---|---|---|---|
| 1 | 79 | Y190 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Cenário B/D real: origem fabricada a partir de nada. Deveria estar em branco (comentário do código, linhas 726-729). |
| 2 | 4 | Y149 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 3 | 87 | X440 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 4 | 89 | X490 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 5 | 74 | X690 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 6 | 15 | X690 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 7 | 75 | X640 | *(nenhum)* | `intox:AGENTE_1` / `""` | ❌ Mesmo padrão. |
| 8 | 8 | X610 | `P_ATIVO_1=CLONAZEPAM` (AGENTE_1 ausente) | `intox:P_ATIVO_1` / `"CLONAZEPAM"` | ✅ Correto — mas por sorte de rota: X610 usa `filter_list_agente_origem` (casamento real contra lista), que não sofre do bug, e não a lógica "primeiro campo preenchido". |
| 9 | 90 | X610 | 4 campos preenchidos, todos batendo numa lista | 4 linhas de saída, uma por campo/valor casado, todas corretas | ✅ Comportamento correto de `filter_list_agente_origem`, incluído para contraste com o caminho universal. |
| 10 | 26 | X640 | `AGENTE_1="AMITRIL,POLARAMINE,RIVOTRIL"` (valor composto, célula do CSV com vírgulas internas entre aspas) | `intox:AGENTE_1` / `"AMITRIL,POLARAMINE,RIVOTRIL"` | ⚠️ Achado secundário (seção 5.2): o valor composto inteiro é reportado como se fosse "a origem", sem separar os 3 medicamentos. |

Os casos 1–7 são instâncias **reais e confirmadas** do cenário B/D — não
apenas um risco teórico. Nenhum dos 100 registros de entrada, porém, expõe
o cenário B em sua forma mais perigosa (AGENTE_1 vazio-mas-presente **e**
um campo posterior com conteúdo real, associado a uma regra do caminho
universal) — os únicos 2 registros de entrada com essa combinação
(`ID_TRAUMA_VITIMA` 8 e 20) foram, por coincidência, tratados por regras que
usam `filter_list_agente_origem` (caminho correto), não pela lógica
"primeiro campo preenchido". O teste controlado da seção 3 (cenário B)
demonstra que, para qualquer regra que dependa da lógica universal,
**um valor real em `AGENTE_2`/`AGENTE_3`/`P_ATIVO_*` seria silenciosamente
descartado** em favor de um `AGENTE_1` vazio, assim que essa combinação
ocorrer nos dados.

## 5. Localização exata no código-fonte

A mesma lógica com o mesmo defeito está **duplicada em 3 lugares**
(mesmo padrão `IF(BOUND(...), intox:CAMPO, 1/0)`, sem checar `STRLEN`):

| Local | Linha | Usado por |
|---|---|---|
| `SparqlClauseBuilder._origem_agente_lines` | 745 | Caminho universal (`rule_to_sparql`, ramo `else`) e X89 (`filtro_not_exists_agente`) |
| `SparqlClauseBuilder.regra_complexa_agente_x70` (Ramo A) | 1042 | Padrão X70 completo (`AGENTE_TOX` em {02,03,04,05}) |
| `SparqlClauseBuilder.regra_agente_tox_qualquer_conteudo` | 1122 | Forma reduzida do X70 (planilha nova) |

O próprio código já contém, em **outro lugar**, o padrão que evitaria esse
problema: `filtro_not_exists_agente` (guarda `not_empty`, linhas 1205 e
1219) e `regra_agente_preenchimento_e_cid_nao_inferido` (linha 1287) usam
`STRLEN(STR(?var)) > 0` para checar se um campo está *realmente* preenchido
— não apenas `BOUND()`. As 3 ocorrências da seção acima não usam esse
padrão, o que é inconsistente com o resto do código-fonte, apesar de o
código já "saber" que essa é a forma correta de checar preenchimento.

## 6. Achados secundários (relacionados, mas distintos do sintoma relatado)

### 5.1 — Sensibilidade a espaço em branco no início/fim do valor

`ID_TRAUMA_VITIMA=85`: `AGENTE_1="BEBIDA ALCOOLICA"` (casa a lista),
`P_ATIVO_1=" BEBIDA ALCOOLICA"` **com um espaço à esquerda**. A saída só
reporta `AGENTE_1` — `P_ATIVO_1` não aparece, plausivelmente porque o
espaço extra impede o casamento exato contra o termo da lista (nem a Fase 1
nem a Fase 2 aplicam `TRIM()`/normalização de espaços antes de comparar).
Não é o mesmo bug da seção 1–5, mas é um sintoma correlato de "o valor
esperado não corresponde ao que a query captura" causado por uma limitação
diferente (ausência de normalização de espaços).

### 5.2 — Valores compostos (múltiplas substâncias em uma única célula)

`ID_TRAUMA_VITIMA=26`: `AGENTE_1="AMITRIL,POLARAMINE,RIVOTRIL"` (uma única
célula do CSV contendo 3 nomes de medicamento separados por vírgula, entre
aspas). Quando esse campo é reportado como origem (caminho universal), o
`VALOR_ORIGEM` reproduz a célula inteira, não um medicamento individual —
tecnicamente "corresponde" ao dado bruto de entrada, mas é de utilidade
questionável como "origem" de uma inferência específica, e impede qualquer
tentativa de casamento por lista contra os 3 termos individualmente.

## 7. Resumo dos problemas encontrados no SPARQL gerado

1. **(Principal, confirmado nos dados)** `_origem_agente_lines`,
   `regra_complexa_agente_x70` (Ramo A) e `regra_agente_tox_qualquer_conteudo`
   usam `IF(BOUND(?_aN), intox:CAMPO_N, 1/0)` para decidir qual campo é "o
   primeiro preenchido". `BOUND()` não distingue "tripla ausente" de "tripla
   presente com literal vazio" — se o grafo de instâncias representa células
   vazias da planilha como triplas com objeto `""`, a lógica sempre escolhe
   `AGENTE_1` (mesmo vazio) e nunca avalia os campos seguintes, mascarando
   qualquer valor real que exista em `AGENTE_2`, `AGENTE_3` ou `P_ATIVO_*`.
   Confirmado em 7 dos 100 registros de teste (todos-campos-vazios) e
   reproduzido isoladamente via `pyoxigraph`.
2. Essa mesma lógica defeituosa está copiada 3 vezes no código-fonte, todas
   com o mesmo problema — uma delas corrigida seria necessário corrigir nas
   outras duas igualmente.
3. O restante do código já contém o padrão correto (`STRLEN(STR(?var))>0`)
   em outros dois pontos (`filtro_not_exists_agente`, `regra_agente_preenchimento_e_cid_nao_inferido`),
   então a inconsistência não é falta de conhecimento do padrão certo, é
   falta de aplicá-lo nos 3 locais da seção 5.
4. (Secundário) Ausência de normalização de espaços em branco antes da
   comparação de termos — um valor com espaço extra não casa com o termo
   da lista mesmo sendo "o mesmo" para um humano.
5. (Secundário) Células com múltiplos valores compostados numa única string
   (separados por vírgula) são tratadas como um único termo atômico, tanto
   para casamento contra listas quanto para o valor reportado como origem.

Nenhuma correção foi aplicada a `excel_to_sparql.py` nem a nenhum outro
arquivo, conforme solicitado.
