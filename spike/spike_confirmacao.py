"""Spike de risco: provar o ciclo de confirmação do ADK com sessão persistida.

Este arquivo é descartável. Ele existe só para responder, com evidência, as
perguntas da Tarefa 1 do change `assistente-residencial-aurora`:

  1.4 - capturar o id da confirmação e o invocation_id
  1.5 - responder e ver a tool executar
  1.6 - reiniciar o processo e ainda conseguir aprovar a pendência
  1.7 - a retomada chega ao especialista que pediu, não ao principal

Cada subcomando roda em um processo separado, então `pedir` seguido de
`aprovar` já é, por construção, o teste de reinício.

Uso:
    uv run python spike/spike_confirmacao.py pedir "Reserve o salão para 2030-04-20"
    uv run python spike/spike_confirmacao.py aprovar <session_id> <conf_id> <invocation_id>
    uv run python spike/spike_confirmacao.py negar   <session_id> <conf_id> <invocation_id>
    uv run python spike/spike_confirmacao.py eventos <session_id>
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import truststore

# Antes de qualquer contexto TLS: usa o trust store do sistema operacional,
# para funcionar em redes com inspeção TLS (proxy corporativo).
truststore.inject_into_ssl()

from dotenv import load_dotenv

load_dotenv()

from google.adk import Agent, Runner  # noqa: E402
from google.adk.apps import App, ResumabilityConfig  # noqa: E402
from google.adk.sessions import DatabaseSessionService  # noqa: E402
from google.adk.tools import FunctionTool, ToolContext  # noqa: E402
from google.genai import types  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "spike.db"
APP_NAME = "spike_aurora"
USER_ID = "morador-teste"
MODELO = os.getenv("AURORA_MODELO", "gemini-2.5-flash")


# --------------------------------------------------------------------------
# A tool que exige confirmação. Ela grava numa tabela própria para que darmos
# prova de que executou (ou não) — olhar o texto da resposta não basta.
# --------------------------------------------------------------------------


def _registrar_execucao(marcador: str) -> None:
    con = sqlite3.connect(BANCO)
    con.execute("CREATE TABLE IF NOT EXISTS execucoes (marcador TEXT)")
    con.execute("INSERT INTO execucoes VALUES (?)", (marcador,))
    con.commit()
    con.close()


def _execucoes() -> list[str]:
    if not BANCO.exists():
        return []
    con = sqlite3.connect(BANCO)
    try:
        return [r[0] for r in con.execute("SELECT marcador FROM execucoes")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def reservar_salao(data: str, tool_context: ToolContext) -> dict:
    """Reserva o salão de festas para a data informada (formato AAAA-MM-DD).

    Args:
        data: A data da reserva, no formato AAAA-MM-DD.
    """
    _registrar_execucao(f"reserva:{data}")
    return {"status": "reservado", "area": "salao-de-festas", "data": data}


# --------------------------------------------------------------------------
# Topologia: principal transfere para o especialista, que é quem tem a tool.
# É exatamente o caminho arriscado da Tarefa 1.7.
# --------------------------------------------------------------------------


especialista_reservas = Agent(
    name="especialista_reservas",
    model=MODELO,
    description="Cuida de reservas das áreas comuns do condomínio.",
    instruction=(
        "Você cuida de reservas das áreas comuns. Use a tool `reservar_salao` "
        "quando o morador pedir para reservar o salão de festas. "
        "Não invente dados. Responda em português, de forma curta."
    ),
    tools=[FunctionTool(reservar_salao, require_confirmation=True)],
)

principal = Agent(
    name="principal",
    model=MODELO,
    description="Atende o morador e encaminha pedidos de reserva.",
    instruction=(
        "Você é o assistente do Residencial Aurora. Encaminhe pedidos de "
        "reserva para o especialista_reservas. Responda em português, curto."
    ),
    sub_agents=[especialista_reservas],
)

app = App(
    name=APP_NAME,
    root_agent=principal,
    resumability_config=ResumabilityConfig(is_resumable=True),
)


def _montar():
    servico = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{BANCO}")
    runner = Runner(app=app, session_service=servico)
    return servico, runner


def _resumo_evento(evento) -> str:
    """Uma linha legível por evento, para inspeção manual."""
    partes = []
    if evento.author:
        partes.append(f"author={evento.author}")
    if evento.long_running_tool_ids:
        partes.append(f"LONGO={sorted(evento.long_running_tool_ids)}")
    for fc in evento.get_function_calls():
        partes.append(f"call:{fc.name}")
    for fr in evento.get_function_responses():
        partes.append(f"resp:{fr.name}={dict(fr.response or {})}")
    texto = ""
    if evento.content and evento.content.parts:
        texto = "".join(
            p.text for p in evento.content.parts if getattr(p, "text", None)
        )
    if texto:
        partes.append(f"texto={texto[:80]!r}")
    return f"  [{evento.invocation_id[:8] if evento.invocation_id else '-'}] " + " ".join(partes)


# --------------------------------------------------------------------------
# Subcomandos
# --------------------------------------------------------------------------


async def pedir(texto: str) -> None:
    """Cria a sessão, envia a mensagem e reporta a pendência, se houver."""
    servico, runner = _montar()
    sessao = await servico.create_session(
        app_name=APP_NAME, user_id=USER_ID, state={"apartamento": "101"}
    )

    antes = len(_execucoes())
    pendencia = None

    async for evento in runner.run_async(
        user_id=USER_ID,
        session_id=sessao.id,
        new_message=types.Content(role="user", parts=[types.Part(text=texto)]),
    ):
        print(_resumo_evento(evento))
        if evento.long_running_tool_ids:
            pendencia = (list(evento.long_running_tool_ids)[0], evento.invocation_id)

    depois = len(_execucoes())

    print()
    print(f"session_id={sessao.id}")
    if pendencia:
        conf_id, inv_id = pendencia
        print(f"confirmacao_id={conf_id}")
        print(f"invocation_id={inv_id}")
        print(f"tool_executou={'SIM' if depois > antes else 'NAO (correto)'}")
    else:
        print("SEM PENDENCIA")
        print(f"tool_executou={'SIM' if depois > antes else 'NAO'}")


async def responder(session_id: str, conf_id: str, invocation_id: str, confirmado: bool) -> None:
    """Retoma a execução pausada com a resposta do morador."""
    servico, runner = _montar()

    sessao = await servico.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if sessao is None:
        print("ERRO: sessao nao encontrada")
        sys.exit(1)

    antes = len(_execucoes())

    resposta = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=conf_id,
                    name="adk_request_confirmation",
                    response={"confirmed": confirmado},
                )
            )
        ],
    )

    async for evento in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        invocation_id=invocation_id,
        new_message=resposta,
    ):
        print(_resumo_evento(evento))

    depois = len(_execucoes())
    print()
    if confirmado:
        print(f"tool_executou={'SIM (correto)' if depois > antes else 'NAO (FALHOU)'}")
    else:
        print(f"tool_executou={'SIM (FALHOU)' if depois > antes else 'NAO (correto)'}")


async def eventos(session_id: str) -> None:
    servico, _ = _montar()
    sessao = await servico.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if sessao is None:
        print("ERRO: sessao nao encontrada")
        sys.exit(1)
    print(f"total de eventos: {len(sessao.events)}")
    for evento in sessao.events:
        print(_resumo_evento(evento))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    comando = sys.argv[1]
    if comando == "pedir":
        asyncio.run(pedir(sys.argv[2]))
    elif comando == "aprovar":
        asyncio.run(responder(sys.argv[2], sys.argv[3], sys.argv[4], True))
    elif comando == "negar":
        asyncio.run(responder(sys.argv[2], sys.argv[3], sys.argv[4], False))
    elif comando == "eventos":
        asyncio.run(eventos(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
