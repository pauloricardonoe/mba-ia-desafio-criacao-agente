"""Cria uma sessão no `adk web` já com o apartamento, e imprime a URL.

Por que isso é necessário: no `adk web`, a sessão é criada pela própria UI, sem
o campo `apartamento` no estado. Sem ele, as tools recusam com "sessão sem
apartamento definido" — de propósito, porque o apartamento vem da sessão e não
da conversa (Garantia 2).

Este script cria a sessão pelo endpoint da UI, com o apartamento já no estado.
Depois é só abrir a URL e conversar.

Uso:
    uv run python dev/nova_sessao.py 101
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://localhost:8001"
APP = "aurora_web"
USUARIO = "morador"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    apartamento = sys.argv[1]

    resposta = httpx.post(
        f"{BASE}/apps/{APP}/users/{USUARIO}/sessions",
        json={"state": {"apartamento": apartamento}},
        timeout=30,
    )
    if resposta.status_code != 200:
        print(f"falhou ({resposta.status_code}): {resposta.text[:200]}")
        print("o `adk web` está rodando? veja o topo do README.")
        sys.exit(1)

    sessao = resposta.json()
    print(f"sessão criada para o apartamento {apartamento}")
    print(f"session_id: {sessao['id']}")
    print()
    print("abra no navegador:")
    print(f"  http://localhost:8001/dev-ui/?app={APP}")


if __name__ == "__main__":
    main()
