"""Entrada do agente para o `adk web`.

O `adk web` procura, numa pasta de agentes, um módulo que exponha `app` ou
`root_agent`. Expomos o `App` completo — não só o agente raiz — para que a UI
use a mesma configuração de retomada e de cache de contexto que a API usa.

O nome do arquivo importa: o `adk web` usa um carregador que só reconhece pastas
com `agent.py` ou `root_agent.yaml`. Com `__init__.py` o agente carrega, mas não
aparece na lista da interface.

Uso:

    uv run adk web dev --port 8001

---

Sobre o apartamento nesta entrada de desenvolvimento:

Na API, o apartamento é fixado na criação da sessão e representa o morador
autenticado (Garantia 2). O `adk web` não tem autenticação: ele cria a sessão
sozinho, sem apartamento, e as tools recusariam com "sessão sem apartamento
definido".

Por isso esta entrada instala um callback que **simula a autenticação**: se a
sessão não tem apartamento, ele assume o valor de `AURORA_DEV_APARTAMENTO`
(padrão `101`). É o equivalente, no ambiente de desenvolvimento, a "este
morador está autenticado como o 101".

Isto **não** existe no caminho da API, e não afeta a Garantia 2: o valor vem de
configuração, não do modelo nem da conversa, e nenhuma tool passa a aceitar
apartamento como parâmetro. Para conversar como outro morador, defina
`AURORA_DEV_APARTAMENTO=302` e reinicie.
"""

from __future__ import annotations

import os

from google.adk.agents.callback_context import CallbackContext

from aurora.agentes.agentes import criar_app_adk, principal


def _simular_autenticacao(callback_context: CallbackContext) -> None:
    """Dá à sessão o apartamento do morador, se ela ainda não tiver um."""
    if not callback_context.state.get("apartamento"):
        callback_context.state["apartamento"] = os.getenv(
            "AURORA_DEV_APARTAMENTO", "101"
        )
    return None


# Cópia do agente principal, para instalar o callback sem tocar no agente que a
# API usa. `model_copy` evita que a mutação vaze para o caminho de produção.
principal_dev = principal.model_copy(
    update={"before_agent_callback": _simular_autenticacao}
)

app = criar_app_adk(principal_dev)
root_agent = principal_dev
