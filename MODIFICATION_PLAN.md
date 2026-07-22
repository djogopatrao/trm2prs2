# Plano de Modificação — Matching Case-Insensitive e Fuzzy em `excel_to_sparql.py`

> Documento de planejamento apenas. Nenhum código foi alterado. Todas as
> referências de linha abaixo são relativas ao arquivo anexado
> `excel_to_sparql.py` (1912 linhas) tal como avaliado.

## 1. Diagnóstico

O gerador produz cláusulas SPARQL onde a comparação de um termo digitado
pelo usuário (campo de agente/lista) contra os termos das `LISTAS` é feita
por **igualdade de string exata** (`IN (...)` ou `=`), sensível a maiúsculas/
minúsculas. Pior: existe uma **inconsistência já presente hoje** — em alguns
caminhos os termos das listas são normalizados para minúsculas antes de
entrarem na query, mas a variável comparada (o valor vindo do grafo) nunca é
normalizada. Isso significa que, mesmo hoje, comparações como
`?lista_termos_X = STR(?valor)` (linha 824) só funcionam **por acaso**,
quando o dado de origem já está em minúsculas.

Locais identificados onde a comparação ocorre:

| # | Método | Linha(s) | Padrão de comparação atual |
|---|--------|----------|------------------------------|
| 1 | `SparqlClauseBuilder._resolve_terms` | 1404-1411 | Caso multi-lista usa `_consolidate_lists` (lowercase); caso 1 lista **não** aplica `.lower()` — inconsistência-fonte |
| 2 | `filter_exists_list_in_value` | 729-755 (filtro em 753) | `FILTER ( ?_value_M IN ("t1","t2",…) )` |
| 3 | `filter_list_agente_origem` | 757-788 (filtro em 786-787) | `FILTER ( ?_valor_origem_M IN (...) )` |
| 4 | `filter_not_list` | 794-826 (filtro em 824) | `?lista_termos_X = STR(?_vN)` |
| 5 | `filter_list_inline` | 832-868 (filtro em 860) | `?_vN IN ("t1","t2",…)` |
| 6 | `regra_complexa_agente_x70` (Ramo B) | 893-982 (filtro em 974-975) | `FILTER( ?_valor_x70 IN (...) )` |
| 7 | `filtro_not_exists_agente` (fallback hard-coded) | 1073-1093 | `?agente_path_value IN (...)` (linhas 1085, 1090) |
| 8 | `_disjuncoes_padroes_irmas` | 1151-1177 (linhas 1166, 1175) | `?agente_path_value IN (...)` |
| 9 | `regra_volume_iii_cid` | 1295-1322 | Reusa (2); herda a correção |
| 10 | `_consolidate_lists` | 549-561 | Já normaliza para lowercase (linha 560) — referência de comportamento correto |

## 2. Especificidades do pyoxigraph relevantes ao plano

- `pyoxigraph` implementa SPARQL 1.1 puro — **não há mecanismo de função de
  extensão (UDF) registrável em Python**, ao contrário de RDFLib/Jena. Logo,
  Levenshtein não pode ser calculado nativamente na engine: qualquer
  "fuzzy match" precisa ser **pré-computado em Python** e embutido na query
  como alternativas literais (`IN`) ou como um padrão `REGEX`.
- `REGEX(texto, padrão, "i")` segue a sintaxe **XPath F&O**, suportada pelo
  oxigraph, sem *lookahead/lookbehind/backreferences*. O motor de regex do
  oxigraph (baseado no crate `regex` do Rust) é **NFA/DFA, não
  backtracking** — portanto **não há risco de ReDoS** por padrões com muitas
  alternâncias, mas o custo de avaliação ainda cresce com o tamanho do
  padrão e é pago **por linha/binding testado**, não há uso de índice.
- `LCASE()` e `STR()` são funções padrão SPARQL 1.1 suportadas. `LCASE`
  exige um *string literal*; por segurança, sempre envolver o valor com
  `STR(...)` antes (`LCASE(STR(?x))`) para tolerar literais tipados.
- `FILTER EXISTS` / `FILTER NOT EXISTS` com `IN` sobre uma lista de literais
  compila para um hash-lookup barato; `REGEX` é bem mais caro por avaliação
  (sem índice, sem hashing). Isso orienta a escolha de estratégia na seção 4.
- Não há cache de subconsultas entre as ~500 regras geradas — cada `CONSTRUCT`
  é executado isoladamente, então o custo de um padrão caro se multiplica
  pelo número de regras que o utilizarem.

## 3. Estratégia proposta

### 3.1 Case-insensitive (obrigatório, sempre ativo)

Padronizar **todas** as comparações terto-lista para o padrão:

```
LCASE(STR(?variavel)) IN ( "termo1_lower", "termo2_lower", … )
```
(ou, no caso de `filter_not_list`, `?lista_termos_X = LCASE(STR(?variavel))`).

Isso exige duas mudanças coordenadas:
1. Garantir que **todo** termo embutido na query já esteja em minúsculas
   (corrigindo a inconsistência do item 1 da tabela).
2. Envolver o **lado variável** da comparação com `LCASE(STR(...))` em
   **todos** os 8 pontos de filtro listados na tabela (itens 2–8).

### 3.2 Fuzzy opcional (até 1 erro: substituição, deleção, duplicação)

Como pyoxigraph não tem Levenshtein nativo, a tolerância a erro será
**pré-computada em Python por termo**, gerando um padrão `REGEX` ancorado
com alternâncias cobrindo:

- Exato: `termo`
- Substituição de 1 caractere por qualquer outro, posição a posição:
  `t[0:i] + "." + t[i+1:]` (usa `.` — 1 alternativa por posição, não 26)
- Deleção de 1 caractere, posição a posição:
  `t[0:i] + t[i+1:]`
- Duplicação de 1 caractere (a "duplicação" citada no pedido), posição a
  posição: `t[0:i+1] + t[i] + t[i+1:]`

Total de alternativas por termo ≈ `3n + 1` (n = tamanho do termo), sem
explosão combinatória de alfabeto — é o motivo de escolher `REGEX` em vez de
enumerar literalmente todas as substituições (que exigiria ~26 variantes por
posição só para trocas de caractere).

Padrão final por termo:
```
^(termo|t1.t3|.t2t3|t1t2.| t2t3|t1t3|t1t2 | t1t1t2t3|t1t2t2t3|t1t2t3t3)$
```
(exemplo ilustrativo para um termo de 3 caracteres `t1t2t3`).

A query final usa apenas **um** `FILTER(REGEX(LCASE(STR(?val)), "^(alt1|alt2|…|altN)$"))`
por lista de termos (concatenando os padrões de todos os termos da lista em
uma única alternância grande), preservando a interface atual de "uma
FILTER por campo".

**Este recurso deve ser opt-in por regra/lista**, não um default global —
alinhado à palavra "opcionalmente" do pedido. Proposta: um novo campo em
`Config` (`fuzzy_typo_tolerance: bool = False`) e/ou uma lista de nomes de
campos/listas elegíveis, mais um limiar mínimo de tamanho do termo
(`fuzzy_min_term_length: int = 5`) para não aplicar fuzzy em termos curtos
(alto risco de falso positivo — ver seção 5).

## 4. Alterações propostas, função a função

### 4.1 Novo: `Config` (linhas 47-93)
- Adicionar campos:
  - `fuzzy_typo_tolerance: bool = False`
  - `fuzzy_min_term_length: int = 5`
- Aditivo, com default desligado — não altera comportamento existente até
  ser explicitamente ativado.

### 4.2 Novos helpers de módulo (próximo a `_remove_source_tag`, linhas 357-369)
- `_escape_sparql_regex_literal(s: str) -> str`: escapa metacaracteres de
  regex XPath (`. ^ $ * + ? ( ) [ ] { } | \`) e, em seguida, escapa
  barras invertidas/aspas para embutir em literal SPARQL (`\` → `\\`,
  `"` → `\"`). **Atenção**: são dois níveis de escaping distintos — o
  primeiro para a semântica de regex, o segundo para a sintaxe de string
  SPARQL. Confundir a ordem é a fonte de erro mais provável desta mudança
  (ver riscos, seção 5).
- `_build_fuzzy_pattern(term: str) -> list[str]`: recebe um termo já em
  minúsculas e devolve a lista de variantes (exato + substituições +
  deleções + duplicações), cada uma já escapada por
  `_escape_sparql_regex_literal`.
- `_build_terms_regex(terms: list[str], fuzzy: bool) -> str`: monta o
  padrão `^(alt1|alt2|…)$` juntando, para cada termo, ou apenas o termo
  escapado (`fuzzy=False`) ou `_build_fuzzy_pattern(term)` (`fuzzy=True`).

### 4.3 `SparqlClauseBuilder._resolve_terms` (linhas 1404-1411)
- **Correção de bug pré-existente**: aplicar `.lower()` também no ramo de
  lista única (linha 1411), igualando ao comportamento de
  `_consolidate_lists` (linha 560). Sem isso, o fix de case-insensitive das
  seções seguintes fica incompleto para todo caminho que passa por uma
  única lista (a maioria dos casos de `filter_exists_list_in_value` e
  `filter_list_agente_origem`).

### 4.4 `filter_exists_list_in_value` (linhas 729-755)
- Linha 744: manter `values_str` a partir de `terms` (agora já lowercase
  via 4.3), OU delegar a `_build_terms_regex` se fuzzy estiver ativo para
  esta chamada.
- Linha 753: trocar
  `FILTER ( ?{v_prop} ... ?{v_val} IN ( {values_str}) ).`
  por, no modo case-insensitive puro:
  `FILTER ( LCASE(STR(?{v_val})) IN ( {values_str}) ).`
  e, no modo fuzzy:
  `FILTER ( REGEX(LCASE(STR(?{v_val})), "{pattern}") ).`
- Assinatura precisa aceitar um parâmetro `fuzzy: bool = False` (ou ler de
  `self._config`/atributo da instância) para decidir qual ramo gerar.

### 4.5 `filter_list_agente_origem` (linhas 757-788)
- Mesma alteração de 4.4, aplicada à `FILTER` das linhas 786-787
  (estrutura idêntica a `filter_exists_list_in_value`, mas com o
  casamento exposto no corpo do WHERE em vez de dentro de
  `FILTER EXISTS`).

### 4.6 `filter_not_list` (linhas 794-826)
- Linhas 807-814: já existe lowercasing manual — pode ser simplificado
  para sempre usar `_resolve_terms` (pós-4.3), eliminando a duplicação de
  lógica atualmente feita ali (não obrigatório, mas reduz risco de nova
  divergência futura).
- Linha 824: trocar
  `FILTER( ?{variable} != "" && ?{list_var_name} = STR( ?{variable} ) )`
  por
  `FILTER( ?{variable} != "" && ( ?{list_var_name} = LCASE(STR( ?{variable} )) ) )`
  (modo case-insensitive) ou, em modo fuzzy, trocar toda a `VALUES` +
  igualdade por `FILTER( ?{variable} != "" && REGEX(LCASE(STR(?{variable})), "{pattern}") )`,
  descartando a cláusula `VALUES` (que só faz sentido para igualdade
  exata) neste ramo.
- **Cuidado com cache**: `values_clause` (linhas 706-723) armazena o
  resultado em `self._declared_values[var_name]` **chaveado só pelo nome
  da variável**. Se o mesmo `var_name` puder ser usado ora em modo exato,
  ora fuzzy (dificilmente ocorre na prática, pois a decisão é por regra,
  não por variável dentro da mesma query), ainda assim é prudente incluir
  o modo (`exact`/`fuzzy`) na chave do cache para eliminar qualquer
  possibilidade de reaproveitar uma cláusula errada.

### 4.7 `filter_list_inline` (linhas 832-868)
- Linha 847: terms via `_resolve_terms` (já lowercase, 4.3).
- Linha 860: trocar `filters.append(f"?{v_val} IN {in_str}")` por
  `filters.append(f"LCASE(STR(?{v_val})) IN {in_str}")` (ou o equivalente
  `REGEX(...)` em modo fuzzy, substituindo totalmente a linha por uma
  chamada a `_build_terms_regex`).

### 4.8 `regra_complexa_agente_x70` — Ramo B (linhas 965-980)
- `terms` já vêm de `_consolidate_lists` (lowercase, linha 921) — falta
  só o lado variável.
- Linha 974-975: trocar
  `FILTER( ?{v_val} IN ( {values_str} ) )`
  por
  `FILTER( LCASE(STR(?{v_val})) IN ( {values_str} ) )`
  (fuzzy aqui é opcional/baixa prioridade — este ramo já é um caso muito
  específico e de baixo volume de termos; ver seção 5 sobre escopo
  recomendado de rollout).

### 4.9 `filtro_not_exists_agente` — fallback hard-coded (linhas 1073-1093)
- Linhas 1085 e 1090: envolver `?{var_value}` com `LCASE(STR(...))`,
  análogo aos itens anteriores. `terms1`/`terms2` já vêm lowercase de
  `_consolidate_lists` (linhas 1077-1083).

### 4.10 `_disjuncoes_padroes_irmas` (linhas 1151-1177)
- Linha 1166 (`padroes_irmas` tipo `"lista"`) e linha 1175 (tipo
  `"agente_tox"`): mesma alteração — envolver `?{var_value}` com
  `LCASE(STR(...))` antes do `IN`.

### 4.11 `regra_volume_iii_cid` (linhas 1295-1322)
- Nenhuma alteração direta necessária: reusa `filter_exists_list_in_value`
  (4.4), portanto herda a correção automaticamente. Único cuidado: a
  lista de substâncias (`substances`, vinda do parquet, linha 1310) hoje
  entra **sem** `.lower()` explícito — confirmar que passa pelo mesmo
  `_resolve_terms` corrigido (4.3) e não por um caminho paralelo.

## 5. Riscos de regressão

| Risco | Onde | Severidade | Mitigação proposta |
|---|---|---|---|
| Corrigir o bug de `_resolve_terms` (4.3) muda resultado de **toda** regra que hoje dependia (mesmo que "por acaso") da comparação sensível a caixa | Todos os itens 4.4–4.10 | **Alta** — é o núcleo da mudança | Rodar o pipeline completo antes/depois sobre a planilha real e comparar `sparql_rules.json`/saídas de teste (golden diff) regra a regra |
| Tornar filtros de **exclusão** (`filter_not_list`, `filtro_not_exists_agente`) case-insensitive faz com que **mais** registros passem a ser excluídos (match que antes falhava por causa da caixa agora "acerta") | 4.6, 4.9, 4.10 | Média-Alta | Validar especificamente as regras X89/X90 e D2/D4 (que dependem desses filtros) com casos de teste reais pós-mudança |
| Fuzzy em termos curtos (≤4 caracteres) gera falsos positivos frequentes (ex.: termo "sal" com 1 erro colide com muitas palavras reais) | 3.2, todos os `REGEX` | **Alta** se fuzzy for ligado sem guarda | Aplicar `fuzzy_min_term_length` (proposto em 4.1) e, inicialmente, habilitar fuzzy **apenas** nas listas indicadas pelo time de domínio, não globalmente |
| Fuzzy aplicado a filtros de **exclusão** pode **suprimir indevidamente** uma inferência correta (um termo genuíno que por acaso tem edição-1 para um termo da lista de exclusão) | 4.6, 4.9 (`filter_not_list`, `filtro_not_exists_agente`) | Média-Alta | Recomenda-se **não** aplicar fuzzy nos caminhos de exclusão na primeira fase — só nos caminhos de inclusão (`filter_exists_list_in_value`, `filter_list_agente_origem`, `filter_list_inline`) |
| Escaping duplo (regex → SPARQL string) incorreto quebra a query (erro de parse) ou, pior, faz o padrão coincidir com algo não pretendido silenciosamente | 4.2 (`_escape_sparql_regex_literal`) | Média | Testes unitários dedicados com termos contendo parênteses, ponto, barra, aspas (comuns em nomes de substâncias, ex. "Ácido acetilsalicílico (AAS)") |
| Cache de `values_clause` reaproveitando cláusula errada entre modos exato/fuzzy | 4.6 | Baixa (cenário raro) | Incluir o modo na chave do cache, como descrito em 4.6 |
| Novo campo em `Config` (dataclass) pode quebrar código externo que instancia `Config(...)` posicionalmente | 4.1 | Baixa | Usar `field(default=...)` com nome, nunca alterar ordem dos campos existentes |

## 6. Riscos de performance

| Risco | Detalhe | Mitigação proposta |
|---|---|---|
| `REGEX` é avaliado por *binding*, sem uso de índice, ao contrário de `IN` (hash lookup) | Cada `FILTER EXISTS`/`FILTER NOT EXISTS` que hoje usa `IN` varre as triplas do(s) predicado(s) candidato(s) e testa cada valor; trocar por `REGEX` multiplica o custo por avaliação, não pela cardinalidade do padrão em si (motor não é backtracking) | Reservar `REGEX`/fuzzy para os campos onde o time de domínio confirmar necessidade; manter `IN` (com `LCASE`) para o caso não-fuzzy, que é praticamente sem custo adicional |
| Tamanho do padrão cresce ~`3n` alternativas por termo, multiplicado pelo nº de termos da lista (algumas listas consolidadas somam dezenas a centenas de termos, ex. `_consolidate_lists` usado no X70 combinando lista_23+lista_24) | Padrões `REGEX` de milhares de caracteres são plausíveis para as listas maiores, aumentando tempo de parse/compilação da query (não catastrófico, mas mensurável) e reduzindo legibilidade/depuração das ~500 queries geradas | Medir tempo de execução em uma amostra representativa (a maior lista existente) antes de generalizar; considerar um teto de termos por lista acima do qual fuzzy é desabilitado automaticamente |
| Efeito multiplicativo: custo por regra × ~500 regras geradas no pipeline completo | Mesmo um aumento pequeno por regra pode somar tempo relevante no lote inteiro | Rodar benchmark do pipeline completo (`main()`) antes/depois da mudança, comparando tempo total de execução das queries (não apenas geração, mas execução contra o grafo real) |
| `LCASE(STR(...))` isoladamente (sem fuzzy) tem custo desprezível | É apenas uma função escalar por linha comparada, sem mudança na estratégia de junção | Nenhuma mitigação necessária — pode ser adotado com confiança em toda a base |

## 7. Escopo de rollout recomendado

1. **Fase 1 (baixo risco)**: aplicar somente a correção de case-insensitive
   (`LCASE(STR(...))` + fix do bug em `_resolve_terms`) em todos os 8 pontos
   listados na seção 4, com validação golden-diff completa antes de seguir.
2. **Fase 2 (opt-in, escopo restrito)**: introduzir a infraestrutura de
   fuzzy (`Config.fuzzy_typo_tolerance`, helpers de regex) e habilitá-la
   **apenas** nos caminhos de inclusão (`filter_exists_list_in_value`,
   `filter_list_agente_origem`, `filter_list_inline`) e apenas para
   listas/campos explicitamente indicados, com o guard de tamanho mínimo de
   termo.
3. **Fase 3 (avaliação)**: medir impacto em precisão/recall das inferências
   (comparando CIDs inferidos antes/depois em uma amostra rotulada) antes de
   estender fuzzy aos caminhos de exclusão ou de generalizar para todas as
   listas.
