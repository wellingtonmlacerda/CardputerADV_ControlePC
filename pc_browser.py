"""Controle do Chrome/Edge via CDP (porta 9222). Playwright numa thread so."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.request import urlopen

CDP = "http://127.0.0.1:9222"
PROFILE = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck" / "chrome-cdp"

_PW = None
_BROWSER = None
_JOBS: queue.Queue = queue.Queue()
_WORKER: threading.Thread | None = None
_READY = threading.Event()


def _chrome_exe() -> str:
    for p in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    ):
        if p.exists():
            return str(p)
    return ""


def cdp_up() -> bool:
    try:
        with urlopen(CDP + "/json/version", timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def _launch_debug_chrome() -> str:
    exe = _chrome_exe()
    if not exe:
        return "Chrome/Edge nao encontrado"
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            exe,
            "--remote-debugging-port=9222",
            "--user-data-dir=" + str(PROFILE),
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.google.com",
        ],
        close_fds=True,
    )
    for _ in range(30):
        time.sleep(0.4)
        if cdp_up():
            return "ok"
    return "Chrome nao abriu a porta 9222"


def _ensure():
    global _PW, _BROWSER
    if _BROWSER is not None:
        try:
            if _BROWSER.is_connected():
                return _BROWSER
        except Exception:
            _BROWSER = None
            _PW = None
    if not cdp_up():
        msg = _launch_debug_chrome()
        if msg != "ok":
            raise RuntimeError(
                msg
                + ". Feche o Chrome e rode iniciar-chrome-debug.bat"
            )
    from playwright.sync_api import sync_playwright

    if _PW is None:
        _PW = sync_playwright().start()
    _BROWSER = _PW.chromium.connect_over_cdp(CDP)
    return _BROWSER


def _ctx_pages():
    browser = _ensure()
    ctxs = browser.contexts
    if not ctxs:
        raise RuntimeError("navegador sem contexto")
    ctx = ctxs[0]
    pages = [p for p in ctx.pages if not p.is_closed()]
    if not pages:
        pages = [ctx.new_page()]
    return ctx, pages


def _page():
    _ctx, pages = _ctx_pages()
    return pages[-1]


def _worker_loop() -> None:
    _READY.set()
    while True:
        item = _JOBS.get()
        if item is None:
            break
        fn, args, kwargs, box = item
        try:
            box["ok"] = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc
        box["ev"].set()


def _call(fn: Callable[..., str], *args: Any, **kwargs: Any) -> str:
    global _WORKER
    if _WORKER is None or not _WORKER.is_alive():
        _READY.clear()
        _WORKER = threading.Thread(target=_worker_loop, name="pw-cdp", daemon=True)
        _WORKER.start()
        _READY.wait(timeout=5)
    box: dict[str, Any] = {"ev": threading.Event(), "ok": None, "err": None}
    _JOBS.put((fn, args, kwargs, box))
    if not box["ev"].wait(timeout=45):
        raise TimeoutError("navegador demorou demais")
    if box["err"] is not None:
        raise box["err"]
    return str(box["ok"] or "")


def _as_url(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "https://www.google.com"
    if q.startswith(("http://", "https://")):
        return q
    if q.startswith("www."):
        return "https://" + q
    low = q.lower()
    if low in ("google", "inicio", "home", "navegador"):
        return "https://www.google.com"
    if low in ("youtube", "yt"):
        return "https://www.youtube.com"
    first = q.split()[0]
    if " " not in q and "." in first and not first.endswith("."):
        return "https://" + q
    if low.startswith("youtube ") or low.startswith("yt "):
        return "https://www.youtube.com/results?search_query=" + quote_plus(q.split(" ", 1)[-1])
    return "https://www.google.com/search?q=" + quote_plus(q)


def _go_sync(q: str) -> str:
    raw = (q or "").strip()
    url = raw if raw.startswith("http") else _as_url(raw)
    page = _page()
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    title = page.title() or ""
    return ("abriu " + title[:50] + " | " + page.url)[:120]


def _youtube_play_sync(term: str) -> str:
    term = (term or "").strip()
    if not term:
        return _go_sync("https://www.youtube.com")
    url = "https://www.youtube.com/results?search_query=" + quote_plus(term)
    page = _page()
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(1500)
    selectors = (
        "ytd-video-renderer a#video-title",
        "a#video-title-link",
        "a#video-title",
        "ytd-thumbnail a#thumbnail",
        "a[href*='watch?v=']",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=5000)
            loc.click(timeout=5000)
            page.wait_for_timeout(800)
            title = page.title() or term
            if "results?search_query" in (page.url or ""):
                continue
            return ("tocando " + title[:50])[:120]
        except Exception:
            continue
    try:
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        page.wait_for_timeout(600)
        if "watch" in (page.url or ""):
            return ("tocando " + (page.title() or term)[:50])[:120]
    except Exception:
        pass
    return ("abriu busca, clique falhou: " + term)[:80]


def _back_sync() -> str:
    page = _page()
    page.go_back(wait_until="domcontentloaded", timeout=12000)
    return ("voltou " + (page.title() or "")[:60])[:120]


def _tabs_sync(cmd: str) -> str:
    ctx, pages = _ctx_pages()
    c = (cmd or "list").strip().lower()
    if c in ("list", "lista", ""):
        lines = []
        for i, p in enumerate(pages):
            mark = "*" if p == pages[-1] else " "
            lines.append(f"{i + 1}{mark} {p.title()[:40]}")
        return "\n".join(lines) or "sem abas"
    if c in ("new", "nova", "nova aba"):
        p = ctx.new_page()
        p.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
        return "nova aba"
    if c in ("close", "fecha", "fechar"):
        pages[-1].close()
        return "aba fechada"
    if c in ("next", "proxima", "proximo"):
        try:
            i = pages.index(pages[-1])
        except ValueError:
            i = 0
        nxt = pages[(i + 1) % len(pages)]
        nxt.bring_to_front()
        return "aba: " + (nxt.title() or "")[:50]
    if c in ("prev", "anterior"):
        try:
            i = pages.index(pages[-1])
            nxt = pages[(i - 1) % len(pages)]
        except ValueError:
            nxt = pages[0]
        nxt.bring_to_front()
        return "aba: " + (nxt.title() or "")[:50]
    if c.isdigit():
        i = int(c) - 1
        if 0 <= i < len(pages):
            pages[i].bring_to_front()
            return "aba: " + (pages[i].title() or "")[:50]
    return "use: list, nova, fecha, proxima, anterior ou numero"


def _click_sync(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "diga o que clicar"
    page = _page()
    page.bring_to_front()
    if q.startswith(("#", ".", "[", "/")):
        page.locator(q).first.click(timeout=5000)
        return "clicou " + q[:60]
    for loc in (
        page.get_by_role("button", name=q),
        page.get_by_role("link", name=q),
        page.get_by_placeholder(q),
        page.get_by_label(q),
        page.get_by_text(q, exact=False),
    ):
        try:
            loc.first.click(timeout=2500)
            return "clicou " + q[:60]
        except Exception:
            continue
    return "nao achei na pagina: " + q[:60]


def _type_sync(q: str) -> str:
    q = (q or "")[:400]
    if not q:
        return "nada para digitar"
    _page().keyboard.type(q, delay=20)
    return f"digitou {len(q)} letras"


def _press_sync(key: str) -> str:
    key = (key or "Enter").strip() or "Enter"
    aliases = {
        "enter": "Enter",
        "esc": "Escape",
        "escape": "Escape",
        "tab": "Tab",
        "space": "Space",
        "backspace": "Backspace",
        "down": "ArrowDown",
        "up": "ArrowUp",
        "left": "ArrowLeft",
        "right": "ArrowRight",
    }
    key = aliases.get(key.lower(), key)
    _page().keyboard.press(key)
    return "tecla " + key


def _scroll_sync(q: str) -> str:
    raw = (q or "down").strip().lower()
    dy = 600
    if raw in ("up", "sobe", "cima"):
        dy = -600
    elif raw in ("down", "desce", "rola", "baixo"):
        dy = 600
    else:
        try:
            dy = int(raw)
        except ValueError:
            dy = 600
    _page().mouse.wheel(0, dy)
    return f"scroll {dy}"


def _flat(node: dict, depth: int, lines: list[str]) -> None:
    if depth > 7 or len(lines) >= 70:
        return
    role = str(node.get("role") or "")
    name = str(node.get("name") or "").replace("\n", " ")[:70]
    if name and role not in ("generic", "none", "Div", "group"):
        lines.append(("  " * depth) + role + ": " + name)
    for ch in node.get("children") or []:
        if isinstance(ch, dict):
            _flat(ch, depth + 1, lines)


def _snapshot_sync() -> str:
    page = _page()
    title = page.title()
    url = page.url
    try:
        tree = page.accessibility.snapshot() or {}
    except Exception:
        tree = {}
    lines = [title[:70], url[:90]]
    if isinstance(tree, dict):
        _flat(tree, 0, lines)
    return "\n".join(lines)[:1500]


def go(q: str) -> str:
    return _call(_go_sync, q)


def youtube_play(term: str) -> str:
    return _call(_youtube_play_sync, term)


def back() -> str:
    return _call(_back_sync)


def tabs(cmd: str = "list") -> str:
    return _call(_tabs_sync, cmd)


def click_in(q: str) -> str:
    return _call(_click_sync, q)


def type_in(q: str) -> str:
    return _call(_type_sync, q)


def press(key: str) -> str:
    return _call(_press_sync, key)


def scroll(q: str = "down") -> str:
    return _call(_scroll_sync, q)


def snapshot() -> str:
    return _call(_snapshot_sync)


def status() -> str:
    if cdp_up():
        return "Chrome CDP 9222 ok"
    return "Chrome sem debug. Rode iniciar-chrome-debug.bat"


def dispatch(name: str, q: str = "") -> str:
    q = q or ""
    if name == "browser_go":
        return go(q)
    if name == "browser_back":
        return back()
    if name == "browser_tab":
        return tabs(q)
    if name == "browser_click":
        return click_in(q)
    if name == "browser_type":
        return type_in(q)
    if name == "browser_press":
        return press(q)
    if name == "browser_scroll":
        return scroll(q)
    if name == "browser_snap":
        return snapshot()[:120]
    return "acao browser desconhecida"
