"""Descobre e abre qualquer app instalado no Windows.

Fonte: shell:AppsFolder, a mesma lista do menu Iniciar "Todos os apps".
Cobre Win32, UWP/MSIX (Teams, WhatsApp, Calculadora) e apps de usuario.
Qualquer item de la abre com: explorer.exe "shell:AppsFolder\\" + AUMID
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import unicodedata
from pathlib import Path

CACHE = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck" / "apps.json"
MAX_AGE = 6 * 3600
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Como a pessoa fala -> nomes que o Windows pode usar, na ordem de preferencia.
ALIASES: dict[str, list[str]] = {
    "navegador": ["chrome", "edge", "firefox"],
    "browser": ["chrome", "edge", "firefox"],
    "internet": ["chrome", "edge", "firefox"],
    "bloco de notas": ["bloco de notas", "notepad"],
    "bloco": ["bloco de notas", "notepad"],
    "notas": ["bloco de notas", "notepad"],
    "calculadora": ["calculadora", "calculator"],
    "pastas": ["explorador de arquivos", "file explorer"],
    "arquivos": ["explorador de arquivos", "file explorer"],
    "explorer": ["explorador de arquivos", "file explorer"],
    "email": ["outlook"],
    "e mail": ["outlook"],
    "correio": ["outlook"],
    "planilha": ["excel"],
    "planilhas": ["excel"],
    "documento": ["word"],
    "documentos": ["word"],
    "apresentacao": ["powerpoint"],
    "slides": ["powerpoint"],
    "terminal": ["terminal", "prompt de comando"],
    "prompt": ["prompt de comando", "terminal"],
    "cmd": ["prompt de comando", "terminal"],
    "vscode": ["visual studio code"],
    "vs code": ["visual studio code"],
    "banco": ["sql server management studio"],
    "ssms": ["sql server management studio"],
    "reuniao": ["teams"],
    "reunioes": ["teams"],
    "zap": ["whatsapp"],
    "whats": ["whatsapp"],
    "musica": ["spotify", "windows media player"],
}

# Palavras que aparecem no pedido mas nao fazem parte do nome do app.
_NOISE = {
    "abre", "abra", "abrir", "abri", "inicia", "inicie", "iniciar", "roda", "rode",
    "rodar", "executa", "execute", "executar", "chama", "chame", "sobe", "liga",
    "ligue", "poe", "coloca", "quero", "pode", "vai", "vamos", "me", "pra", "para",
    "por", "favor", "o", "a", "os", "as", "um", "uma", "do", "da", "de", "no", "na",
    "em", "meu", "minha", "app", "aplicativo", "programa", "janela", "aqui", "ai",
    "agora",
}


def norm(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    keep = "".join(c if (c.isalnum() or c == " ") else " " for c in t)
    return " ".join(keep.split())


def strip_noise(text: str) -> str:
    return " ".join(w for w in norm(text).split() if w not in _NOISE)


def _ps(script: str, timeout: int = 40) -> str:
    """Roda PowerShell escondido e devolve stdout em UTF-8."""
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            capture_output=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _scan_appsfolder() -> list[dict[str, str]]:
    raw = _ps(
        "(New-Object -ComObject Shell.Application).NameSpace('shell:AppsFolder')"
        ".Items() | ForEach-Object { $_.Name + '|||' + $_.Path }"
    )
    apps: list[dict[str, str]] = []
    for line in raw.splitlines():
        if "|||" not in line:
            continue
        name, _, aumid = line.partition("|||")
        name, aumid = name.strip(), aumid.strip()
        if name and aumid:
            apps.append({"name": name, "id": aumid, "key": norm(name)})
    return apps


def refresh() -> list[dict[str, str]]:
    apps = _scan_appsfolder()
    if apps:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(
            json.dumps({"at": int(time.time()), "apps": apps}, ensure_ascii=False),
            encoding="utf-8",
        )
    return apps


def index(force: bool = False) -> list[dict[str, str]]:
    if not force and CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - int(data.get("at", 0)) < MAX_AGE and data.get("apps"):
                return list(data["apps"])
        except Exception:
            pass
    return refresh()


def _score(query: str, app: dict[str, str]) -> int:
    k = app.get("key") or ""
    if not k:
        return 0
    if k == query:
        return 100
    if k.startswith(query):
        return 85
    tokens = query.split()
    if tokens and all(t in k for t in tokens):
        # entre varios que batem, o nome mais curto costuma ser "o" app
        return 70 - min(len(k) // 8, 10)
    if query in k:
        return 55
    return 0


def _best(query: str, apps: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    scored = sorted(((_score(query, a), a) for a in apps), key=lambda p: -p[0])
    return [a for s, a in scored if s > 0][:limit]


def search(name: str, limit: int = 5, force: bool = False) -> list[dict[str, str]]:
    q = strip_noise(name) or norm(name)
    if not q:
        return []
    apps = index(force)
    for cand in ALIASES.get(q, [q]):
        hits = _best(cand, apps, limit)
        if hits:
            return hits
    if not force:
        # app instalado agora mesmo? reindexa uma vez so.
        return search(name, limit, force=True)
    return []


def resolve(name: str) -> dict[str, str] | None:
    hits = search(name, 1)
    return hits[0] if hits else None


def launch_id(aumid: str) -> None:
    subprocess.Popen(
        ["explorer.exe", "shell:AppsFolder\\" + aumid],
        close_fds=True,
        creationflags=NO_WINDOW,
    )


def launch(name: str) -> str:
    raw = (name or "").strip().strip('"')
    if not raw:
        return "diga qual programa"
    if raw.lower().startswith(("http://", "https://")):
        os.startfile(raw)
        return "abriu " + raw[:60]
    p = Path(raw)
    if p.exists():
        os.startfile(str(p))
        return "abriu " + p.name
    app = resolve(raw)
    if not app:
        return "nao achei o app: " + raw[:40]
    launch_id(app["id"])
    return "abriu " + app["name"][:50]


def suggest(name: str, n: int = 6) -> str:
    hits = search(name, n)
    if not hits:
        return "nenhum app parecido com: " + (name or "")[:40]
    return "\n".join(a["name"] for a in hits)
