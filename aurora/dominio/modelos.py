"""Modelos do domínio do condomínio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Apartamento:
    numero: str
    morador: str


@dataclass(frozen=True)
class Area:
    id: str
    nome: str
    taxa: float

    @property
    def gera_cobranca(self) -> bool:
        """Regra de negócio 2: taxa maior que zero gera cobrança."""
        return self.taxa > 0


@dataclass(frozen=True)
class Reserva:
    codigo: str
    apartamento: str
    area: str
    data: str
    taxa: float


@dataclass(frozen=True)
class Visitante:
    apartamento: str
    nome: str
    data: str


class ReservaRecusada(Exception):
    """Recusa de reserva tratada como resposta normal, nunca como erro de servidor.

    A Garantia 5 exige que a disputa por uma área termine com uma recusa
    educada, não com um 500.
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo
