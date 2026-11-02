"""Aplicação FastAPI do assistente."""

from __future__ import annotations

from contextlib import asynccontextmanager

import truststore

# Antes de qualquer contexto TLS: honra o trust store do sistema operacional.
# Necessário em redes com inspeção TLS, inofensivo em qualquer outro ambiente.
truststore.inject_into_ssl()

from fastapi import FastAPI  # noqa: E402
from google.adk import Runner  # noqa: E402
from google.adk.sessions import DatabaseSessionService  # noqa: E402

from aurora.agentes.agentes import criar_app_adk  # noqa: E402
from aurora.agentes.execucao import Execucao  # noqa: E402
from aurora.api.rotas import router  # noqa: E402
from aurora.config import DIR_DADOS, Config  # noqa: E402
from aurora.dominio.confirmacoes import RegistroConfirmacoes  # noqa: E402
from aurora.dominio.repositorio import Repositorio  # noqa: E402


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Prepara a configuração, os bancos e o runner do ADK.

    `garantir_estado_inicial` só carrega `dados/*.json` se o banco estiver
    vazio. É o que faz a Garantia 3 valer: reiniciar a API não devolve o
    condomínio ao estado inicial.
    """
    config = Config.carregar()

    repositorio = Repositorio(config.banco_dominio)
    repositorio.garantir_estado_inicial(DIR_DADOS)

    registro = RegistroConfirmacoes(config.banco_dominio)
    registro.criar_esquema()

    servico_sessao = DatabaseSessionService(
        db_url=f"sqlite+aiosqlite:///{config.banco_sessoes}"
    )
    runner = Runner(app=criar_app_adk(), session_service=servico_sessao)

    app.state.config = config
    app.state.repositorio = repositorio
    app.state.registro = registro
    app.state.servico_sessao = servico_sessao
    app.state.execucao = Execucao(runner, registro)
    yield


def criar_app() -> FastAPI:
    app = FastAPI(
        title="Assistente do Residencial Aurora",
        lifespan=ciclo_de_vida,
    )
    app.include_router(router)

    @app.get("/saude")
    def saude() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = criar_app()
