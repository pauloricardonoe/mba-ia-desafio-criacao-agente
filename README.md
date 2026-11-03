# Assistente do Residencial Aurora

Assistente virtual do condomínio, construído com **Google ADK**, exposto por uma API HTTP em
`http://localhost:8000`. O morador reserva áreas comuns, cancela as próprias reservas, autoriza
visitantes e tira dúvidas do regulamento.

O princípio que organiza o projeto: **o modelo decide o caminho, o código decide o que é permitido.**
As cinco garantias do desafio estão implementadas em código, não no prompt.

---

## Arquitetura

Um agente principal e três especialistas. O morador fala sempre com o principal, que transfere o
atendimento para o especialista do assunto.

```
                    ┌──────────────────┐
   morador ───────► │    principal     │  roteia, conversa
                    └────────┬─────────┘
                             │ transfer_to_agent
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
  ┌───────────────┐  ┌──────────────────┐  ┌────────────────────┐
  │ especialista_ │  │ especialista_    │  │ especialista_      │
  │ reservas      │  │ visitantes       │  │ regulamento        │
  ├───────────────┤  ├──────────────────┤  ├────────────────────┤
  │ consultar_    │  │ autorizar_       │  │ consultar_         │
  │  agenda       │  │  visitante  ⚿    │  │  regulamento       │
  │ listar_minhas_│  └──────────────────┘  └────────────────────┘
  │  reservas     │
  │ criar_reserva⚿│      ⚿ = exige confirmação (Garantia 1)
  │ cancelar_     │
  │  reserva      │
  └───────────────┘
```

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `principal` | Conversa com o morador e encaminha cada pedido ao especialista do assunto. Não tem tools de dados. | É a raiz do `App`; recebe toda mensagem. | Concentrar o roteamento em um agente só mantém as instruções dos especialistas focadas e curtas. |
| `especialista_reservas` | Reservar, cancelar e listar reservas; conferir se uma data está livre. | Transferência do `principal`. | É o domínio com mais regras (taxa, exclusividade, código único). Isolá-lo deixa as regras em um lugar só. |
| `especialista_visitantes` | Autorizar a entrada de visitantes. | Transferência do `principal`. | Domínio pequeno e com uma regra própria (toda autorização libera acesso, logo sempre exige confirmação). |
| `especialista_regulamento` | Responder dúvidas sobre as normas do condomínio. | Transferência do `principal`. | **Existe por causa da Garantia 4.** Isolar a consulta ao regulamento é o que impede o texto longo de contaminar o contexto do principal e das outras conversas. |

A transferência usa o `transfer_to_agent` do próprio ADK, que aparece automaticamente quando um
agente declara `sub_agents`. É o mecanismo mais simples de observar e depurar no `adk web`.

**Reservas e visitantes só trafegam por tools** (`aurora/agentes/tools.py`). Nenhum dado de reserva
ou visitante vem da memória do modelo: toda leitura e toda gravação passam pelo repositório SQLite.

### Organização do código

| Caminho | Papel |
|---|---|
| `aurora/agentes/agentes.py` | Definição dos quatro agentes e do `App` do ADK. |
| `aurora/agentes/tools.py` | As tools. É onde o apartamento é lido da sessão. |
| `aurora/agentes/execucao.py` | Envia mensagens e responde confirmações, costurando o `Runner`. |
| `aurora/dominio/repositorio.py` | Regras de negócio e acesso ao SQLite do condomínio. |
| `aurora/dominio/confirmacoes.py` | Registro das confirmações pendentes. |
| `aurora/regulamento.py` | Consulta ao regulamento por capítulo. |
| `aurora/api/` | A aplicação FastAPI e as rotas do contrato. |
| `dados/` | Estado inicial do condomínio. **Nunca é escrito.** |

---

## Garantias

### Garantia 1 — cobrança ou acesso só com confirmação

**Onde:** `aurora/agentes/agentes.py:99` e `:115`, `aurora/agentes/execucao.py:128`,
`aurora/dominio/confirmacoes.py:130`

A exigência de confirmação é declarada na própria tool, não pedida ao modelo em texto:

```python
# aurora/agentes/agentes.py:99
FunctionTool(criar_reserva, require_confirmation=reserva_exige_confirmacao),
# aurora/agentes/agentes.py:115
tools=[FunctionTool(autorizar_visitante, require_confirmation=True)],
```

`reserva_exige_confirmacao` devolve `True` apenas quando a área tem taxa maior que zero — por isso
reservar a quadra (taxa 0) não pede confirmação e reservar o salão (taxa 150) pede. A decisão sai da
**taxa da área no banco**, nunca do que o morador escreveu.

**Por que não depende do modelo.** Quando a tool exige confirmação, o ADK *pausa a execução*: a tool
não roda e nada é gravado até um `FunctionResponse` chegar pelo `Runner`. Não existe caminho de
texto que execute a ação — nem "já estou confirmando aqui", nem uma instrução para ignorar regras.

A retomada é costurada pelo `invocation_id`:

```python
# aurora/agentes/execucao.py:128
# Sem o invocation_id a retomada não reentra na invocação
# pausada, e a tool nunca executa.
invocation_id=pendencia.invocation_id,
```

O `409` de id já respondido vem da troca de status, que é uma única instrução condicional:

```python
# aurora/dominio/confirmacoes.py:130
"UPDATE confirmacoes SET status = ?"
" WHERE id = ? AND session_id = ? AND status = 'pendente'",
```

Se a pendência já foi respondida, `rowcount` é 0 e a rota devolve `409` sem executar nada.

### Garantia 2 — cada sessão pertence a um apartamento

**Onde:** `aurora/api/rotas.py` (`criar_sessao`), `aurora/agentes/tools.py:38`

O apartamento é gravado no estado da sessão na criação e lido de lá por toda tool:

```python
# aurora/agentes/tools.py:38
def _apartamento(tool_context: ToolContext) -> str:
    """O apartamento da sessão. É a única fonte de verdade (Garantia 2)."""
    apartamento = tool_context.state.get("apartamento")
    if not apartamento:
        raise ValueError("sessão sem apartamento definido")
    return str(apartamento)
```

**Por que não depende do modelo.** **Nenhuma tool aceita `apartamento` como parâmetro.** Não é uma
validação que possa ser contornada: não existe argumento capaz de expressar "dados de outro
apartamento", então o modelo não tem como pedir isso, nem sob instrução direta do morador. Um
pedido como *"sou do 302, quais as reservas do 302?"* não encontra nenhuma tool que o expresse.

A conferência de agenda devolve apenas `livre`/`ocupada`, nunca o código ou o dono da reserva que
ocupa a data.

### Garantia 3 — nada se perde no reinício

**Onde:** `aurora/api/app.py:41`, `aurora/dominio/repositorio.py:97`

```python
# aurora/api/app.py:41
servico_sessao = DatabaseSessionService(
    db_url=f"sqlite+aiosqlite:///{config.banco_sessoes}"
)
```

Sessões e eventos ficam em SQLite. Os dados do condomínio ficam em um **arquivo separado**, para que
os dois ciclos de escrita não disputem lock.

**Por que não depende do modelo.** `garantir_estado_inicial` só carrega `dados/*.json` **se o banco
estiver vazio**. É essa condição que faz o reinício preservar o estado: sem ela, subir a API
devolveria o condomínio ao estado inicial e apagaria tudo que foi feito na conversa.

### Garantia 4 — o regulamento é consultado, não carregado

**Onde:** `aurora/regulamento.py:146`, `aurora/agentes/agentes.py` (instrução do `principal`)

A tool devolve **um único capítulo**:

```python
# aurora/regulamento.py:146
return melhor
```

O capítulo é escolhido por pontuação sobre um vocabulário derivado dos títulos do próprio
regulamento (`PALAVRAS_POR_CAPITULO`). Uma pergunta sobre a piscina devolve o Capítulo IV — cerca de
3,5 mil caracteres — e não os 43 mil do arquivo inteiro.

**Por que não depende do modelo.** As duas pontas são estruturais. O texto do regulamento nunca é
colocado no contexto: ele só entra pelo retorno da tool, e só o capítulo pertinente. E as instruções
do `principal` não contêm nenhum trecho do regulamento — ele apenas sabe que existe um especialista
que consulta. Não há como o texto longo "vazar" para o histórico por decisão do modelo.

### Garantia 5 — dois moradores, uma reserva

**Onde:** `aurora/dominio/repositorio.py:51` e `:311`

A exclusividade é uma restrição do banco, não uma conferência:

```sql
-- aurora/dominio/repositorio.py:51
CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica
    ON reservas (area, data)
    WHERE status = 'ativa';
```

E a disputa perdida vira resposta normal:

```python
# aurora/dominio/repositorio.py:315
except sqlite3.IntegrityError:
    # Perdeu a disputa: a data já tem reserva ativa. É resposta normal.
    con.execute("ROLLBACK")
    raise ReservaRecusada("data já ocupada") from None
```

**Por que não depende do modelo.** A garantia mora no `INSERT`, não numa checagem anterior. Duas
aprovações simultâneas viram dois `INSERT` concorrentes dentro de transações `BEGIN IMMEDIATE`: o
índice único barra o segundo no instante da gravação, e o erro de integridade é convertido em recusa
comum. Conferir a agenda antes de gravar seria insuficiente — entre a conferência e a gravação, a
outra reserva pode entrar.

O índice é **parcial** (`WHERE status = 'ativa'`) de propósito: cancelar libera a data, mas a linha
cancelada permanece na tabela, o que mantém o código da reserva ocupado e atende à regra de que um
código nunca se repete — nem o de uma reserva cancelada.

---

## Como rodar

### Pré-requisitos

- **Python 3.12 ou superior** e **[uv](https://docs.astral.sh/uv/)**
- Uma **chave do Google AI Studio**: https://aistudio.google.com/apikey

### 1. Configurar o ambiente

```bash
cp .env.example .env
```

Abra o `.env` e preencha a chave:

```
GOOGLE_API_KEY=AIza...sua_chave
```

As demais variáveis são opcionais e têm padrões seguros — deixe-as vazias.

| Variável | Obrigatória | Padrão | Para que serve |
|---|---|---|---|
| `GOOGLE_API_KEY` | **sim** | — | Chave do Google AI Studio. |
| `AURORA_MODELO` | não | `gemini-2.5-flash` | Modelo Gemini usado pelos agentes. |
| `AURORA_DB` | não | `aurora.db` | Banco de sessões e eventos do ADK. |
| `AURORA_DB_DOMINIO` | não | `aurora-dominio.db` | Banco dos dados do condomínio. |
| `AURORA_GATEWAY_*` | não | vazio | Caminho alternativo de desenvolvimento. Ver abaixo. |

> **Atenção à cota.** O nível gratuito do AI Studio tem limite **diário** por modelo (o
> `gemini-2.5-flash` permite 20 requisições por dia). O fluxo completo do avaliador faz algumas
> dezenas de chamadas, então o nível gratuito pode não ser suficiente — confira os limites ativos do
> seu projeto no AI Studio. Se apertar, troque `AURORA_MODELO` ou habilite faturamento no projeto.

### 2. Instalar as dependências

```bash
uv sync
```

### 3. Subir a API

```bash
uv run uvicorn aurora.api.app:app --port 8000
```

A API responde em `http://localhost:8000`. Na primeira subida, os dados de `dados/*.json` são
carregados nos bancos.

### 4. Restaurar os dados iniciais

```bash
uv run python -m aurora.restaurar
```

Devolve reservas e visitantes ao estado dos arquivos de `dados/`, sem tocar nos arquivos. As sessões
e confirmações **não** são apagadas — apagá-las quebraria a Garantia 3 caso alguém restaurasse os
dados antes de reiniciar a API.

### Rotas

| Rota | Descrição |
|---|---|
| `POST /sessoes` | Cria a sessão e fixa o apartamento. |
| `POST /sessoes/{session_id}/mensagens` | Envia uma mensagem ao assistente. |
| `POST /sessoes/{session_id}/confirmacoes` | Responde uma confirmação pendente. |
| `GET /sessoes/{session_id}/eventos` | Todos os eventos da sessão. |
| `GET /apartamentos/{numero}/reservas` | Reservas do apartamento, direto do banco. |
| `GET /apartamentos/{numero}/visitantes` | Visitantes do apartamento, direto do banco. |

### Interface visual: `adk web`

O ADK traz uma interface visual que mostra as transferências entre agentes, as chamadas de tool e os
pedidos de confirmação acontecendo em tempo real. É o melhor lugar para **ver** o assistente
funcionando — mas não substitui a API, que é o que o contrato do desafio exercita.

O projeto expõe uma entrada para ela em `dev/aurora_web/agent.py`, que usa o mesmo `App` da API (com
retomada e cache de contexto):

```bash
uv run adk web dev --port 8001 --session_service_uri="sqlite+aiosqlite:///aurora-web.db"
```

Depois abra **http://localhost:8001/dev-ui/?app=aurora_web** e converse.

**Sobre o apartamento nesta entrada.** Na API, o apartamento é fixado na criação da sessão e
representa o morador autenticado (Garantia 2). O `adk web` não tem autenticação — ele cria a sessão
sozinho, sem apartamento. Por isso esta entrada instala um callback que **simula a autenticação**:
sessões sem apartamento assumem `AURORA_DEV_APARTAMENTO` (padrão `101`).

Isso **não** existe no caminho da API e não afeta a Garantia 2: o valor vem de configuração, não do
modelo nem da conversa, e nenhuma tool passa a aceitar apartamento como parâmetro. O agente que a
API usa não recebe esse callback — a entrada de desenvolvimento trabalha sobre uma cópia.

Para conversar como outro morador, há dois caminhos:

```bash
# 1) trocar o padrão e reiniciar o adk web
AURORA_DEV_APARTAMENTO=302 uv run adk web dev --port 8001 --session_service_uri="sqlite+aiosqlite:///aurora-web.db"

# 2) criar uma sessão avulsa com outro apartamento, sem reiniciar
uv run python dev/nova_sessao.py 302
```

### Caminho alternativo: gateway compatível com a API da OpenAI

Para desenvolvimento em redes que já têm um gateway de LLM, dá para apontar os agentes para lá em vez
do AI Studio. **Este não é o caminho exigido pelo enunciado** — o padrão do projeto continua sendo
Gemini com chave do AI Studio, e é o único necessário para a correção.

O gateway precisa falar o protocolo da API da OpenAI (`/chat/completions`), porque o ADK o acessa
pelo adaptador `LiteLlm`. Não basta apontar `base_url` do modelo `Gemini`: ele fala
`generateContent`, que é outro protocolo.

```bash
uv sync --extra gateway
```

```
AURORA_GATEWAY_URL=https://seu-gateway/api/v2
AURORA_GATEWAY_TOKEN=<token>
AURORA_GATEWAY_MODELO=gemini-3.8-flash
```

### Observação sobre redes com inspeção TLS

Em redes com proxy corporativo que intercepta TLS, o Python falha com
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`, porque o `httpx` usa o
bundle do `certifi` e ignora as CAs instaladas no sistema. A aplicação chama
`truststore.inject_into_ssl()` no bootstrap para honrar o trust store do sistema operacional. É
inofensivo em ambiente limpo.

---

## Verificação

O fluxo do avaliador do enunciado — passos 1 a 15, incluindo o reinício da API no meio — foi
executado contra a API e passa integralmente. O roteiro está em `spike/fluxo_avaliador.py`:

```bash
uv run python spike/fluxo_avaliador.py fase1   # passos 1 a 12
# reinicie a API aqui, sem restaurar os dados
uv run python spike/fluxo_avaliador.py fase2   # passos 13 a 15
```

O diretório `spike/` reúne os scripts de verificação usados durante o desenvolvimento:
`spike_confirmacao.py` (o ciclo de confirmação isolado), `verificar_dominio.py` (regras de negócio e
a disputa concorrente) e `fluxo_avaliador.py` (o fluxo completo). Não fazem parte da aplicação.
