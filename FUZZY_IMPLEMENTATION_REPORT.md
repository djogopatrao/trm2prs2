# Relatório — Implementação e Testes do Matching Fuzzy (Fase 2)

> Implementação feita seguindo `FUZZY_IMPLEMENTATION_PLAN.md`. Os testes
> foram executados e **nenhuma correção foi aplicada** aos problemas
> encontrados — este documento reporta exatamente o que ocorreu, para
> avaliação da estratégia antes de qualquer ajuste.

## 1. Resumo executivo

```
Total: 34   PASS: 31   FAIL: 1   SKIP: 2   ERROR: 0
```

- **31 casos passaram**, incluindo todos os 9 `LEGACY` + 10 `CASE` (Fase 1,
  não deveriam ser afetados pela Fase 2 — e não foram) e 12 dos 14 `FUZZY`.
- **1 caso falhou**: `FUZZY-12`. Causa raiz identificada (seção 4.1): **defeito
  no dado de teste**, não no código implementado.
- **2 casos continuam `SKIP`**, ambos por design: `LEGACY-10` (controle
  categórico, fora de escopo desde a Fase 1) e `FUZZY-10` (colisão ambígua,
  documentada desde a criação de `TEST_CASES.json` como não-automatizável).
- **0 erros de execução** (nenhuma exceção do gerador ou do pyoxigraph).

## 2. O que foi implementado

Seguindo `FUZZY_IMPLEMENTATION_PLAN.md` seção 4, item a item:

| Item do plano | Status |
|---|---|
| 4.1 `Config.fuzzy_fields` / `Config.fuzzy_min_term_length` | ✅ Implementado |
| 4.2 Helpers `_escape_regex_char`, `_fuzzy_variants`, `_escape_sparql_string`, `_build_terms_pattern` | ✅ Implementado, incluindo a correção de ordem de escaping (escapar por caractere antes de splicing, preservando o `.` de substituição) |
| 4.3 `filter_exists_list_in_value(..., fuzzy=False)` | ✅ Implementado |
| 4.4 `filter_list_agente_origem(..., fuzzy=False)` | ✅ Implementado — **sem caso de teste fuzzy dedicado** (gap já sinalizado no plano, seção 2; não preenchido agora) |
| 4.5 `filter_list_inline(..., fuzzy=False)` | ✅ Implementado |
| 4.6 `filter_list` dispatcher — `fuzzy` + `ValueError` se combinado com `not_exists=True` | ✅ Implementado |
| 4.7 `regra_volume_iii_cid(..., fuzzy=False)` | ✅ Implementado |
| 4.8 `RuleProcessor._process_field` lendo `Config.fuzzy_fields` | ✅ Implementado nos 3 pontos (lista genérica, `regra_local_exposicao`, Volume III) |
| Seção 5 — `run_tests.py`: remover skip geral de fuzzy, adaptadores repassando `fuzzy` | ✅ Implementado |

`SparqlClauseBuilder.__init__` ganhou o parâmetro `fuzzy_min_term_length`
(não estava explicitado no plano em nível de assinatura, mas era necessário
para os métodos acessarem o limiar) — `RuleProcessor.rule_to_sparql` passa
`self._config.fuzzy_min_term_length` ao construir o builder.

## 3. Resultado completo dos testes

```
[✓] LEGACY-01    PASS      0.318 ms  esperado=True obtido=True
[✓] LEGACY-02    PASS      0.099 ms  esperado=False obtido=False
[✓] LEGACY-03    PASS      0.097 ms  esperado=True obtido=True
[✓] LEGACY-04    PASS      0.106 ms  esperado=True obtido=True
[✓] LEGACY-05    PASS      0.079 ms  esperado=False obtido=False
[✓] LEGACY-06    PASS      0.069 ms  esperado=True obtido=True
[✓] LEGACY-07    PASS      0.482 ms  esperado=True obtido=True
[✓] LEGACY-08    PASS      0.228 ms  esperado=True obtido=True
[✓] LEGACY-09    PASS      0.123 ms  esperado=True obtido=True
[·] LEGACY-10    SKIP             —  campo categórico (fora do escopo)
[✓] CASE-01      PASS      0.082 ms  esperado=True obtido=True
[✓] CASE-02      PASS      0.065 ms  esperado=True obtido=True
[✓] CASE-03      PASS      0.062 ms  esperado=True obtido=True
[✓] CASE-04      PASS      0.089 ms  esperado=True obtido=True
[✓] CASE-05      PASS      0.067 ms  esperado=True obtido=True
[✓] CASE-06      PASS      0.057 ms  esperado=True obtido=True
[✓] CASE-07      PASS      0.287 ms  esperado=True obtido=True
[✓] CASE-08      PASS      0.165 ms  esperado=True obtido=True
[✓] CASE-09      PASS      0.144 ms  esperado=True obtido=True
[✓] CASE-10      PASS      0.079 ms  esperado=True obtido=True
[✓] FUZZY-01     PASS      0.998 ms  esperado=True obtido=True   (substituição)
[✓] FUZZY-02     PASS      0.568 ms  esperado=True obtido=True   (deleção)
[✓] FUZZY-03     PASS      0.348 ms  esperado=True obtido=True   (duplicação)
[✓] FUZZY-04     PASS      0.680 ms  esperado=True obtido=True   (duplicação posição 0)
[✓] FUZZY-05     PASS      0.932 ms  esperado=True obtido=True   (filter_list_inline)
[✓] FUZZY-06     PASS      0.591 ms  esperado=True obtido=True   (case + fuzzy combinados)
[✓] FUZZY-07     PASS      0.490 ms  esperado=False obtido=False (2 erros — controle negativo)
[✓] FUZZY-08     PASS      0.149 ms  esperado=False obtido=False (termo curto — guarda de tamanho)
[✓] FUZZY-09     PASS      0.439 ms  esperado=True obtido=True   (colisão, cenário isolado)
[·] FUZZY-10     SKIP             —  ambíguo — requer revisão manual (by design)
[✓] FUZZY-11     PASS      2.726 ms  esperado=True obtido=True   (escaping, exato)
[✗] FUZZY-12     FAIL      2.423 ms  esperado=True obtido=False  (escaping, "deleção" — VER SEÇÃO 4.1)
[✓] FUZZY-13     PASS      0.107 ms  esperado=False obtido=False (fronteira: exclusão NÃO recebe fuzzy)
[✓] FUZZY-14     PASS      0.497 ms  esperado=True obtido=True   (regra_volume_iii_cid herda fuzzy)

Total: 34  PASS: 31  FAIL: 1  SKIP: 2  ERROR: 0
```

## 4. Análise dos casos sem PASS limpo

### 4.1 `FUZZY-12` (FAIL) — defeito no dado de teste, não na implementação

O caso espera que `"ácido acetilsaliciico (aas)"` case, via 1 deleção, com o
termo canônico `"ácido acetilsalicílico (aas)"`. Investigação
(`difflib.SequenceMatcher`) mostra os opcodes reais entre os dois textos:

```
[('equal', 0, 17, 0, 17), ('replace', 17, 19, 17, 18), ('equal', 19, 28, 18, 27)]
```

Ou seja, o trecho `"íl"` (2 caracteres) do termo canônico foi substituído por
`"i"` (1 caractere) no valor de entrada — isso é **uma substituição (í→i) MAIS
uma deleção (do "l")**, distância de edição **2**, não 1. O comentário que eu
mesmo escrevi em `TEST_CASES.json` ("1 deleção... fora da parte entre
parênteses") está incorreto: o valor de entrada foi digitado errado ao criar
o caso — ele contém duas edições, não uma.

Confirmação isolando a implementação (fora do runner, testando o helper
diretamente): uma deleção **limpa** de fato do mesmo termo casa
corretamente:

```
>>> ask("ácido acetilsaicílico (aas)")   # remove só o 'l', mantém o 'í'
True
>>> ask("ácido acetilsaliciico (aas)")   # valor real do FUZZY-12 (2 edições)
False
```

**Conclusão**: a implementação está correta — ela rejeita, como deveria, uma
entrada a 2 edições de distância. O `FAIL` é do `TEST_CASES.json`
(`resultado_esperado: true` está errado para o `valor_entrada` registrado),
não do código de `excel_to_sparql.py`. Nenhuma correção foi feita, conforme
solicitado.

### 4.2 `LEGACY-10` (SKIP) — esperado, sem mudança

Continua fora de escopo (campo categórico, comparação por URI) desde a Fase
1. Nenhuma implicação para a Fase 2.

### 4.3 `FUZZY-10` (SKIP) — esperado, por design

`resultado_esperado` deste caso é a string `"ambiguo — ver observacao"` (não
um booleano) desde a criação de `TEST_CASES.json`, exatamente para forçar
`run_case` a não tratá-lo como PASS/FAIL automático — é o cenário de colisão
entre dois termos distintos a 1 edição um do outro, que exige julgamento
humano. Comportamento correto e sem mudanças.

## 5. Medições de tempo — não-fuzzy vs. fuzzy

| numero do teste | tempo (não fuzzy) | tempo (fuzzy) |
|---|---|---|
| LEGACY-01 | 0.318 ms | — |
| LEGACY-02 | 0.099 ms | — |
| LEGACY-03 | 0.097 ms | — |
| LEGACY-04 | 0.106 ms | — |
| LEGACY-05 | 0.079 ms | — |
| LEGACY-06 | 0.069 ms | — |
| LEGACY-07 | 0.482 ms | — |
| LEGACY-08 | 0.228 ms | — |
| LEGACY-09 | 0.123 ms | — |
| LEGACY-10 | — | — |
| CASE-01 | 0.082 ms | — |
| CASE-02 | 0.065 ms | — |
| CASE-03 | 0.062 ms | — |
| CASE-04 | 0.089 ms | — |
| CASE-05 | 0.067 ms | — |
| CASE-06 | 0.057 ms | — |
| CASE-07 | 0.287 ms | — |
| CASE-08 | 0.165 ms | — |
| CASE-09 | 0.144 ms | — |
| CASE-10 | 0.079 ms | — |
| FUZZY-01 | — | 0.998 ms |
| FUZZY-02 | — | 0.568 ms |
| FUZZY-03 | — | 0.348 ms |
| FUZZY-04 | — | 0.680 ms |
| FUZZY-05 | — | 0.932 ms |
| FUZZY-06 | — | 0.591 ms |
| FUZZY-07 | — | 0.490 ms |
| FUZZY-08 | — | 0.149 ms |
| FUZZY-09 | — | 0.439 ms |
| FUZZY-10 | — | — |
| FUZZY-11 | — | 2.726 ms |
| FUZZY-12 | — | 2.423 ms |
| FUZZY-13 | — | 0.107 ms |
| FUZZY-14 | — | 0.497 ms |

**Leitura**: casos não-fuzzy sobre 1 termo curto ficam na casa de
0.06–0.13 ms; os fuzzy equivalentes (mesmo cenário, 1 termo) ficam entre
0.35–1.0 ms — um overhead de **~3× a ~8×** por causa do `REGEX` avaliado por
binding em vez do `IN` (hash lookup), exatamente o risco de performance
previsto no `MODIFICATION_PLAN.md` (seção 6) e no `FUZZY_IMPLEMENTATION_PLAN.md`
(seção 6). `FUZZY-11`/`FUZZY-12` (2.4–2.7 ms) são os mais caros: o termo tem
parênteses + é o mais longo do conjunto (28 caracteres), gerando o maior
número de alternativas no padrão. `FUZZY-13`, que não recebe fuzzy (fica no
caminho de exclusão), tem tempo comparável ao não-fuzzy (0.107 ms) —
confirma que a fronteira de escopo também vale para custo, não só para
comportamento.

Estas são medições de execução única em `Store` minúsculo (uma tripla),
servindo como referência relativa, não como benchmark de produção — mesma
ressalva já registrada no `README.md`.

## 6. Achados adicionais durante a implementação (não cobertos por `TEST_CASES.json`)

### 6.1 `regra_local_exposicao` com `negation_list=True` — possível vazamento de fuzzy para um caminho de exclusão

`regra_local_exposicao` usa `filter_list_inline` em duas situações
semanticamente diferentes:
1. Inclusão simples (`values_listas` sem negação).
2. **Exclusão** disfarçada de inclusão: quando o valor começa com "7. Outro,
   quando o texto preenchido em LOC_EX_DE não for rastreado pelas listas...",
   o resultado de `filter_list_inline` é envolvido externamente por um
   `FILTER NOT EXISTS` (`negation_list=True`).

Implementei o repasse de `fuzzy` para `filter_list_inline` de forma
incondicional nos dois casos, seguindo literalmente o
`FUZZY_IMPLEMENTATION_PLAN.md` (que não distinguia esse sub-caso). Isso
significa que, se `"LOC_EXPO;LOC_EXP_DE"` for adicionado a
`Config.fuzzy_fields`, o ramo 2 (que é conceitualmente uma exclusão) também
receberia fuzzy — contradizendo a decisão de escopo da seção 2 do plano
("filtros de exclusão não recebem fuzzy nesta fase"). **Nenhum caso de
`TEST_CASES.json` exercita este sub-caminho com fuzzy habilitado**, então o
`run_tests.py` não capturou esta inconsistência — foi encontrada por
inspeção do código durante a implementação, não pelos testes. Reportando
sem corrigir, conforme solicitado.

### 6.2 Gap de cobertura confirmado: `filter_list_agente_origem`

Como já sinalizado no `FUZZY_IMPLEMENTATION_PLAN.md` seção 2, `filter_list_agente_origem`
recebeu o parâmetro `fuzzy` (seção 2 deste relatório), mas nenhum caso em
`TEST_CASES.json` o exercita com `modo_avaliado="fuzzy"`. A suíte atual não
dá nenhum sinal (nem PASS nem FAIL) sobre esse caminho especificamente —
ele está tecnicamente implementado, mas **não verificado**.

## 7. Riscos previstos vs. observados

| Risco previsto (`MODIFICATION_PLAN.md`/`FUZZY_IMPLEMENTATION_PLAN.md`) | Observado |
|---|---|
| Termos curtos geram falso positivo sem guarda de tamanho | Guarda funcionou: `FUZZY-08` ("sal", 3 chars) corretamente não casou |
| Fuzzy permite exatamente 1 erro, não mais | Confirmado: `FUZZY-07` (2 erros) corretamente não casou |
| `REGEX` mais caro que `IN`/`LCASE` | Confirmado: overhead de 3×–8× nos casos medidos (seção 5) |
| Escaping duplo regex→SPARQL é a fonte de erro mais provável | Parcialmente confirmado — não por bug de escaping em si (funcionou corretamente para o termo com parênteses), mas o caso de teste que deveria teste-lo (`FUZZY-12`) tinha o próprio dado errado, mascarando a validação |
| Colisão entre termos distintos a 1 edição | Documentada e isolada como não-automatizável (`FUZZY-10`), sem tentativa de resolução automática — comportamento esperado |
| Fuzzy vazar para caminhos de exclusão | Confirmado que **não** vaza no caminho testado (`FUZZY-13`, `filter_not_list`); porém identificado um caminho **não testado** onde poderia vazar (seção 6.1) |

## 8. Conclusão

A estratégia de matching fuzzy descrita no `FUZZY_IMPLEMENTATION_PLAN.md`
funciona como projetada nos 12 dos 14 cenários que a exercitam diretamente,
incluindo os controles negativos mais importantes (2 erros, termo curto,
fronteira de exclusão). O único `FAIL` tem causa raiz em um dado de teste
incorreto, não na implementação. Os dois `SKIP` são esperados por design.

Itens em aberto (nenhum corrigido nesta rodada, por instrução explícita):
1. `FUZZY-12`: corrigir o `valor_entrada` em `TEST_CASES.json` para
   representar de fato 1 deleção.
2. Resolver a ambiguidade de escopo do `regra_local_exposicao` com
   `negation_list=True` (seção 6.1) — decidir se o `FILTER NOT EXISTS`
   externo deve bloquear `fuzzy=True` mesmo quando o campo está em
   `Config.fuzzy_fields`.
3. Adicionar um caso `FUZZY` para `filter_list_agente_origem` (gap sinalizado
   desde o plano original, ainda não preenchido).
4. Regenerar a seção de medições do `README.md` com os números reais desta
   tabela (README ainda mostra a Fase 2 como pendente e todas as colunas
   fuzzy como "—").
