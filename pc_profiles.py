"""Como cada app expoe a lista de conversas, e como saber que ela trocou.

Nao ha um jeito unico: medido nesta maquina, o WhatsApp usa DataItemControl e
a caixa de escrever muda para "Digite uma mensagem para <pessoa>"; o Teams usa
TreeItemControl, a caixa e sempre "Digite uma mensagem" e o titulo da janela
nem acompanha a aba. Cada um desses foi descoberto na mao, depurando.

Aqui isso vira dado, nao codigo. App desconhecido passa por uma sondagem que
adivinha o tipo da linha e testa qual sinal de verificacao funciona, e o que
der certo fica gravado - na segunda vez ja funciona sem ninguem editar nada.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ARQUIVO = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck" / "profiles.json"

# sinais possiveis de que a conversa realmente trocou
COMPOSE = "compose"        # o nome da caixa de escrever passa a citar a pessoa
TITULO = "titulo"          # o titulo da janela muda
SELECIONADO = "selecionado"  # o item clicado fica IsSelected
AUTO = "auto"              # tenta todos e grava o que funcionou

TODOS_ITENS = ("DataItemControl", "ListItemControl", "TreeItemControl")


@dataclass
class Perfil:
    itens: tuple[str, ...] = TODOS_ITENS
    verifica: str = AUTO
    nav: tuple[str, ...] = ("conversas", "chat")
    busca: tuple[str, ...] = ("pesquis", "search", "buscar", "procure")
    descoberto: bool = False
    quando: int = 0

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("itens", "nav", "busca"):
            d[k] = list(d[k])
        return d


# Perfis medidos no aparelho. Servem de base e de rede de seguranca: mesmo que
# a sondagem erre, estes dois continuam certos.
CONHECIDOS: dict[str, Perfil] = {
    "whatsapp": Perfil(
        itens=("DataItemControl",),
        verifica=COMPOSE,
        nav=("conversas",),
        busca=("pesquis",),
    ),
    "teams": Perfil(
        itens=("TreeItemControl",),
        verifica=SELECIONADO,
        nav=("chat",),
        busca=("procure", "pesquis"),
    ),
}


def chave(app: str) -> str:
    t = unicodedata.normalize("NFD", (app or "").lower().strip())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = " ".join(t.split())
    for nome in CONHECIDOS:
        if nome in t:
            return nome
    return t or "?"


def _carregar() -> dict[str, dict[str, Any]]:
    try:
        return dict(json.loads(ARQUIVO.read_text(encoding="utf-8")).get("perfis", {}))
    except Exception:  # noqa: BLE001
        return {}


def _gravar(perfis: dict[str, dict[str, Any]]) -> None:
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(json.dumps({"perfis": perfis}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def obter(app: str) -> Perfil:
    """Perfil conhecido, aprendido, ou o generico."""
    k = chave(app)
    if k in CONHECIDOS:
        return CONHECIDOS[k]
    bruto = _carregar().get(k)
    if bruto:
        try:
            return Perfil(
                itens=tuple(bruto.get("itens") or TODOS_ITENS),
                verifica=str(bruto.get("verifica") or AUTO),
                nav=tuple(bruto.get("nav") or ()),
                busca=tuple(bruto.get("busca") or ()),
                descoberto=True,
                quando=int(bruto.get("quando", 0)),
            )
        except Exception:  # noqa: BLE001
            pass
    return Perfil()


def guardar(app: str, perfil: Perfil) -> None:
    k = chave(app)
    if k in CONHECIDOS:
        return                     # os medidos a mao nao sao sobrescritos
    perfis = _carregar()
    perfil.descoberto = True
    perfil.quando = int(time.time())
    perfis[k] = perfil.to_json()
    _gravar(perfis)


def aprender_verificacao(app: str, sinal: str) -> None:
    """Grava qual sinal de verificacao funcionou para este app."""
    if sinal not in (COMPOSE, TITULO, SELECIONADO):
        return
    k = chave(app)
    if k in CONHECIDOS:
        return
    p = obter(app)
    if p.verifica == sinal:
        return
    p.verifica = sinal
    guardar(app, p)


def sondar(historico: dict[str, int], nomes_por_tipo: dict[str, list[str]]) -> tuple[str, ...]:
    """Adivinha qual tipo de controle e a linha de conversa.

    Recebe o histograma de tipos e os nomes vistos em cada um. Uma linha de
    conversa aparece muitas vezes (uma por contato) e traz nome + previa, ou
    seja, texto comprido. Um item de menu aparece pouco e e uma palavra.
    """
    melhor, nota_melhor = (), -1.0
    for tipo in TODOS_ITENS:
        n = historico.get(tipo, 0)
        if n < 3:
            continue
        nomes = [x for x in nomes_por_tipo.get(tipo, []) if x]
        if not nomes:
            continue
        medio = sum(len(x) for x in nomes) / len(nomes)
        if medio < 12:
            continue          # menu lateral, nao lista de conversa
        nota = min(n, 40) * medio
        if nota > nota_melhor:
            melhor, nota_melhor = (tipo,), nota
    return melhor or TODOS_ITENS


def esquecer(app: str = "") -> str:
    if not app:
        _gravar({})
        return "esqueci todos os perfis"
    perfis = _carregar()
    k = chave(app)
    if perfis.pop(k, None) is None:
        return "nao havia perfil de " + k
    _gravar(perfis)
    return "esqueci o perfil de " + k


def listar() -> str:
    perfis = _carregar()
    fixos = ", ".join(CONHECIDOS)
    if not perfis:
        return "medidos: %s | aprendidos: nenhum" % fixos
    apr = ", ".join("%s(%s)" % (k, v.get("verifica", "?")) for k, v in perfis.items())
    return "medidos: %s | aprendidos: %s" % (fixos, apr)
