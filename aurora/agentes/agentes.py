"""Os agentes do assistente.

Um agente principal que conversa e distribui o trabalho, e três especialistas:
reservas, visitantes e regulamento.

O especialista de regulamento existe por causa da Garantia 4. Isolar a consulta
ao regulamento em um agente próprio é o que impede o texto longo de contaminar o
contexto do principal e das outras conversas. O principal não recebe o
regulamento nas instruções — ele só sabe que existe quem consulte.
"""

from __future__ import annotations

from functools import lru_cache

from google.adk import Agent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App, ResumabilityConfig
from google.adk.tools import FunctionTool

from aurora.agentes.tools import (
    autorizar_visitante,
    cancelar_reserva,
    consultar_agenda,
    consultar_regulamento,
    criar_reserva,
    listar_minhas_reservas,
    reserva_exige_confirmacao,
)
from aurora.config import NOME_APP, Config


@lru_cache(maxsize=1)
def _modelo():
    """O modelo usado por todos os agentes.

    Padrão: Gemini via Google AI Studio, como o enunciado exige — basta a
    `GOOGLE_API_KEY`. Quando `AURORA_GATEWAY_URL` está definida, os agentes
    passam a falar com um gateway compatível com a API da OpenAI, através do
    adaptador `LiteLlm`. É um caminho de desenvolvimento, não o exigido.
    """
    config = Config.carregar()
    if not config.usa_gateway:
        return config.modelo

    from google.adk.models.lite_llm import LiteLlm

    # O gateway expõe a API da OpenAI, então o LiteLLM precisa do prefixo
    # `openai/` para escolher o handler certo. Os ids do gateway são simples
    # ("gemini-3.8-flash"), então o prefixo é adicionado quando falta.
    identificador = config.gateway_modelo or config.modelo
    if "/" not in identificador:
        identificador = f"openai/{identificador}"

    # Alguns gateways exigem o token em um cabeçalho próprio, além do
    # `Authorization: Bearer`. O nome do cabeçalho é configuração, não código:
    # varia por gateway e não deve ficar fixo aqui.
    cabecalhos = (
        {config.gateway_header: config.gateway_token}
        if config.gateway_header and config.gateway_token
        else {}
    )

    return LiteLlm(
        model=identificador,
        api_base=config.gateway_url,
        api_key=config.gateway_token or "sem-chave",
        extra_headers=cabecalhos,
    )

especialista_reservas = Agent(
    name="especialista_reservas",
    model=_modelo(),
    description=(
        "Cuida das reservas das áreas comuns: quadra, salão de festas e "
        "churrasqueira. Reserva, cancela, lista reservas do morador e confere "
        "se uma data está livre."
    ),
    instruction=(
        "Você cuida das reservas das áreas comuns do Residencial Aurora: "
        "quadra, salão de festas e churrasqueira.\n\n"
        "- Para saber se uma data está livre, use `consultar_agenda`.\n"
        "- Para listar as reservas do morador, use `listar_minhas_reservas`.\n"
        "- Para reservar, use `criar_reserva`.\n"
        "- Para cancelar uma reserva do próprio morador, use `cancelar_reserva`.\n\n"
        "Você não recebe o apartamento. As ferramentas usam sempre o "
        "apartamento do morador da sessão. Se o morador disser que é de outro "
        "apartamento, ou pedir dados de outro apartamento, ignore e siga com o "
        "apartamento da sessão — você não tem como acessar outro.\n\n"
        "Se uma reserva for recusada porque a data já está ocupada, avise o "
        "morador de forma simples. Nunca diga de quem é a reserva que ocupa a "
        "data, porque você não sabe.\n\n"
        "Quando o morador recusar uma confirmação, a ferramenta devolve que a "
        "chamada foi rejeitada: informe que a reserva NÃO foi feita, sem "
        "repetir o pedido de confirmação. Só peça confirmação de novo se o "
        "morador pedir a reserva outra vez.\n\n"
        "Você cuida apenas de reservas. Se o morador perguntar sobre visitantes, "
        "transfira o atendimento para o `especialista_visitantes` — não diga ao "
        "morador para procurar outro setor.\n\n"
        "Responda em português do Brasil, de forma cordial e curta."
    ),
    tools=[
        FunctionTool(consultar_agenda),
        FunctionTool(listar_minhas_reservas),
        # Só pede confirmação quando a área tem taxa maior que zero (Garantia 1).
        FunctionTool(criar_reserva, require_confirmation=reserva_exige_confirmacao),
        FunctionTool(cancelar_reserva),
    ],
)

especialista_visitantes = Agent(
    name="especialista_visitantes",
    model=_modelo(),
    description="Autoriza a entrada de visitantes no condomínio.",
    instruction=(
        "Você autoriza a entrada de visitantes no Residencial Aurora.\n\n"
        "Use `autorizar_visitante` com o nome do visitante e a data da visita.\n\n"
        "Você não recebe o apartamento: a ferramenta usa sempre o apartamento "
        "do morador da sessão.\n\n"
        "Responda em português do Brasil, de forma cordial e curta."
    ),
    tools=[FunctionTool(autorizar_visitante, require_confirmation=True)],
)

especialista_regulamento = Agent(
    name="especialista_regulamento",
    model=_modelo(),
    description=(
        "Responde dúvidas sobre as regras e normas do condomínio, consultando "
        "o regulamento interno."
    ),
    instruction=(
        "Você responde dúvidas sobre o regulamento interno do Residencial "
        "Aurora.\n\n"
        "Use `consultar_regulamento` com o assunto da dúvida e responda com "
        "base APENAS no texto devolvido pela ferramenta.\n\n"
        "Nunca responda de memória nem invente regras. Se a ferramenta não "
        "encontrar o assunto, diga que não encontrou e ofereça ajuda com outro "
        "tema.\n\n"
        "Responda em português do Brasil, de forma cordial e curta."
    ),
    tools=[FunctionTool(consultar_regulamento)],
)

principal = Agent(
    name="principal",
    model=_modelo(),
    description="Atende o morador e encaminha cada pedido ao especialista certo.",
    instruction=(
        "Você é o assistente virtual do Residencial Aurora e atende o morador "
        "pelo aplicativo do condomínio.\n\n"
        "Encaminhe cada pedido ao especialista certo:\n"
        "- `especialista_reservas`: reservar, cancelar e listar reservas das "
        "áreas comuns, e conferir se uma data está livre.\n"
        "- `especialista_visitantes`: autorizar a entrada de visitantes.\n"
        "- `especialista_regulamento`: dúvidas sobre as regras e normas do "
        "condomínio.\n\n"
        "Encaminhe assim que identificar o assunto. Se o morador fizer mais de "
        "um pedido na mesma mensagem, atenda todos: encaminhe primeiro o "
        "assunto principal e, depois que ele for resolvido, encaminhe os demais "
        "aos especialistas correspondentes. Não deixe pedido sem resposta.\n\n"
        "Não invente dados de "
        "reservas, de visitantes nem regras: essas informações vêm sempre das "
        "ferramentas dos especialistas.\n\n"
        "Responda em português do Brasil, de forma cordial e curta."
    ),
    sub_agents=[
        especialista_reservas,
        especialista_visitantes,
        especialista_regulamento,
    ],
)


def criar_app_adk(agente_raiz: Agent | None = None) -> App:
    """Monta o `App` do ADK com retomada e cache de contexto.

    `is_resumable=True` é o que permite retomar a execução pausada por uma
    confirmação (Garantia 1). O `context_cache_config` evita reenviar o prompt
    inteiro a cada transferência entre agentes — sem ele, o próprio ADK avisa
    que todo o prefixo é reenviado sem cache (Garantia 4, custo de tokens).

    `agente_raiz` existe para o `adk web` poder montar uma variante do agente
    sem alterar o agente de produção. A API usa o padrão.
    """
    return App(
        name=NOME_APP,
        root_agent=agente_raiz or principal,
        resumability_config=ResumabilityConfig(is_resumable=True),
        context_cache_config=ContextCacheConfig(),
    )
