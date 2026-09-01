"""Trabalhos em andamento, para o Cardputer acompanhar em vez de esperar cego.

Antes o /intent bloqueava ate 60s e o aparelho mostrava "IA pensando..."
parado, sem sinal de vida nem como desistir. Agora o pedido roda numa thread,
publica o que esta fazendo, e o aparelho pergunta o andamento de tempos em
tempos.

Quem esta executando descobre o proprio trabalho por thread local: assim
`progresso("abrindo whatsapp")` funciona de qualquer ponto do laco sem ter de
carregar o id por toda a pilha de chamadas.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_GUARDADOS = 8
VALIDADE = 300.0          # segundos: depois disso o trabalho e descartado

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}
_seq = [0]
_local = threading.local()


@dataclass
class Job:
    id: str
    pedido: str
    progresso: str = "pensando"
    pronto: bool = False
    cancelado: bool = False
    resultado: dict[str, Any] = field(default_factory=dict)
    criado: float = field(default_factory=time.time)
    passos: list[str] = field(default_factory=list)


def _limpar() -> None:
    """Descarta o que ja passou da validade, mantendo os mais novos."""
    agora = time.time()
    velhos = [k for k, j in _jobs.items() if agora - j.criado > VALIDADE]
    for k in velhos:
        _jobs.pop(k, None)
    if len(_jobs) > MAX_GUARDADOS:
        ordenados = sorted(_jobs.values(), key=lambda j: j.criado)
        for j in ordenados[: len(_jobs) - MAX_GUARDADOS]:
            _jobs.pop(j.id, None)


def criar(pedido: str) -> str:
    with _lock:
        _limpar()
        _seq[0] += 1
        jid = "j%d" % _seq[0]
        _jobs[jid] = Job(id=jid, pedido=pedido)
        return jid


def assumir(jid: str) -> None:
    """Marca este trabalho como o da thread atual."""
    _local.jid = jid


def largar() -> None:
    _local.jid = None


def atual() -> str:
    return getattr(_local, "jid", None) or ""


def progresso(texto: str, jid: str = "") -> None:
    """Uma linha curta do que esta acontecendo. Cabe no visor: ~40 chars."""
    jid = jid or atual()
    if not jid:
        return
    linha = " ".join(str(texto or "").split())[:60]
    with _lock:
        j = _jobs.get(jid)
        if j is None or j.pronto:
            return
        j.progresso = linha
        j.passos.append(linha)
        if len(j.passos) > 20:
            del j.passos[0]


def cancelar(jid: str) -> bool:
    with _lock:
        j = _jobs.get(jid)
        if j is None or j.pronto:
            return False
        j.cancelado = True
        j.progresso = "cancelando..."
        return True


def cancelado(jid: str = "") -> bool:
    """O laco checa isto entre os passos para parar no meio."""
    jid = jid or atual()
    if not jid:
        return False
    with _lock:
        j = _jobs.get(jid)
        return bool(j and j.cancelado)


def concluir(jid: str, resultado: dict[str, Any]) -> None:
    with _lock:
        j = _jobs.get(jid)
        if j is None:
            return
        j.resultado = dict(resultado or {})
        j.pronto = True
        j.progresso = ""


def ler(jid: str) -> dict[str, Any]:
    """O que o aparelho recebe ao perguntar pelo andamento."""
    with _lock:
        j = _jobs.get((jid or "").strip())
        if j is None:
            return {"ok": False, "error": "trabalho expirou"}
        if not j.pronto:
            return {"ok": True, "done": False, "progress": j.progresso,
                    "cancelado": j.cancelado}
        saida = {"ok": True, "done": True}
        saida.update(j.resultado)
        return saida


def passos(jid: str) -> list[str]:
    with _lock:
        j = _jobs.get(jid)
        return list(j.passos) if j else []
