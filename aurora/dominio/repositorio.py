"""Acesso aos dados do condomínio, em SQLite.

Aqui moram as regras de negócio do enunciado. O modelo não decide nada neste
módulo: as tools chamam estes métodos passando o apartamento que veio do estado
da sessão, nunca um apartamento escolhido na conversa.

A Garantia 5 (exclusividade da reserva no instante da gravação) é implementada
pelo índice único parcial `reserva_ativa_unica`, não por uma conferência feita
antes. Conferir antes não basta: entre a conferência e a gravação, outra
reserva pode entrar.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aurora.dominio.modelos import (
    Apartamento,
    Area,
    Reserva,
    ReservaRecusada,
    Visitante,
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL,
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa',
    taxa        REAL NOT NULL DEFAULT 0
);

-- Garantia 5: duas reservas ativas para a mesma área e data são impossíveis.
-- O índice é parcial para que uma reserva cancelada libere a data sem que o
-- código dela seja reaproveitado (o código é a chave primária).
CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica
    ON reservas (area, data)
    WHERE status = 'ativa';

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contador (
    nome  TEXT PRIMARY KEY,
    valor INTEGER NOT NULL
);
"""


def _conectar(banco: str | Path) -> sqlite3.Connection:
    """Conexão com WAL e espera por lock, para aguentar escrita concorrente."""
    con = sqlite3.connect(str(banco), isolation_level=None, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 10000")
    con.execute("PRAGMA foreign_keys = ON")
    return con


class Repositorio:
    """Acesso aos dados do condomínio."""

    def __init__(self, banco: str | Path) -> None:
        self.banco = str(banco)

    # -- estrutura ---------------------------------------------------------

    def criar_esquema(self) -> None:
        con = _conectar(self.banco)
        try:
            con.executescript(ESQUEMA)
        finally:
            con.close()

    def _vazio(self, con: sqlite3.Connection) -> bool:
        return con.execute("SELECT COUNT(*) FROM areas").fetchone()[0] == 0

    def garantir_estado_inicial(self, dir_dados: Path) -> None:
        """Carrega `dados/*.json` apenas na primeira vez.

        Só carrega se o banco estiver vazio. É isso que faz a Garantia 3 valer:
        reiniciar a API não pode devolver o condomínio ao estado inicial.
        Os arquivos de `dados/` são lidos, nunca escritos.
        """
        con = _conectar(self.banco)
        try:
            con.executescript(ESQUEMA)
            if not self._vazio(con):
                return

            apartamentos = json.loads((dir_dados / "apartamentos.json").read_text())
            areas = json.loads((dir_dados / "areas.json").read_text())
            reservas = json.loads((dir_dados / "reservas.json").read_text())
            visitantes = json.loads((dir_dados / "visitantes.json").read_text())

            con.execute("BEGIN IMMEDIATE")
            con.executemany(
                "INSERT INTO apartamentos (numero, morador) VALUES (?, ?)",
                [(a["numero"], a["morador"]) for a in apartamentos],
            )
            taxas = {a["id"]: a["taxa"] for a in areas}
            con.executemany(
                "INSERT INTO areas (id, nome, taxa) VALUES (?, ?, ?)",
                [(a["id"], a["nome"], a["taxa"]) for a in areas],
            )
            con.executemany(
                "INSERT INTO reservas (codigo, apartamento, area, data, status, taxa)"
                " VALUES (?, ?, ?, ?, 'ativa', ?)",
                [
                    (
                        r["codigo"],
                        r["apartamento"],
                        r["area"],
                        r["data"],
                        taxas.get(r["area"], 0),
                    )
                    for r in reservas
                ],
            )
            con.executemany(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                [(v["apartamento"], v["nome"], v["data"]) for v in visitantes],
            )

            # A sequência começa depois do maior código já existente, para que
            # nenhum código novo repita RSV-1377, RSV-4821 ou RSV-2950.
            maior = max(
                (int(r["codigo"].split("-")[-1]) for r in reservas), default=0
            )
            con.execute(
                "INSERT INTO contador (nome, valor) VALUES ('reserva', ?)", (maior,)
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def restaurar(self, dir_dados: Path) -> None:
        """Devolve reservas e visitantes ao estado dos arquivos de `dados/`.

        Sessões e confirmações não são tocadas: apagá-las quebraria a Garantia 3
        se alguém restaurasse os dados antes de reiniciar a API.
        """
        con = _conectar(self.banco)
        try:
            reservas = json.loads((dir_dados / "reservas.json").read_text())
            visitantes = json.loads((dir_dados / "visitantes.json").read_text())
            taxas = {
                a["id"]: a["taxa"]
                for a in json.loads((dir_dados / "areas.json").read_text())
            }

            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM reservas")
            con.execute("DELETE FROM visitantes")
            con.executemany(
                "INSERT INTO reservas (codigo, apartamento, area, data, status, taxa)"
                " VALUES (?, ?, ?, ?, 'ativa', ?)",
                [
                    (
                        r["codigo"],
                        r["apartamento"],
                        r["area"],
                        r["data"],
                        taxas.get(r["area"], 0),
                    )
                    for r in reservas
                ],
            )
            con.executemany(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                [(v["apartamento"], v["nome"], v["data"]) for v in visitantes],
            )
            maior = max(
                (int(r["codigo"].split("-")[-1]) for r in reservas), default=0
            )
            con.execute(
                "INSERT INTO contador (nome, valor) VALUES ('reserva', ?)"
                " ON CONFLICT(nome) DO UPDATE SET valor = excluded.valor",
                (maior,),
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    # -- leitura -----------------------------------------------------------

    def area(self, area_id: str) -> Area | None:
        con = _conectar(self.banco)
        try:
            linha = con.execute(
                "SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)
            ).fetchone()
        finally:
            con.close()
        return Area(**dict(linha)) if linha else None

    def listar_areas(self) -> list[Area]:
        con = _conectar(self.banco)
        try:
            linhas = con.execute("SELECT id, nome, taxa FROM areas ORDER BY id").fetchall()
        finally:
            con.close()
        return [Area(**dict(l)) for l in linhas]

    def apartamento(self, numero: str) -> Apartamento | None:
        con = _conectar(self.banco)
        try:
            linha = con.execute(
                "SELECT numero, morador FROM apartamentos WHERE numero = ?", (numero,)
            ).fetchone()
        finally:
            con.close()
        return Apartamento(**dict(linha)) if linha else None

    def listar_reservas(self, apartamento: str) -> list[Reserva]:
        """Reservas ativas do apartamento. Só o próprio: não há parâmetro para outro."""
        con = _conectar(self.banco)
        try:
            linhas = con.execute(
                "SELECT codigo, apartamento, area, data, taxa FROM reservas"
                " WHERE apartamento = ? AND status = 'ativa' ORDER BY data",
                (apartamento,),
            ).fetchall()
        finally:
            con.close()
        return [Reserva(**dict(l)) for l in linhas]

    def listar_visitantes(self, apartamento: str) -> list[Visitante]:
        con = _conectar(self.banco)
        try:
            linhas = con.execute(
                "SELECT apartamento, nome, data FROM visitantes"
                " WHERE apartamento = ? ORDER BY data",
                (apartamento,),
            ).fetchall()
        finally:
            con.close()
        return [Visitante(**dict(l)) for l in linhas]

    def disponibilidade(self, area_id: str, data: str) -> str:
        """Devolve apenas 'livre' ou 'ocupada'.

        Garantia 2: a conversa pode saber se a data está livre, mas nunca de
        quem é a reserva que a ocupa.
        """
        con = _conectar(self.banco)
        try:
            ocupada = con.execute(
                "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
                (area_id, data),
            ).fetchone()
        finally:
            con.close()
        return "ocupada" if ocupada else "livre"

    # -- escrita -----------------------------------------------------------

    def _proximo_codigo(self, con: sqlite3.Connection) -> str:
        valor = con.execute(
            "SELECT valor FROM contador WHERE nome = 'reserva'"
        ).fetchone()[0]
        novo = valor + 1
        con.execute("UPDATE contador SET valor = ? WHERE nome = 'reserva'", (novo,))
        return f"RSV-{novo}"

    def criar_reserva(self, apartamento: str, area_id: str, data: str) -> Reserva:
        """Grava a reserva, ou levanta `ReservaRecusada` se a data estiver ocupada.

        A exclusividade vale no instante da gravação: o INSERT é que é barrado
        pelo índice único, não uma conferência anterior.
        """
        area = self.area(area_id)
        if area is None:
            raise ReservaRecusada(f"área desconhecida: {area_id}")

        con = _conectar(self.banco)
        try:
            con.execute("BEGIN IMMEDIATE")
            codigo = self._proximo_codigo(con)
            con.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data, status, taxa)"
                " VALUES (?, ?, ?, ?, 'ativa', ?)",
                (codigo, apartamento, area_id, data, area.taxa),
            )
            con.execute("COMMIT")
        except sqlite3.IntegrityError:
            # Perdeu a disputa: a data já tem reserva ativa. É resposta normal.
            con.execute("ROLLBACK")
            raise ReservaRecusada("data já ocupada") from None
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return Reserva(codigo, apartamento, area_id, data, area.taxa)

    def cancelar_reserva(self, apartamento: str, area_id: str, data: str) -> bool:
        """Cancela a reserva do próprio apartamento. Devolve se algo mudou."""
        con = _conectar(self.banco)
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "UPDATE reservas SET status = 'cancelada'"
                " WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa'",
                (apartamento, area_id, data),
            )
            con.execute("COMMIT")
            return cur.rowcount > 0
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def autorizar_visitante(self, apartamento: str, nome: str, data: str) -> Visitante:
        con = _conectar(self.banco)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                (apartamento, nome, data),
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return Visitante(apartamento, nome, data)
