"""Utilidades de texto."""

from __future__ import annotations

import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para casar 'salão' com 'salao'."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()
