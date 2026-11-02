"""Consulta ao regulamento interno, por capítulo.

Garantia 4: o regulamento é consultado, nunca carregado. Este módulo parseia
`dados/regulamento.md` em capítulos e devolve **apenas** o capítulo que casa com
o assunto perguntado.

Devolver o arquivo inteiro violaria a garantia de imediato: o texto longo
passaria a acompanhar todas as mensagens seguintes, encarecendo cada chamada ao
modelo, e os eventos da sessão conteriam trechos de capítulos que não têm nada a
ver com a pergunta.

O agente principal também não recebe nada daqui — só o especialista de
regulamento, e só o capítulo pertinente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aurora.texto import normalizar as _normalizar

# Vocabulário por capítulo, derivado dos títulos do próprio regulamento mais os
# sinônimos que um morador usaria no dia a dia. É o que permite casar "até que
# horas a piscina funciona" com o Capítulo IV sem carregar o resto.
PALAVRAS_POR_CAPITULO: dict[str, tuple[str, ...]] = {
    "Disposições gerais": (
        "disposições gerais", "regra geral", "convenção", "administração",
        "síndico", "zelador", "definições", "aplicativo",
    ),
    "Direitos e deveres dos moradores": (
        "direitos", "deveres", "obrigações", "cota condominial", "condomínio",
        "elevador", "elevadores", "elevador social",
    ),
    "Silêncio e boa convivência": (
        "silêncio", "barulho", "ruído", "ruido", "som", "volume", "festa",
        "festas", "reunião", "vizinho", "convivência", "horário de silêncio",
        "instrumento musical",
    ),
    "Piscina": (
        "piscina", "deck", "raia", "traje de banho", "banho", "espreguiçadeira",
        "exame dermatológico", "cloro", "água",
    ),
    "Academia, brinquedoteca e playground": (
        "academia", "brinquedoteca", "playground", "musculação", "peso",
        "aparelho", "personal", "brinquedo", "criança", "crianças",
    ),
    "Salão de festas, churrasqueira e quadra": (
        "salão", "salao", "salão de festas", "churrasqueira", "quadra",
        "churrasco", "evento", "reserva", "reservas", "bola", "rede",
        "decoração", "festa no salão",
    ),
    "Portaria e segurança": (
        "portaria", "segurança", "visitante", "visitantes", "entrega",
        "encomenda", "câmera", "camera", "tag", "controle de acesso",
        "portão", "portao", "acesso",
    ),
    "Animais de estimação": (
        "animal", "animais", "pet", "cachorro", "cão", "cao", "gato", "cães",
        "coleira", "focinheira", "espaço pet", "dejeto",
    ),
    "Mudanças": (
        "mudança", "mudanca", "mudanças", "carreto", "elevador de serviço",
        "içamento", "volumoso",
    ),
    "Obras e reformas": (
        "obra", "obras", "reforma", "reformas", "entulho", "construção",
        "pintura", "argamassa", "lona",
    ),
    "Garagem e veículos": (
        "garagem", "vaga", "vagas", "carro", "veículo", "veiculo", "moto",
        "bicicletário", "bicicleta", "carregador", "elétrico",
    ),
    "Coleta de lixo e reciclagem": (
        "lixo", "reciclagem", "coleta", "coleta seletiva", "resíduo",
        "residuo", "descarte", "óleo de cozinha", "lixeira", "reciclável",
    ),
    "Infrações e penalidades": (
        "infração", "infracao", "multa", "penalidade", "advertência",
        "advertencia", "reincidência", "recurso", "defesa",
    ),
    "Disposições finais": (
        "disposições finais", "alteração do regulamento", "vigência",
        "revisão", "comunicado",
    ),
}


@dataclass(frozen=True)
class Capitulo:
    titulo: str
    texto: str
    palavras: tuple[str, ...]


def carregar_capitulos(caminho) -> list[Capitulo]:
    """Divide o regulamento em capítulos, pelos títulos de nível 2."""
    texto = caminho.read_text(encoding="utf-8")
    partes = re.split(r"^## ", texto, flags=re.MULTILINE)

    capitulos: list[Capitulo] = []
    for parte in partes[1:]:
        linhas = parte.split("\n", 1)
        titulo = linhas[0].strip()
        corpo = linhas[1].strip() if len(linhas) > 1 else ""
        # "Capítulo IV: Piscina" -> "Piscina", que é a chave do vocabulário.
        nome = titulo.split(":", 1)[1].strip() if ":" in titulo else titulo
        palavras = PALAVRAS_POR_CAPITULO.get(nome, (_normalizar(nome),))
        capitulos.append(
            Capitulo(
                titulo=titulo,
                texto=f"## {titulo}\n\n{corpo}",
                palavras=palavras,
            )
        )
    return capitulos


def _pontuar(capitulo: Capitulo, consulta_normalizada: str) -> int:
    """Conta quantas palavras-chave do capítulo aparecem na consulta."""
    return sum(1 for p in capitulo.palavras if _normalizar(p) in consulta_normalizada)


def consultar(capitulos: list[Capitulo], topico: str) -> Capitulo | None:
    """Devolve o capítulo que melhor casa com o tópico, ou None.

    Só um capítulo é devolvido. É isso que impede o regulamento inteiro de
    entrar no histórico da sessão.
    """
    consulta = _normalizar(topico)
    melhor: Capitulo | None = None
    melhor_pontos = 0

    for capitulo in capitulos:
        pontos = _pontuar(capitulo, consulta)
        # Desempate por título mais longo, para preferir o capítulo específico
        # ("Piscina") ao genérico quando ambos casam.
        if pontos > melhor_pontos or (
            pontos == melhor_pontos
            and pontos > 0
            and melhor is not None
            and len(capitulo.palavras) > len(melhor.palavras)
        ):
            melhor, melhor_pontos = capitulo, pontos

    return melhor
