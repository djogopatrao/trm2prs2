# Plano de Implementação — Matching Fuzzy (Fase 2)

> Documento de planejamento apenas. Nenhum código foi alterado. Complementa o
> `MODIFICATION_PLAN.md` (que já descrevia a Fase 2 em alto nível, seções 3.2,
> 4.1, 4.2 e 7) com um desenho concreto, pronto para implementação, agora que
> a Fase 1 (case-insensitive) já está aplicada em `excel_to_sparql.py` e
> validada por `TEST_CASES.json` via `run_tests.py`.

## 1. O que já existe (ponto de partida)

Consultei o estado atual do repositório antes de planejar:

- **`excel_to_sparql.py`**: os 8 pontos de comparação já usam
  `LCASE(STR(?var))` (linhas 753, 787, 824, 860, 975, 1085, 1090, 1166, 1175)
  e `_resolve_terms` (linha 1404) já normaliza todos os termos para
  minúsculas antes de embuti-los na query. Isso confirma que os números de
  linha do `MODIFICATION_PLAN.md` original continuam válidos — a Fase 1 não
  deslocou a estrutura do arquivo.
- **`TEST_CASES.json`**: já contém 14 casos `FUZZY` com a semântica exata que
  este plano precisa satisfazer, incluindo os controles negativos mais
  importantes:
  - `FUZZY-07`: 2 erros combinados → **não** deve casar (limite estrito de 1 erro).
  - `FUZZY-08`: termo de 3 caracteres ("sal") → **não** deve casar (guarda de tamanho mínimo).
  - `FUZZY-09`/`FUZZY-10`: colisão entre termos distintos → caso documentado como ambíguo, não automatizável.
  - `FUZZY-11`/`FUZZY-12`: termo com parênteses → exercita o escaping duplo.
  - `FUZZY-13`: `filter_not_list` (exclusão) → fuzzy **não** deve se aplicar (fronteira de escopo da Fase 2).
- **`run_tests.py`**: hoje pula todos os 14 casos `FUZZY` com
  `"fuzzy ainda não implementado"`. A seção 4 abaixo já leva em conta como
  esses adaptadores precisam mudar.
- **`README.md`**: a tabela de tempos já tem uma coluna "tempo (fuzzy)"
  reservada, hoje toda "—".

## 2. Escopo confirmado (o que recebe fuzzy e o que não recebe)

Mantendo a recomendação do `MODIFICATION_PLAN.md` (seção 7, Fase 2) e
confirmando contra os `funcao_alvo` usados nos 14 casos `FUZZY` de
`TEST_CASES.json`:

| Função | Recebe fuzzy? | Evidência |
|---|---|---|
| `filter_exists_list_in_value` | **Sim** | 9 dos 14 casos `FUZZY` usam esta função |
| `filter_list_inline` | **Sim** | `FUZZY-05` |
| `regra_volume_iii_cid` | **Sim** (herda, reusa `filter_exists_list_in_value`) | `FUZZY-14` |
| `filter_list_agente_origem` | **Sim**, por coerência com o plano original — nenhum caso de teste a exercita ainda | *gap a preencher em `TEST_CASES.json` quando esta fase for implementada* |
| `filter_not_list` (exclusão) | **Não** | `FUZZY-13` testa explicitamente que fuzzy NÃO se aplica aqui |
| `filtro_not_exists_agente` / `_disjuncoes_padroes_irmas` (exclusão, X89) | **Não** | Nenhum caso `FUZZY` os exercita; mesmo racional de exclusão do `filter_not_list` |
| `regra_complexa_agente_x70` (Ramo B) | **Não**, nesta fase | Já sinalizado como baixa prioridade no plano original (seção 4.8); nenhum caso `FUZZY` o exercita |

## 3. Algoritmo de geração do padrão fuzzy (revisão do desenho original)

O `MODIFICATION_PLAN.md` original (seção 4.2) já apontava o escaping duplo
regex→SPARQL como "a fonte de erro mais provável". Detalhando agora o
algoritmo por completo, existe uma sutileza que o plano original não
cobria explicitamente: **a alternativa de substituição introduz de propósito
um `.` (wildcard) não-escapado**, e um escaping "ingênuo" aplicado à string
inteira depois de montada apagaria essa distinção. A ordem correta é:

1. **Escapar cada caractere do termo individualmente** (não a string toda de
   uma vez), produzindo uma lista `chars_escapados`. Caracteres especiais de
   regex (`. ^ $ * + ? ( ) [ ] { } | \`) viram `\<char>`; os demais ficam
   como estão.
2. **Montar as variantes por posição, splicando a lista de caracteres já
   escapados**:
   - Exata: `"".join(chars_escapados)`
   - Substituição na posição *i*: `"".join(chars_escapados[:i]) + "." + "".join(chars_escapados[i+1:])`
     — o `.` é inserido *depois* do escaping por-caractere, então nunca é
     escapado por engano.
   - Deleção na posição *i*: `"".join(chars_escapados[:i] + chars_escapados[i+1:])`
   - Duplicação na posição *i*: `"".join(chars_escapados[:i+1] + [chars_escapados[i]] + chars_escapados[i+1:])`
3. **Aplicar a guarda de tamanho mínimo por termo** (não por lista — uma
   lista pode misturar termos curtos e longos, ex. `TEST_CASES.json` mistura
   "sal" com termos longos na mesma bateria): se `len(termo) < fuzzy_min_term_length`,
   pular os passos de substituição/deleção/duplicação e usar **somente** a
   variante exata para aquele termo específico. É exatamente o que
   `FUZZY-08` exige.
4. **Juntar todas as variantes de todos os termos da lista** com `|`,
   envolver com âncoras: `"^(" + "|".join(todas_as_variantes) + ")$"`.
5. **Só então** aplicar o escaping de string SPARQL (`\` → `\\`, `"` → `\"`)
   **uma única vez, sobre o padrão inteiro já montado**. Isso é seguro porque
   os únicos caracteres "estruturais" que sobram sem escape no padrão
   (`. | ^ $ ( )`) nunca são tocados pelo escaping de string SPARQL — ele só
   mexe em `\` e `"`.

Exemplo com o termo `ácido acetilsalicílico (aas)` (caso `FUZZY-11`/`FUZZY-12`):
- Passo 1: `(` e `)` viram `\(` e `\)`; os demais caracteres ficam iguais.
- Passo 2 (deleção, caso `FUZZY-12`, removendo o `l` de "saliciico"):
  variante = `ácido acetilsalic\(...\)` com um caractere a menos na parte
  textual — a parte entre parênteses continua escapada corretamente porque
  a deleção não mexeu nos elementos já escapados daquela região.
- Passo 5: qualquer `\` produzido no passo 1 vira `\\` no literal SPARQL
  final.

Essa é a mesma conclusão do plano original, mas agora com o passo a passo
exato — elimina a ambiguidade que a seção 4.2 anterior deixava em aberto.

## 4. Alterações de código previstas (ainda não aplicadas)

### 4.1 `Config` (linhas 47–93)
Adicionar dois campos, com defaults que mantêm o comportamento atual
(fuzzy desligado):
- `fuzzy_min_term_length: int = 5`
- `fuzzy_fields: frozenset[str] = frozenset()` — conjunto das chaves de
  campo (exatamente como aparecem no dicionário da regra, ex.
  `"AGENTE_1;AGENTE_2;AGENTE_3;P_ATIVO_1;P_ATIVO_2;P_ATIVO_3"`, não nomes de
  lista) elegíveis para fuzzy. Vazio = fuzzy completamente desligado, sem
  mudança de comportamento.

Decisão de desenho (resolvendo o "e/ou" deixado em aberto no plano
original): fuzzy é opt-in **por campo de regra**, não um único booleano
global — permite habilitar fuzzy em `AGENTE_*` sem afetar `LOC_EXPO`, por
exemplo, alinhado à recomendação de rollout restrito da seção 7.

### 4.2 Novos helpers de módulo (próximos a `_remove_source_tag`, linha 357)
- `_escape_regex_char(c: str) -> str` — escapa 1 caractere se for
  metacaractere de regex, senão devolve-o inalterado.
- `_fuzzy_variants(term: str, min_length: int) -> list[str]` — implementa os
  passos 1–3 da seção 3 acima; devolve a lista de variantes (já escapadas
  por caractere) para **um** termo.
- `_escape_sparql_string(s: str) -> str` — passo 5 (escaping de string
  SPARQL), aplicado uma única vez sobre o padrão completo.
- `_build_terms_pattern(terms: list[str], fuzzy: bool, min_length: int) -> str`
  — monta o padrão `^(...)$` final para uma lista de termos (já
  lowercased), delegando a `_fuzzy_variants` quando `fuzzy=True` ou usando
  apenas a forma exata escapada quando `fuzzy=False`.

### 4.3 `filter_exists_list_in_value` (linha 729, filtro na linha 753)
- Novo parâmetro `fuzzy: bool = False`.
- Quando `fuzzy=False`: comportamento **idêntico ao atual** (linha 753
  inalterada) — zero risco de regressão para o caminho não-fuzzy.
- Quando `fuzzy=True`: linha 753 passa a ser
  `f'\t\tFILTER ( REGEX(LCASE(STR(?{v_val})), "{pattern}", "i") ).'`
  usando `pattern = _build_terms_pattern(terms, fuzzy=True, min_length=...)`.
  A flag `"i"` é redundante com o `LCASE` (defesa em profundidade,
  documentada como intencional — não deve ser removida por parecer
  supérflua).

### 4.4 `filter_list_agente_origem` (linha 757, filtro nas linhas 786–787)
Mesma alteração de 4.3, aplicada à `FILTER` que hoje compara
`?{v_val}`. **Nenhum caso de `TEST_CASES.json` exercita este caminho com
fuzzy** — recomendo adicionar um caso `FUZZY` para `filter_list_agente_origem`
antes de considerar esta função coberta.

### 4.5 `filter_list_inline` (linha 832, filtro na linha 860)
Novo parâmetro `fuzzy: bool = False`; linha 860 troca
`f"LCASE(STR(?{v_val})) IN {in_str}"` por
`f'REGEX(LCASE(STR(?{v_val})), "{pattern}", "i")'` quando `fuzzy=True`.

### 4.6 `filter_list` — dispatcher (linha 874)
Novo parâmetro `fuzzy: bool = False`, repassado a
`filter_exists_list_in_value`/`filter_list_inline`. Quando `not_exists=True`
(caminho de exclusão) **e** `fuzzy=True` simultaneamente: levantar
`ValueError` explícito ("fuzzy não é suportado em filtros de exclusão nesta
fase") em vez de ignorar silenciosamente — mantém o estilo defensivo já usado
no dispatcher para a combinação `not_exists=True, filter_exists=True`.

### 4.7 `regra_volume_iii_cid` (linha 1295)
Novo parâmetro `fuzzy: bool = False`, repassado à chamada interna de
`filter_exists_list_in_value`.

### 4.8 `RuleProcessor._process_field` (linha ~1556)
Nos três pontos que hoje chamam `filter_list(...)`, `filter_list_agente_origem(...)`
ou (via `regra_local_exposicao`) `filter_list_inline(...)`/`regra_volume_iii_cid(...)`,
calcular `fuzzy = var_name in self._config.fuzzy_fields` e repassar. Isso
cobre:
- Bloco "Campo com valores que referenciam listas de termos" (linha ~1626).
- `regra_local_exposicao` → `filter_list_inline(["LOC_EXP_DE"], ...)`.
- Bloco "Termos do Volume III do CID-10" → `regra_volume_iii_cid(...)`.

## 5. Alterações previstas em `run_tests.py`

- Remover o `if tc.get("modo_avaliado") == "fuzzy": return "SKIP", ...` (linha
  170) — deixar de tratar fuzzy como categoria bloqueada; os 34 casos passam
  a rodar de verdade.
- Estender os adaptadores `_adapt_filter_exists_list_in_value`,
  `_adapt_filter_list_agente_origem`, `_adapt_filter_list_inline` e
  `_adapt_volume_iii` para aceitar e repassar `fuzzy=tc["modo_avaliado"] == "fuzzy"`
  aos métodos correspondentes do builder.
- **Não** alterar `_adapt_filter_not_list`, `_adapt_x89_fallback` e
  `_adapt_disjuncoes_padroes_irmas` — continuam chamando os métodos sem
  parâmetro fuzzy (eles nem o aceitam, por design). Isso faz `FUZZY-13`
  (que usa `filter_not_list`) continuar validando a fronteira de escopo
  automaticamente, sem lógica especial no runner.
- Resultado esperado após a mudança: os 33 casos não-categóricos executam de
  fato (`LEGACY` 9 + `CASE` 10 + `FUZZY` 14 = 33; `LEGACY-10` continua SKIP
  por ser controle categórico). `FUZZY-10` (colisão ambígua) deve continuar
  marcado para revisão manual — não tratar como PASS/FAIL automático mesmo
  depois de implementado (o próprio `resultado_esperado` do caso já é a
  string `"ambiguo — ver observacao"`, não um booleano, então
  `run_case` já o reporta como `SKIP` por `resultado_esperado` não-booleano).

## 6. Revalidação de regressão e performance

- **Regressão**: para `fuzzy=False`, a query gerada deve ser **byte-idêntica**
  à gerada hoje (Fase 1). Antes de mesclar a Fase 2, comparar a saída de
  `filter_exists_list_in_value`/`filter_list_agente_origem`/`filter_list_inline`
  com `fuzzy=False` explícito contra a saída atual (sem o parâmetro) para os
  mesmos argumentos — devem ser strings idênticas.
- **Performance**: `run_tests.py` já cronometra `store.query()` por caso
  (ver seção "Medições de tempo de execução das queries" do `README.md`).
  Depois de implementar, regerar a tabela com `--tabela-markdown` para
  popular a coluna "tempo (fuzzy)" com números reais e comparar contra a
  coluna "tempo (não fuzzy)" da mesma linha — dá uma medida direta do
  overhead do `REGEX` frente ao `IN`. Recomendo também adicionar um caso de
  teste sintético com uma lista de ~100 termos (fora do conjunto atual, só
  para stress) antes de habilitar fuzzy em listas de produção grandes, para
  ter uma noção de custo em escala real.

## 7. Ordem de execução recomendada

1. `Config`: adicionar `fuzzy_fields` e `fuzzy_min_term_length` (seção 4.1).
2. Helpers de módulo: `_escape_regex_char`, `_fuzzy_variants`,
   `_escape_sparql_string`, `_build_terms_pattern` (seção 4.2), com testes
   unitários diretos do algoritmo de escaping (independente de SPARQL/pyoxigraph)
   antes de integrá-los aos builders.
3. Adicionar `fuzzy` a `filter_exists_list_in_value`, `filter_list_agente_origem`,
   `filter_list_inline`, `filter_list`, `regra_volume_iii_cid` (seções 4.3–4.7),
   confirmando a regressão byte-idêntica da seção 6 a cada função alterada.
4. Conectar `RuleProcessor._process_field` a `Config.fuzzy_fields` (seção 4.8).
5. Atualizar `run_tests.py` (seção 5) e rodar a suíte completa — meta: 33
   executados, `FUZZY-07/08/13` como `FAIL` esperado vira `PASS` (controles
   negativos devem continuar corretos), `FUZZY-10` continua `SKIP` por
   design.
6. Regerar a tabela de tempos do `README.md` e atualizar a seção "Status da
   implementação" para marcar a Fase 2 como concluída.
7. Adicionar o caso `FUZZY` faltante para `filter_list_agente_origem`
   (gap identificado na seção 2) a `TEST_CASES.json`.
