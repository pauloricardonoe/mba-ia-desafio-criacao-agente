"""Execução da conversa: envia mensagens e responde confirmações.

É aqui que a Garantia 1 se fecha. O ADK pausa a execução quando uma tool exige
confirmação; este módulo traduz essa pausa para o contrato HTTP e devolve a
resposta do morador para dentro do agente que pediu a confirmação.

A costura da retomada é o `invocation_id`. Sem ele, a resposta inicia uma
invocação nova e a tool nunca executa — a falha silenciosa que o enunciado
aponta como a armadilha mais cara do desafio.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.adk import Runner
from google.genai import types

from aurora.agentes.tools import resolver_area_id
from aurora.dominio.confirmacoes import Confirmacao, RegistroConfirmacoes

NOME_DA_CONFIRMACAO = "adk_request_confirmation"


@dataclass(frozen=True)
class Resultado:
    resposta: str
    pendentes: list[Confirmacao]


def _texto_dos_eventos(eventos: list) -> str:
    """Último texto produzido pelos agentes, ignorando o eco do morador."""
    texto = ""
    for evento in eventos:
        if evento.author == "user" or not evento.content:
            continue
        if not evento.content.parts:
            continue
        for parte in evento.content.parts:
            if getattr(parte, "text", None):
                texto = parte.text
    return texto


class Execucao:
    """Conduz uma sessão: envia mensagens e responde confirmações."""

    def __init__(self, runner: Runner, registro: RegistroConfirmacoes) -> None:
        self.runner = runner
        self.registro = registro

    def _registrar_pendencias(self, session_id: str, eventos: list) -> None:
        """Anota no registro toda confirmação que a execução pediu.

        Os argumentos da tool original viajam dentro do evento de confirmação,
        em `originalFunctionCall`. É de lá que saem `acao` e `detalhes` — o
        contrato exige a área e a data em `detalhes`.
        """
        for evento in eventos:
            if not evento.long_running_tool_ids:
                continue
            for chamada in evento.get_function_calls():
                if chamada.name != NOME_DA_CONFIRMACAO:
                    continue
                original = (chamada.args or {}).get("originalFunctionCall", {})
                detalhes = dict(original.get("args") or {})
                if "area" in detalhes:
                    resolvida = resolver_area_id(str(detalhes["area"]))
                    if resolvida:
                        detalhes["area"] = resolvida
                self.registro.registrar(
                    id=chamada.id,
                    session_id=session_id,
                    invocation_id=evento.invocation_id,
                    acao=original.get("name") or "acao",
                    detalhes=detalhes,
                )

    async def enviar_mensagem(self, session_id: str, texto: str) -> Resultado:
        eventos = [
            evento
            async for evento in self.runner.run_async(
                user_id=_usuario(),
                session_id=session_id,
                new_message=types.Content(
                    role="user", parts=[types.Part(text=texto)]
                ),
            )
        ]
        self._registrar_pendencias(session_id, eventos)
        return Resultado(
            resposta=_texto_dos_eventos(eventos),
            pendentes=self.registro.pendentes(session_id),
        )

    async def responder_confirmacao(
        self, session_id: str, confirmacao_id: str, confirmado: bool
    ) -> Resultado | None:
        """Retoma a execução pausada. `None` quando o id não está pendente.

        O status é trocado antes de retomar: assim um reenvio da mesma resposta
        não encontra mais a pendência e cai no `409`.
        """
        pendencia = self.registro.responder(session_id, confirmacao_id, confirmado)
        if pendencia is None:
            return None

        resposta = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=confirmacao_id,
                        name=NOME_DA_CONFIRMACAO,
                        response={"confirmed": confirmado},
                    )
                )
            ],
        )

        eventos = [
            evento
            async for evento in self.runner.run_async(
                user_id=_usuario(),
                session_id=session_id,
                # Sem o invocation_id a retomada não reentra na invocação
                # pausada, e a tool nunca executa.
                invocation_id=pendencia.invocation_id,
                new_message=resposta,
            )
        ]
        self._registrar_pendencias(session_id, eventos)
        return Resultado(
            resposta=_texto_dos_eventos(eventos),
            pendentes=self.registro.pendentes(session_id),
        )


def _usuario() -> str:
    from aurora.config import USUARIO_SESSAO

    return USUARIO_SESSAO
