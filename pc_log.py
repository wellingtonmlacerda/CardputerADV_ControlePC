"""Registro do que foi pedido e do que aconteceu.

Ate agora, quando algo falhava no uso real, o unico diagnostico disponivel era
um print da tela do terminal. Isto grava um JSONL por dia para que a proxima
falha possa ser lida depois, sem depender de alguem estar olhando.

Uma linha por pedido, mais uma por passo do laco de ferramentas.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PASTA = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck" / "log"
DIAS = 7

_lock = threading.Lock()


def _arquivo(quando: datetime | None = None) -> Path:
    d = quando or datetime.now()
    return PASTA / ("agent-%s.jsonl" % d.strftime("%Y%m%d"))


def _rotacionar() -> None:
    """Apaga o que passou de DIAS. Barato: roda junto com a escrita."""
    try:
        limite = datetime.now() - timedelta(days=DIAS)
        for f in PASTA.glob("agent-*.jsonl"):
            try:
                dia = datetime.strptime(f.stem[len("agent-"):], "%Y%m%d")
            except ValueError:
                continue
            if dia < limite:
                f.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def escrever(**campos: Any) -> None:
    registro = {"t": datetime.now().isoformat(timespec="seconds")}
    registro.update(campos)
    linha = json.dumps(registro, ensure_ascii=False, default=str)
    with _lock:
        try:
            PASTA.mkdir(parents=True, exist_ok=True)
            with _arquivo().open("a", encoding="utf-8") as fh:
                fh.write(linha + "\n")
            if registro.get("tipo") == "pedido":
                _rotacionar()
        except Exception:  # noqa: BLE001
            pass          # registro nunca pode derrubar o agente


def pedido(texto: str, camada: str, acao: str, q: str, ok: bool,
           ms: int, msg: str = "") -> None:
    escrever(tipo="pedido", pedido=texto[:200], camada=camada, acao=acao,
             q=str(q)[:200], ok=bool(ok), ms=int(ms), msg=str(msg)[:300])


def passo(ferramenta: str, args: Any, resultado: str, ms: int) -> None:
    escrever(tipo="passo", ferramenta=ferramenta, args=args,
             resultado=str(resultado)[:300], ms=int(ms))


def _ler_dias(n: int = 3) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    hoje = datetime.now()
    for i in range(n):
        f = _arquivo(hoje - timedelta(days=i))
        if not f.exists():
            continue
        try:
            for linha in f.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if linha.startswith("{"):
                    saida.append(json.loads(linha))
        except Exception:  # noqa: BLE001
            continue
    return saida


def falhas(n: int = 3) -> str:
    """Ultimas falhas, curtinho: e o que cabe no visor do Cardputer."""
    regs = [r for r in _ler_dias()
            if r.get("tipo") == "pedido" and not r.get("ok", True)]
    if not regs:
        return "nenhuma falha registrada"
    regs.sort(key=lambda r: str(r.get("t", "")))
    linhas = []
    for r in regs[-n:]:
        hora = str(r.get("t", ""))[11:16]
        linhas.append("%s %s: %s" % (hora, str(r.get("pedido", ""))[:24],
                                     str(r.get("msg", ""))[:40]))
    return "\n".join(linhas)


def resumo() -> str:
    """Quantos pedidos, quantos falharam e por qual camada passaram."""
    regs = [r for r in _ler_dias() if r.get("tipo") == "pedido"]
    if not regs:
        return "sem registros"
    total = len(regs)
    ruins = sum(1 for r in regs if not r.get("ok", True))
    camadas: dict[str, int] = {}
    for r in regs:
        c = str(r.get("camada", "?"))
        camadas[c] = camadas.get(c, 0) + 1
    ordem = ", ".join("%s %d" % (k, v)
                      for k, v in sorted(camadas.items(), key=lambda x: -x[1]))
    media = sum(int(r.get("ms", 0)) for r in regs) // max(total, 1)
    return "%d pedidos, %d falhas, media %dms | %s" % (total, ruins, media, ordem)
