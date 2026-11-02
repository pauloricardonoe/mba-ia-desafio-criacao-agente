"""Registro das confirmações pendentes.

Por que este registro existe, se o ADK já pausa a execução sozinho: o contrato
HTTP exige duas coisas que o ADK não entrega por si.

1. `409` para um `id` que não está pendente, **inclusive o de uma confirmação já
   respondida**. O ADK sabe que pausou, mas não guarda esse histórico para
   consulta depois.
2. `confirmacoes_pendentes` listando **todas** as pendências da sessão no momento
   da resposta, não só as da última execução.

A tabela é escrita quando um evento `adk_request_confirmation` aparece e
consultada em toda resposta. O `409` é decidido pelo `status`, não pelo ADK.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from aurora.dominio.repositorio import _conectar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS confirmacoes (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    invocation_id TEXT,
    acao          TEXT NOT NULL,
    detalhes      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pendente'
);

CREATE INDEX IF NOT EXISTS confirmacoes_por_sessao
    ON confirmacoes (session_id, status);
"""


@dataclass(frozen=True)
class Confirmacao:
    id: str
    session_id: str
    invocation_id: str | None
    acao: str
    detalhes: dict
    status: str


class RegistroConfirmacoes:
    """Guarda e responde as confirmações pendentes de cada sessão."""

    def __init__(self, banco: str) -> None:
        self.banco = banco

    def criar_esquema(self) -> None:
        con = _conectar(self.banco)
        try:
            con.executescript(ESQUEMA)
        finally:
            con.close()

    def registrar(
        self,
        *,
        id: str,
        session_id: str,
        invocation_id: str | None,
        acao: str,
        detalhes: dict,
    ) -> None:
        """Anota uma pendência. Reexecução do mesmo id não duplica a linha."""
        con = _conectar(self.banco)
        try:
            con.execute(
                "INSERT INTO confirmacoes"
                " (id, session_id, invocation_id, acao, detalhes, status)"
                " VALUES (?, ?, ?, ?, ?, 'pendente')"
                " ON CONFLICT(id) DO NOTHING",
                (id, session_id, invocation_id, acao, json.dumps(detalhes, ensure_ascii=False)),
            )
        finally:
            con.close()

    def _linha_para(self, linha: sqlite3.Row) -> Confirmacao:
        return Confirmacao(
            id=linha["id"],
            session_id=linha["session_id"],
            invocation_id=linha["invocation_id"],
            acao=linha["acao"],
            detalhes=json.loads(linha["detalhes"]),
            status=linha["status"],
        )

    def pendentes(self, session_id: str) -> list[Confirmacao]:
        con = _conectar(self.banco)
        try:
            linhas = con.execute(
                "SELECT * FROM confirmacoes WHERE session_id = ? AND status = 'pendente'"
                " ORDER BY rowid",
                (session_id,),
            ).fetchall()
        finally:
            con.close()
        return [self._linha_para(l) for l in linhas]

    def buscar(self, session_id: str, id: str) -> Confirmacao | None:
        con = _conectar(self.banco)
        try:
            linha = con.execute(
                "SELECT * FROM confirmacoes WHERE session_id = ? AND id = ?",
                (session_id, id),
            ).fetchone()
        finally:
            con.close()
        return self._linha_para(linha) if linha else None

    def responder(self, session_id: str, id: str, confirmado: bool) -> Confirmacao | None:
        """Marca a pendência como respondida e devolve o que foi aprovado.

        Devolve `None` quando não há pendência com esse id nesta sessão — o que
        cobre tanto o id inexistente quanto o de uma confirmação já respondida.
        A troca de status é uma única instrução condicional, então dois envios
        simultâneos da mesma resposta não podem ambos ter sucesso.
        """
        novo_status = "aprovada" if confirmado else "negada"
        con = _conectar(self.banco)
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "UPDATE confirmacoes SET status = ?"
                " WHERE id = ? AND session_id = ? AND status = 'pendente'",
                (novo_status, id, session_id),
            )
            if cur.rowcount == 0:
                con.execute("ROLLBACK")
                return None
            linha = con.execute(
                "SELECT * FROM confirmacoes WHERE id = ?", (id,)
            ).fetchone()
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return self._linha_para(linha)
