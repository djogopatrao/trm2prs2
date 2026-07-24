# Plano de Correção — VALOR_ORIGEM/CAMPO_ORIGEM fabricados a partir de campo vazio

> Baseado nos achados de `BUG_INVESTIGATION_REPORT.md`. Todas as linhas
> citadas refletem o estado de `excel_to_sparql.py` **antes** da correção
> (pós Fase 1 case-insensitive + Fase 2 fuzzy, pré-correção deste bug).
>
> **Status: itens P0 (seções 2.1-2.3) implementados e testados.** Ver
> `test_bugfix_origem.py` (16/16 casos passam, cobrindo os 4 consumidores:
> `_origem_agente_lines` diretamente, caminho universal via
> `regra_complexa_agente_x70` Ramo A, `regra_agente_tox_qualquer_conteudo` e
> `filtro_not_exists_agente`/X89) e a suíte principal (`run_tests.py`,
> continua em 32 PASS/0 FAIL/2 SKIP, sem regressão). Itens P1/P2/P3
> permanecem pendentes.

## 1. Recapitulação do problema

`BOUND(?_aN)` retorna verdadeiro tanto para "a tripla existe com valor real"
quanto para "a tripla existe com literal vazio (`""`)". As três cópias da
lógica "primeiro campo de agente preenchido" usam apenas `BOUND()`, então
quando o grafo de instâncias representa uma célula vazia da planilha como
uma tripla com objeto `""` (em vez de omitir a tripla), a lógica:
1. Sempre escolhe `AGENTE_1` como `CAMPO_ORIGEM`, mesmo vazio;
2. Nunca chega a avaliar `AGENTE_2`/`AGENTE_3`/`P_ATIVO_*`, mesmo que tenham
   conteúdo real;
3. Nos casos em que **nenhum** campo tem conteúdo real, materializa
   `CAMPO_ORIGEM="intox:AGENTE_1"` / `VALOR_ORIGEM=""` em vez de não
   materializar os triplos (contradizendo o próprio comentário do código).

O restante do código já resolve exatamente esse problema em outros dois
lugares com `STRLEN(STR(?var))>0` — a correção é aplicar o mesmo padrão nos
3 locais que ainda usam só `BOUND()`.

## 2. Regiões do código a corrigir

### 2.1 `SparqlClauseBuilder._origem_agente_lines` — **P0 (crítica)** ✅ Implementado

- **Linhas 740-745** (loop que monta `coalesce_val_args`/`coalesce_campo_args`):
  ```python
  for i, c in enumerate(campos):
      a = f"?_a{i}_{sufixo}"
      lines.append(f"\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
      coalesce_val_args.append(a)                                         # linha 743
      coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")       # linha 745
  ```
  Alterar para:
  - `coalesce_val_args.append(a)` → `coalesce_val_args.append(f"IF(BOUND({a}) && STRLEN(STR({a}))>0, {a}, 1/0)")`
  - `coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")` → acrescentar `&& STRLEN(STR({a}))>0` à condição.
- **Linhas 746-748** (`BIND(COALESCE(...))`): sem alteração — já consomem as
  listas acima; o comportamento muda automaticamente com a correção do loop.
- **Usado por**: caminho universal (`rule_to_sparql`, ramo `else`, linha
  ~1636) e X89 (`filtro_not_exists_agente`, linha ~1237). Corrigir esta
  função corrige **ambos** os consumidores de uma vez — é o ponto de maior
  alavancagem (uma mudança, dois caminhos corrigidos).

### 2.2 `SparqlClauseBuilder.regra_complexa_agente_x70` — Ramo A — **P0 (crítica)** ✅ Implementado

- **Linhas 1037-1042** (loop idêntico ao de 2.1, duplicado):
  ```python
  for i, c in enumerate(campos):
      a = f"?_a{i}_x70"
      opt_lines.append(f"\t\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
      coalesce_val_args.append(a)                                         # linha 1040
      coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")       # linha 1042
  ```
  Mesma correção de 2.1 (adicionar `&& STRLEN(STR({a}))>0` às duas
  condições).
- **Linhas 1051-1052** (`BIND(COALESCE(...))` do Ramo A): sem alteração.
- **Nota de escopo**: o Ramo B (linhas 1059-1074) já usa `LCASE(STR(...))`
  para o casamento de lista (Fase 1) e **não** depende do padrão
  `BOUND()` para decidir a origem — o Ramo B expõe a origem a partir do
  casamento real contra a lista, não da lógica "primeiro preenchido". Não
  precisa de alteração.

### 2.3 `SparqlClauseBuilder.regra_agente_tox_qualquer_conteudo` — **P0 (crítica)** ✅ Implementado

- **Linhas 1118-1122** (terceira cópia do mesmo loop):
  ```python
  for i, c in enumerate(campos):
      a = f"?_a{i}_x70"
      opt_lines.append(f"\t\tOPTIONAL {{ ?registro intox:{c} {a}. }}")
      coalesce_val_args.append(a)                                         # linha 1121
      coalesce_campo_args.append(f"IF(BOUND({a}), intox:{c}, 1/0)")       # linha 1122
  ```
  Mesma correção de 2.1/2.2.
- **Linhas 1129-1130** (`BIND(COALESCE(...))`): sem alteração.

### 2.4 (Recomendado, não urgente) Eliminar a triplicação — **P1**

As três regiões acima são **cópias idênticas** do mesmo trecho de 5 linhas.
Uma vez aplicada a correção nas três (2.1-2.3), considerar refatorar
`regra_complexa_agente_x70` (Ramo A) e `regra_agente_tox_qualquer_conteudo`
para chamarem `_origem_agente_lines(...)` diretamente em vez de duplicar o
loop `OPTIONAL`/`COALESCE` — elimina a chance de uma quarta cópia divergir
no futuro. Não é urgente por si só (não corrige nenhum bug adicional além
do que 2.1-2.3 já corrigem), mas reduz o risco de regressão de manutenções
futuras. Requer mais cuidado, pois `regra_complexa_agente_x70`/`regra_agente_tox_qualquer_conteudo`
usam nomes de variável fixos (`_campo_x70`/`_valor_x70`/`_inf_x70`), diferente
do sufixo parametrizável de `_origem_agente_lines` — a chamada precisaria
passar `sufixo="x70"` explicitamente para preservar os nomes de variável
que o restante dessas funções referencia.

### 2.5 (Fora de escopo desta correção, avaliar separadamente) Achados secundários do relatório — **P2/P3**

- **Normalização de espaços em branco** (seção 5.1 do relatório): não há
  função `TRIM()` nativa em SPARQL 1.1 — a forma correta seria
  `REPLACE(STR(?v), "^\\s+|\\s+$", "")` aplicado a cada comparação de termo.
  Isso tocaria os **mesmos 8 pontos** já alterados nas Fases 1/2
  (`filter_exists_list_in_value`, `filter_list_agente_origem`,
  `filter_not_list`, `filter_list_inline`, etc.) — escopo comparável a uma
  nova fase, não uma correção pontual. Recomendo tratar como iniciativa
  separada, não como parte desta correção de bug.
- **Valores compostos em uma única célula** (seção 5.2 do relatório, ex.
  `"AMITRIL,POLARAMINE,RIVOTRIL"`): é uma limitação de modelagem de dados,
  não corrigível apenas na camada SPARQL sem antes decidir, com o time de
  domínio, como separar/tratar múltiplos valores dentro de uma célula.
  **P3** — requer decisão de produto antes de qualquer mudança de código.

## 3. Avaliação de risco de regressão

| Item | Risco | Justificativa |
|---|---|---|
| 2.1 `_origem_agente_lines` | **Baixo** | Para registros onde o campo já era genuinamente ausente (sem tripla), `BOUND()` já era falso — a adição de `STRLEN(STR(...))>0` é um no-op nesses casos (a condição já era falsa por `BOUND`). Só muda comportamento nos casos que o próprio relatório classifica como incorretos hoje (campo presente-mas-vazio). Impacta 2 consumidores (universal + X89) — testar ambos. |
| 2.2 `regra_complexa_agente_x70` Ramo A | **Baixo** | Mesma lógica de 2.1, mesmo argumento. Único cuidado: Ramo A é parte de uma `UNION` com o Ramo B — confirmar que a correção não introduz nenhuma variável cruzando a fronteira do UNION (o padrão atual já evita isso; a correção não adiciona novas variáveis, só refina a condição das existentes). |
| 2.3 `regra_agente_tox_qualquer_conteudo` | **Baixo** | Mesma lógica de 2.1/2.2. |
| 2.4 Eliminar duplicação (refatoração) | **Médio** | Mexe na estrutura de 2 funções (não só na condição), risco de alterar nomes de variável/quebrar referências do CONSTRUCT se o sufixo não for passado corretamente. Só fazer **depois** de 2.1-2.3 estarem corrigidos e testados isoladamente. |
| 2.5 Normalização de espaços | **Médio-Alto** | Toca os mesmos 8 pontos das Fases 1/2 — mesmo perfil de risco já documentado em `MODIFICATION_PLAN.md` (mudança de comportamento em filtros de exclusão, possível impacto em performance). Tratar como iniciativa própria, com seu próprio plano. |
| 2.5 Valores compostos | **Alto / bloqueado** | Não há mudança de código segura sem definição prévia de regra de negócio (separar por vírgula? Ignorar? Tratar como termo atômico?). Fazer antes disso seria adivinhação. |

## 4. Priorização recomendada

1. **P0 — Fazer primeiro, em conjunto**: itens 2.1, 2.2 e 2.3 (mesma
   correção, 3 locais). Baixo risco, corrige diretamente os 7 casos
   confirmados no `BUG_INVESTIGATION_REPORT.md` e a classe mais ampla de
   bug (mascaramento de campo posterior preenchido) demonstrada no teste
   controlado da seção 3 daquele relatório. **✅ Feito** — ver
   `test_bugfix_origem.py` e a seção 5 abaixo.
2. **P1 — Depois, opcional**: item 2.4 (eliminar a triplicação). Só depois
   de 2.1-2.3 estarem corrigidos e validados — não é pré-requisito, é
   redução de dívida técnica.
3. **P2 — Iniciativa separada, planejar depois**: normalização de espaços
   (2.5a). Merece seu próprio plano de modificação (nos moldes de
   `MODIFICATION_PLAN.md`/`FUZZY_IMPLEMENTATION_PLAN.md`), não uma correção
   pontual.
4. **P3 — Aguardando decisão de produto**: valores compostos numa única
   célula (2.5b). Não colocar no roadmap de código até haver uma decisão
   de negócio sobre como tratar esses valores.

## 5. Validação realizada após a correção (P0)

- **✅ Feito**: `test_bugfix_origem.py` cobre os 4 cenários de
  `BUG_INVESTIGATION_REPORT.md` (campo ausente + posterior preenchido;
  1º campo bound-mas-vazio + posterior preenchido; nenhum campo presente;
  todos os campos bound-mas-vazios) contra os **4 consumidores** da lógica
  corrigida: `_origem_agente_lines` diretamente, `regra_complexa_agente_x70`
  (Ramo A), `regra_agente_tox_qualquer_conteudo` e
  `filtro_not_exists_agente` (rota X89, que também usa `_origem_agente_lines`
  internamente). **16/16 casos passam.** Não reimplementa a lógica —
  executa o SPARQL real gerado pelo código de produção contra um
  `pyoxigraph.Store` sintético, igual ao padrão de `run_tests.py`.
- **✅ Feito**: suíte principal (`python3 run_tests.py`) reexecutada após a
  correção — permanece em **32 PASS, 0 FAIL, 2 SKIP**, idêntico ao resultado
  pré-correção, confirmando ausência de regressão nos casos de
  case-insensitive (Fase 1) e fuzzy (Fase 2) já cobertos.
- **Pendente**: reexecutar os 100 registros da amostra anexada (ou o
  dataset completo, se disponível) contra o pipeline completo
  (`excel_to_sparql.py` + ontologia + planilha reais) e confirmar que os 7
  casos que hoje mostram `CAMPO_ORIGEM=intox:AGENTE_1`/`VALOR_ORIGEM=""`
  passam a não materializar esses dois triplos — não foi possível validar
  isso end-to-end nesta correção porque a planilha/ontologia/parquet reais
  não estão disponíveis neste repositório (só o CSV de amostra e sua saída,
  usados na investigação).
- **Pendente**: conferir se existe algum consumidor downstream do CSV/grafo
  que assuma que `CAMPO_ORIGEM`/`VALOR_ORIGEM` estão **sempre** presentes
  para todo `intox:temInferencia` — a correção passa a omiti-los quando
  nenhum campo tiver conteúdo real, o que é o comportamento documentado,
  mas é uma mudança observável para quem consome a saída.
