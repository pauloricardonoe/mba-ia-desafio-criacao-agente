"""Configuração da aplicação, lida do ambiente.

Nenhum valor sensível tem padrão: a chave do AI Studio vem sempre do `.env`,
que fica fora do Git. Os demais valores têm padrões seguros para rodar local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "dados"

load_dotenv(RAIZ / ".env")

# Nome da aplicação ADK, usado como `app_name` no serviço de sessões.
NOME_APP = "residencial_aurora"

# O contrato da API não expõe o conceito de usuário: a sessão é identificada
# apenas pelo `session_id`. O ADK exige um `user_id`, então usamos um fixo.
USUARIO_SESSAO = "morador"


@dataclass(frozen=True)
class Config:
    """Configuração imutável, montada uma vez a partir do ambiente."""

    modelo: str
    banco_sessoes: str
    banco_dominio: str
    gateway_url: str | None = None
    gateway_token: str | None = None
    gateway_modelo: str | None = None
    gateway_header: str | None = None

    @property
    def usa_gateway(self) -> bool:
        """Se os agentes devem falar com um gateway em vez do AI Studio."""
        return bool(self.gateway_url)

    @classmethod
    def carregar(cls) -> "Config":
        # `or` em vez do padrão do os.getenv: uma variável presente e vazia no
        # `.env` (como no `.env.example`) precisa cair no padrão, não virar "".
        return cls(
            modelo=os.getenv("AURORA_MODELO") or "gemini-2.5-flash",
            # Sessões e eventos do ADK ficam em um arquivo próprio, separado dos
            # dados do condomínio. São dois ciclos de escrita diferentes, e
            # separá-los evita disputa de lock do SQLite entre eles.
            banco_sessoes=os.getenv("AURORA_DB") or "aurora.db",
            banco_dominio=os.getenv("AURORA_DB_DOMINIO") or "aurora-dominio.db",
            # Opcionais. Quando preenchidos, apontam os agentes para um gateway
            # compatível com a API da OpenAI. É um caminho de desenvolvimento;
            # o padrão do projeto continua sendo Gemini com chave do AI Studio.
            gateway_url=os.getenv("AURORA_GATEWAY_URL") or None,
            gateway_token=os.getenv("AURORA_GATEWAY_TOKEN") or None,
            gateway_modelo=os.getenv("AURORA_GATEWAY_MODELO") or None,
            gateway_header=os.getenv("AURORA_GATEWAY_HEADER") or None,
        )
