"""Rotas do contrato HTTP.

As rotas de verificação leem os dados do condomínio direto, sem passar pelo
modelo — é onde o avaliador confere os efeitos de cada conversa.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aurora.agentes.execucao import Resultado
from aurora.config import NOME_APP, USUARIO_SESSAO

router = APIRouter()


# -- modelos do contrato ---------------------------------------------------


class CriarSessao(BaseModel):
    apartamento: str


class SessaoCriada(BaseModel):
    session_id: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


class ConfirmacaoPendente(BaseModel):
    id: str
    acao: str
    detalhes: dict


class RespostaConversa(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[ConfirmacaoPendente]


class ReservaSaida(BaseModel):
    codigo: str
    area: str
    data: str


class VisitanteSaida(BaseModel):
    nome: str
    data: str


# -- apoio -----------------------------------------------------------------


async def _exigir_sessao(session_id: str, request: Request):
    """404 quando a sessão não existe. Vale para toda rota com {session_id}."""
    sessao = await request.app.state.servico_sessao.get_session(
        app_name=NOME_APP, user_id=USUARIO_SESSAO, session_id=session_id
    )
    if sessao is None:
        raise HTTPException(status_code=404, detail="sessão não encontrada")
    return sessao


def _montar(resultado: Resultado) -> RespostaConversa:
    return RespostaConversa(
        resposta=resultado.resposta,
        confirmacoes_pendentes=[
            ConfirmacaoPendente(id=c.id, acao=c.acao, detalhes=c.detalhes)
            for c in resultado.pendentes
        ],
    )


# -- rotas -----------------------------------------------------------------


@router.post("/sessoes", status_code=201)
async def criar_sessao(corpo: CriarSessao, request: Request) -> SessaoCriada:
    """Cria a sessão fixando o apartamento no estado dela.

    Garantia 2: o apartamento é definido aqui, uma única vez, e passa a ser a
    única fonte de verdade para as tools. Nada que o morador escrever depois
    altera este valor.
    """
    sessao = await request.app.state.servico_sessao.create_session(
        app_name=NOME_APP,
        user_id=USUARIO_SESSAO,
        state={"apartamento": corpo.apartamento},
    )
    return SessaoCriada(session_id=sessao.id)


@router.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(
    session_id: str, corpo: Mensagem, request: Request
) -> RespostaConversa:
    await _exigir_sessao(session_id, request)
    resultado = await request.app.state.execucao.enviar_mensagem(
        session_id, corpo.texto
    )
    return _montar(resultado)


@router.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(
    session_id: str, corpo: RespostaConfirmacao, request: Request
) -> RespostaConversa:
    """Responde uma confirmação pendente.

    `409` quando não existe confirmação pendente com esse id nesta sessão —
    o que cobre tanto o id inexistente quanto o de uma confirmação já
    respondida. A confirmação vem daqui, nunca do texto da conversa.
    """
    await _exigir_sessao(session_id, request)
    resultado = await request.app.state.execucao.responder_confirmacao(
        session_id, corpo.id, corpo.confirmado
    )
    if resultado is None:
        raise HTTPException(
            status_code=409,
            detail="não existe confirmação pendente com esse id nesta sessão",
        )
    return _montar(resultado)


@router.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str, request: Request) -> list[dict]:
    """Todos os eventos da sessão, em ordem, com o conteúdo completo."""
    sessao = await _exigir_sessao(session_id, request)
    return [evento.model_dump(mode="json") for evento in sessao.events]


@router.get("/apartamentos/{numero}/reservas")
async def listar_reservas(numero: str, request: Request) -> list[ReservaSaida]:
    reservas = request.app.state.repositorio.listar_reservas(numero)
    return [ReservaSaida(codigo=r.codigo, area=r.area, data=r.data) for r in reservas]


@router.get("/apartamentos/{numero}/visitantes")
async def listar_visitantes(numero: str, request: Request) -> list[VisitanteSaida]:
    visitantes = request.app.state.repositorio.listar_visitantes(numero)
    return [VisitanteSaida(nome=v.nome, data=v.data) for v in visitantes]
