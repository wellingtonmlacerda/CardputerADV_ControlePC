"""Memoria do que ja deu certo: frase -> sequencia de ferramentas.

Da segunda vez em diante o mesmo pedido roda sem chamar o modelo.

A generalizacao e DETERMINISTICA, nao vem do modelo. O plano original previa
pedir um regex ao modelo, mas regex inventado por um 3b erra e o estrago fica
gravado. Em vez disso: os valores que o laco usou nas ferramentas sao
procurados dentro da propria frase; onde batem, viram grupo de captura.

  frase : "manda bom dia pro natan no whatsapp"
  args  : app=whatsapp  person=Natan Salgado  text=bom dia
  vira  : manda (?P<c1>.+?) pro (?P<c2>.+?) no (?P<c3>.+?)
          com text={c1}, person={c2}, app={c3}

"Natan Salgado" nao aparece literalmente, mas o token "natan" aparece: e esse
o pedaco que vira variavel. Na proxima vez a pessoa pode ser outra e o
open_chat resolve o nome completo de novo.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

ARQUIVO = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck" / "recipes.json"
MAX_RECEITAS = 200

# palavras curtas demais ou comuns demais para virar variavel
_PARADAS = {"o", "a", "os", "as", "de", "do", "da", "no", "na", "em", "pro",
            "pra", "para", "um", "uma", "que", "com", "por", "ao"}


def norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower().strip())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _carregar() -> list[dict[str, Any]]:
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        return list(dados.get("receitas", []))
    except Exception:  # noqa: BLE001
        return []


def _gravar(receitas: list[dict[str, Any]]) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    corte = receitas[-MAX_RECEITAS:]
    ARQUIVO.write_text(
        json.dumps({"receitas": corte}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def _spans(frase: str, valor: str) -> tuple[int, int] | None:
    """Onde o valor (ou o token mais longo dele) aparece na frase."""
    f = norm(frase)
    v = norm(str(valor))
    if len(v) < 2:
        return None
    i = f.find(v)
    if i >= 0:
        return (i, i + len(v))
    for tok in sorted(v.split(), key=len, reverse=True):
        if len(tok) < 3 or tok in _PARADAS:
            continue
        m = re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", f)
        if m:
            return (m.start(), m.end())
    return None


def generalizar(frase: str, passos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Monta padrao + gabarito. None se nao der para generalizar com seguranca."""
    f = norm(frase)
    if not f or not passos:
        return None

    # candidatos: (inicio, fim, marcador)  -- um marcador por trecho distinto
    achados: dict[tuple[int, int], str] = {}
    ligacao: list[tuple[int, str, str, str]] = []   # passo_idx, chave, marcador
    for idx, p in enumerate(passos):
        for chave, valor in (p.get("args") or {}).items():
            if not isinstance(valor, str) or not valor.strip():
                continue
            span = _spans(f, valor)
            if span is None:
                continue
            marcador = achados.get(span)
            if marcador is None:
                marcador = "c%d" % (len(achados) + 1)
                achados[span] = marcador
            ligacao.append((idx, chave, marcador, valor))

    if not achados:
        return None

    # descarta trechos sobrepostos, mantendo os mais longos
    ordenados = sorted(achados.items(), key=lambda kv: (kv[0][0], -kv[0][1]))
    limpos: list[tuple[tuple[int, int], str]] = []
    fim_anterior = -1
    for span, marc in ordenados:
        if span[0] < fim_anterior:
            continue
        limpos.append((span, marc))
        fim_anterior = span[1]
    vivos = {m for _s, m in limpos}

    # monta o regex: literal escapado fora dos trechos, grupo dentro
    partes: list[str] = []
    pos = 0
    for (ini, fim), marc in limpos:
        partes.append(re.escape(f[pos:ini]).replace(r"\ ", r"\s+"))
        partes.append("(?P<%s>.+?)" % marc)
        pos = fim
    partes.append(re.escape(f[pos:]).replace(r"\ ", r"\s+"))
    padrao = "^" + "".join(partes) + "$"

    # gabarito dos passos, com {marcador} no lugar dos valores variaveis
    gabarito: list[dict[str, Any]] = []
    for idx, p in enumerate(passos):
        args = dict(p.get("args") or {})
        for i, chave, marc, _valor in ligacao:
            if i == idx and marc in vivos:
                args[chave] = "{%s}" % marc
        gabarito.append({"ferramenta": p["ferramenta"], "args": args})

    receita = {"padrao": padrao, "frase": f, "passos": gabarito,
               "usos": 0, "criada": int(time.time())}
    return receita if _valida(receita, frase, passos) else None


def _valida(receita: dict[str, Any], frase: str, passos: list[dict[str, Any]]) -> bool:
    """So grava se o padrao reproduzir exatamente os passos originais."""
    try:
        rx = re.compile(receita["padrao"])
    except re.error:
        return False
    m = rx.match(norm(frase))
    if not m:
        return False
    refeito = aplicar(receita, m)
    if len(refeito) != len(passos):
        return False
    for feito, original in zip(refeito, passos):
        if feito["ferramenta"] != original["ferramenta"]:
            return False
        for chave, valor in (original.get("args") or {}).items():
            novo = feito["args"].get(chave)
            if isinstance(valor, str) and isinstance(novo, str):
                # o trecho capturado pode ser o apelido ("natan") no lugar do
                # nome completo resolvido ("Natan Salgado"): isso e esperado
                if norm(novo) not in norm(valor) and norm(valor) not in norm(novo):
                    return False
            elif novo != valor:
                return False
    return True


def aplicar(receita: dict[str, Any], m: re.Match) -> list[dict[str, Any]]:
    grupos = {k: (v or "").strip() for k, v in m.groupdict().items()}
    saida = []
    for p in receita["passos"]:
        args = {}
        for chave, valor in (p.get("args") or {}).items():
            if isinstance(valor, str):
                for g, texto in grupos.items():
                    valor = valor.replace("{%s}" % g, texto)
            args[chave] = valor
        saida.append({"ferramenta": p["ferramenta"], "args": args})
    return saida


def procurar(frase: str) -> list[dict[str, Any]] | None:
    """Passos prontos para esta frase, ou None."""
    f = norm(frase)
    receitas = _carregar()
    for r in reversed(receitas):          # a mais recente ganha
        if r.get("frase") == f:
            return aplicar(r, re.match("^" + re.escape(f) + "$", f))
        padrao = r.get("padrao")
        if not padrao:
            continue
        try:
            m = re.match(padrao, f)
        except re.error:
            continue
        if m:
            r["usos"] = int(r.get("usos", 0)) + 1
            _gravar(receitas)
            return aplicar(r, m)
    return None


def salvar(frase: str, passos: list[dict[str, Any]]) -> str:
    """Guarda o que deu certo. Generaliza quando der; senao, frase exata."""
    if not passos:
        return "nada para guardar"
    receita = generalizar(frase, passos)
    if receita is None:
        receita = {"padrao": "", "frase": norm(frase), "passos": passos,
                   "usos": 0, "criada": int(time.time())}
        tipo = "frase exata"
    else:
        tipo = "padrao"
    receitas = [r for r in _carregar() if r.get("frase") != receita["frase"]]
    receitas.append(receita)
    _gravar(receitas)
    return "aprendi (%s)" % tipo


def esquecer_ultima() -> str:
    receitas = _carregar()
    if not receitas:
        return "nao havia nada aprendido"
    fora = receitas.pop()
    _gravar(receitas)
    return "esqueci: " + str(fora.get("frase", ""))[:60]


def esquecer_tudo() -> str:
    n = len(_carregar())
    _gravar([])
    return "esqueci tudo (%d)" % n


def listar() -> str:
    receitas = _carregar()
    if not receitas:
        return "nada aprendido ainda"
    return "\n".join("%dx %s" % (r.get("usos", 0), r.get("frase", ""))
                     for r in receitas[-15:])
