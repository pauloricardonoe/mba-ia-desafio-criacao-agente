"""Verificação do domínio: regras de negócio e Garantia 5.

Descartável, como o resto de `spike/`. Roda contra um banco temporário.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from aurora.config import DIR_DADOS
from aurora.dominio.modelos import ReservaRecusada
from aurora.dominio.repositorio import Repositorio

falhas: list[str] = []


def conferir(descricao: str, obtido, esperado) -> None:
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {descricao}: {obtido!r}")
    if not ok:
        falhas.append(f"{descricao}: esperado {esperado!r}, obtido {obtido!r}")


def novo_repo(tmp: Path) -> Repositorio:
    repo = Repositorio(tmp / "dominio.db")
    repo.garantir_estado_inicial(DIR_DADOS)
    return repo


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    repo = novo_repo(tmp)

    print("estado inicial")
    conferir(
        "reservas do 101",
        [(r.codigo, r.area, r.data) for r in repo.listar_reservas("101")],
        [("RSV-1377", "quadra", "2030-03-09")],
    )
    conferir(
        "visitantes do 302",
        [(v.nome, v.data) for v in repo.listar_visitantes("302")],
        [("Marina Duarte", "2030-03-16")],
    )

    print("\ndisponibilidade (Garantia 2: so livre/ocupada)")
    conferir("quadra 2030-03-09", repo.disponibilidade("quadra", "2030-03-09"), "ocupada")
    conferir("quadra 2030-04-06", repo.disponibilidade("quadra", "2030-04-06"), "livre")

    print("\nreserva nova e codigo unico")
    r1 = repo.criar_reserva("101", "quadra", "2030-04-06")
    conferir("codigo difere dos iniciais", r1.codigo not in {"RSV-1377", "RSV-4821", "RSV-2950"}, True)
    conferir("taxa da quadra (sem cobranca)", r1.taxa, 0)
    r2 = repo.criar_reserva("101", "salao-de-festas", "2030-04-20")
    conferir("codigos distintos entre si", r1.codigo != r2.codigo, True)
    conferir("taxa do salao (com cobranca)", r2.taxa, 150.0)

    print("\nconflito de data ocupada")
    try:
        repo.criar_reserva("101", "salao-de-festas", "2030-03-16")
        conferir("recusa do 302 ocupando a data", "nao recusou", "ReservaRecusada")
    except ReservaRecusada as e:
        conferir("recusa do 302 ocupando a data", e.motivo, "data já ocupada")
    conferir(
        "302 intacto",
        [(r.codigo, r.data) for r in repo.listar_reservas("302")],
        [("RSV-4821", "2030-03-16")],
    )

    print("\ncancelamento libera a data sem liberar o codigo")
    conferir("cancela a propria", repo.cancelar_reserva("101", "quadra", "2030-03-09"), True)
    conferir("sumiu das reservas do 101", [r.codigo for r in repo.listar_reservas("101")].count("RSV-1377"), 0)
    conferir("data liberada", repo.disponibilidade("quadra", "2030-03-09"), "livre")
    conferir("cancelar de outro apartamento nao muda nada", repo.cancelar_reserva("101", "salao-de-festas", "2030-03-16"), False)
    r3 = repo.criar_reserva("201", "quadra", "2030-03-09")
    conferir("codigo novo != codigo cancelado", r3.codigo != "RSV-1377", True)

    print("\nGarantia 5: disputa concorrente pela mesma area e data")
    repo2 = novo_repo(Path(tempfile.mkdtemp()))
    barreira = threading.Barrier(2)
    resultados: list[str] = []
    travas = threading.Lock()

    def tentar(apartamento: str) -> None:
        barreira.wait()
        try:
            r = repo2.criar_reserva(apartamento, "salao-de-festas", "2030-05-11")
            with travas:
                resultados.append(f"ok:{apartamento}:{r.codigo}")
        except ReservaRecusada as e:
            with travas:
                resultados.append(f"recusado:{apartamento}:{e.motivo}")

    threads = [threading.Thread(target=tentar, args=(a,)) for a in ("101", "201")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"    resultados: {sorted(resultados)}")
    vencedores = [r for r in resultados if r.startswith("ok:")]
    conferir("exatamente um venceu", len(vencedores), 1)
    conferir("exatamente um recusado", len([r for r in resultados if r.startswith("recusado:")]), 1)
    ativas = len([r for r in repo2.listar_reservas("101") + repo2.listar_reservas("201") if r.data == "2030-05-11"])
    conferir("uma unica reserva ativa na area/data", ativas, 1)

    print("\nrestauracao")
    repo.restaurar(DIR_DADOS)
    conferir(
        "volta ao estado inicial",
        sorted((r.codigo, r.area, r.data) for r in repo.listar_reservas("101")),
        [("RSV-1377", "quadra", "2030-03-09")],
    )
    conferir("visitantes restaurados", len(repo.listar_visitantes("302")), 1)

    print()
    if falhas:
        print(f"### {len(falhas)} FALHA(S)")
        for f in falhas:
            print(f"  - {f}")
        raise SystemExit(1)
    print("### dominio OK")


if __name__ == "__main__":
    main()
