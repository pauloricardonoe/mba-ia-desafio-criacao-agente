"""Tools do assistente.

Regra central da Garantia 2: **nenhuma tool aceita `apartamento` como
parâmetro**. O apartamento vem do estado da sessão, definido na criação e nunca
alterado. Isso implementa a garantia por construção, e não por validação: não
existe argumento capaz de expressar "dados de outro apartamento", então nem o
modelo nem uma mensagem bem escrita conseguem pedir isso.

Garantia 1: só as tools que geram cobrança ou liberam acesso exigem
confirmação. A exigência da reserva é condicional à taxa da área, avaliada pelo
callable `_reserva_exige_confirmacao`.
"""

from __future__ import annotations

from functools import lru_cache

from google.adk.tools import ToolContext

from aurora import regulamento
from aurora.config import DIR_DADOS, Config
from aurora.dominio.modelos import Area, ReservaRecusada
from aurora.dominio.repositorio import Repositorio
from aurora.texto import normalizar


@lru_cache(maxsize=1)
def _repositorio() -> Repositorio:
    """Repositório do condomínio. Sem estado: abre conexão a cada chamada."""
    return Repositorio(Config.carregar().banco_dominio)


@lru_cache(maxsize=1)
def _capitulos() -> list[regulamento.Capitulo]:
    return regulamento.carregar_capitulos(DIR_DADOS / "regulamento.md")


def _apartamento(tool_context: ToolContext) -> str:
    """O apartamento da sessão. É a única fonte de verdade (Garantia 2)."""
    apartamento = tool_context.state.get("apartamento")
    if not apartamento:
        raise ValueError("sessão sem apartamento definido")
    return str(apartamento)


def _resolver_area(texto: str) -> Area | None:
    """Casa o que o morador falou ('salão de festas') com o id da área."""
    alvo = normalizar(texto)
    for area in _repositorio().listar_areas():
        nome = normalizar(area.nome)
        if alvo == area.id or alvo == nome or alvo in nome or nome in alvo:
            return area
    return None


def resolver_area_id(texto: str) -> str | None:
    """Id canônico da área, para deixar `detalhes` da confirmação estável."""
    area = _resolver_area(texto)
    return area.id if area else None


# --------------------------------------------------------------------------
# Reservas
# --------------------------------------------------------------------------


def consultar_agenda(area: str, data: str) -> dict:
    """Diz se uma área está livre ou ocupada em uma data.

    Use antes de propor uma reserva, para saber se a data está disponível.
    Devolve apenas "livre" ou "ocupada" — nunca informa de quem é a reserva.

    Args:
        area: A área comum, como "quadra", "salão de festas" ou "churrasqueira".
        data: A data no formato AAAA-MM-DD.
    """
    resolvida = _resolver_area(area)
    if resolvida is None:
        return {"erro": f"área desconhecida: {area}"}
    return {
        "area": resolvida.id,
        "data": data,
        "disponibilidade": _repositorio().disponibilidade(resolvida.id, data),
    }


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador.

    Não recebe apartamento: devolve sempre as reservas do apartamento da sessão.
    """
    reservas = _repositorio().listar_reservas(_apartamento(tool_context))
    return {
        "reservas": [
            {"codigo": r.codigo, "area": r.area, "data": r.data} for r in reservas
        ]
    }


def reserva_exige_confirmacao(area: str, data: str, tool_context: ToolContext) -> bool:
    """Garantia 1: só exige confirmação quando a área tem taxa maior que zero.

    A assinatura espelha a de `criar_reserva`, como o ADK espera de um callable
    de confirmação: os mesmos argumentos da tool, mais o contexto.
    """
    resolvida = _resolver_area(area)
    return bool(resolvida and resolvida.gera_cobranca)


def criar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para uma data.

    Args:
        area: A área comum, como "quadra", "salão de festas" ou "churrasqueira".
        data: A data no formato AAAA-MM-DD.
    """
    apartamento = _apartamento(tool_context)
    resolvida = _resolver_area(area)
    if resolvida is None:
        return {"status": "recusada", "motivo": f"área desconhecida: {area}"}

    try:
        reserva = _repositorio().criar_reserva(apartamento, resolvida.id, data)
    except ReservaRecusada as recusa:
        # Recusa é resposta normal, nunca erro de servidor (Garantia 5).
        return {"status": "recusada", "motivo": recusa.motivo}

    return {
        "status": "reservado",
        "codigo": reserva.codigo,
        "area": reserva.area,
        "data": reserva.data,
        "cobranca": reserva.taxa,
    }


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva do próprio apartamento do morador.

    Não exige confirmação: o morador cancela as reservas do próprio apartamento
    sem confirmação (regra de negócio 4).

    Args:
        area: A área comum da reserva a cancelar.
        data: A data da reserva, no formato AAAA-MM-DD.
    """
    apartamento = _apartamento(tool_context)
    resolvida = _resolver_area(area)
    if resolvida is None:
        return {"status": "nao_encontrada", "motivo": f"área desconhecida: {area}"}

    cancelou = _repositorio().cancelar_reserva(apartamento, resolvida.id, data)
    if not cancelou:
        return {"status": "nao_encontrada", "motivo": "não há reserva sua nessa área e data"}
    return {"status": "cancelada", "area": resolvida.id, "data": data}


# --------------------------------------------------------------------------
# Visitantes
# --------------------------------------------------------------------------


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no condomínio em uma data.

    Args:
        nome: O nome completo do visitante.
        data: A data da visita, no formato AAAA-MM-DD.
    """
    apartamento = _apartamento(tool_context)
    visitante = _repositorio().autorizar_visitante(apartamento, nome, data)
    return {"status": "autorizado", "nome": visitante.nome, "data": visitante.data}


# --------------------------------------------------------------------------
# Regulamento
# --------------------------------------------------------------------------


def consultar_regulamento(topico: str) -> dict:
    """Consulta o regulamento interno do condomínio sobre um assunto.

    Devolve apenas o capítulo do regulamento que trata do assunto perguntado.
    Use sempre que o morador tiver dúvida sobre uma regra do condomínio.

    Args:
        topico: O assunto da dúvida, como "piscina", "silêncio", "animais",
            "mudanças", "garagem", "salão de festas" ou "lixo".
    """
    capitulo = regulamento.consultar(_capitulos(), topico)
    if capitulo is None:
        return {"encontrado": False, "topico": topico}
    return {"encontrado": True, "capitulo": capitulo.titulo, "texto": capitulo.texto}
