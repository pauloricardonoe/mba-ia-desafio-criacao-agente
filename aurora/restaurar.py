"""Restaura reservas e visitantes ao estado dos arquivos de `dados/`.

Uso:
    uv run python -m aurora.restaurar

Não toca nas sessões nem nas confirmações: apagá-las quebraria a Garantia 3
caso alguém restaurasse os dados antes de reiniciar a API.
"""

from __future__ import annotations

from aurora.config import DIR_DADOS, Config
from aurora.dominio.repositorio import Repositorio


def main() -> None:
    config = Config.carregar()
    repositorio = Repositorio(config.banco_dominio)
    repositorio.garantir_estado_inicial(DIR_DADOS)
    repositorio.restaurar(DIR_DADOS)
    print(f"Dados restaurados a partir de {DIR_DADOS}")
    print(f"Banco de dados do condomínio: {config.banco_dominio}")


if __name__ == "__main__":
    main()
