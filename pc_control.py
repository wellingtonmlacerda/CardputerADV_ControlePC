"""Acoes allowlist para controlar o Windows (ADV + MCP). Sem shell livre."""

from __future__ import annotations

import ctypes
import os
import subprocess
from urllib.parse import quote_plus

ACTIONS = {
    "lock": "Travar a tela",
    "volume_up": "Aumentar volume",
    "volume_down": "Diminuir volume",
    "mute": "Mudo",
    "media": "Play/pause midia",
    "media_next": "Proxima faixa",
    "media_prev": "Faixa anterior",
    "screenshot": "Captura de tela (Win+Shift+S)",
    "desktop": "Mostrar area de trabalho",
    "taskmgr": "Gerenciador de tarefas",
    "settings": "Configuracoes do Windows",
    "switch_win": "Trocar de janela (Alt+Tab)",
    "maximize": "Maximizar janela",
    "minimize": "Minimizar janela",
    "app": "Abrir programa",
    "focus": "Ir para a janela",
    "read": "Ler a janela",
    "chat": "Abrir conversa",
    "msg": "Enviar mensagem",
    "notepad": "Abrir Bloco de notas",
    "explorer": "Abrir Explorer",
    "browser": "Abrir o navegador",
    "calc": "Abrir calculadora",
    "calc_alt": "Abrir calculadora",
    "search": "Pesquisar no Google",
    "youtube": "Pesquisar no YouTube",
    "close": "Fechar janela ou aba",
    "browser_go": "Abrir site ou busca no Chrome",
    "browser_click": "Clicar texto/botao na pagina",
    "browser_type": "Digitar no campo da pagina",
    "browser_tab": "Abas: list, nova, fecha, proxima",
    "browser_scroll": "Rolar a pagina",
    "browser_back": "Voltar no navegador",
    "browser_press": "Tecla no navegador (Enter)",
    "browser_snap": "Ler o que esta na pagina",
    "reply": "Responder",
    "plan": "Plano de acoes",
    "forget": "Esquecer o aprendido",
    "diag": "Diagnostico",
}

LAST_YT = ""
YT_OPEN = False

_RESUME_MEDIA = {
    "toca",
    "toque",
    "play",
    "pause",
    "pausa",
    "reproduz",
    "continuar",
    "continua",
    "da play",
    "dar play",
    "toca a musica",
    "toque a musica",
    "toca o video",
    "toca ela",
    "toca isso",
    "toca aquela",
    "toca de novo",
    "toca agora",
    "toca ai",
    "pausa a musica",
    "continua a musica",
    "play na musica",
    "pode tocar",
    "poe pra tocar",
}


def combo(*vks: int) -> None:
    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def key(vk: int) -> None:
    combo(vk)


def _norm(text: str) -> str:
    t = text.lower().strip()
    for a, b in (
        ("á", "a"),
        ("à", "a"),
        ("ã", "a"),
        ("â", "a"),
        ("é", "e"),
        ("ê", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ô", "o"),
        ("õ", "o"),
        ("ú", "u"),
        ("ç", "c"),
    ):
        t = t.replace(a, b)
    return t


def _is_resume_media(t: str) -> bool:
    t = _norm(t)
    if t in _RESUME_MEDIA:
        return True
    for p in ("toca ", "toque ", "play "):
        if t.startswith(p):
            rest = t[len(p) :].strip()
            if rest in (
                "a musica",
                "o video",
                "ela",
                "isso",
                "aquela",
                "de novo",
                "agora",
                "ai",
                "o som",
                "a faixa",
                "pra mim",
            ):
                return True
    return False


_WEBVIEW_APPS = ("teams", "whatsapp", "outlook novo", "new outlook")
_WEB_FALLBACK = {
    "teams": "https://teams.microsoft.com/v2/",
    "whatsapp": "https://web.whatsapp.com/",
    "outlook": "https://outlook.office.com/mail/",
}


def _web_route(q: str) -> str:
    nq = _norm(q)
    for key, url in _WEB_FALLBACK.items():
        if key in nq:
            return url
    return ""


def read_text(query: str = "") -> str:
    """Le o texto de uma janela.

    Apps nativos (Outlook classico, Bloco de notas, Explorer) saem por UI
    Automation. Apps WebView2 como o Teams nao expoem a arvore de
    acessibilidade, entao caem para a versao web no navegador do CDP.
    """
    q = (query or "").strip()
    text = ""
    err = ""
    try:
        import pc_read

        text = pc_read.read_window(q)
        if q and "janela nao encontrada" in text:
            # app fechado: abre, espera aparecer e le de novo
            import pc_desktop

            pc_desktop.focus_or_launch(q)
            if pc_read.wait_window(q, 20):
                text = pc_read.read_window(q)
    except Exception as exc:  # noqa: BLE001
        text = ""
        err = str(exc)[:60]

    useful = text and "sem texto legivel" not in text and len(text.splitlines()) > 2
    if useful:
        return text

    url = _web_route(q)
    if url:
        try:
            import pc_browser

            pc_browser.go(url)
            snap = pc_browser.snapshot()
            if snap and len(snap.splitlines()) > 2:
                return snap
            return "abri " + url + " no navegador. Faca login uma vez."
        except Exception as exc:  # noqa: BLE001
            return "app sem leitura direta e o navegador falhou: " + str(exc)[:60]

    if text:
        return text
    return "nao consegui ler" + ((": " + err) if err else "")


# Conversa aberta agora, para o pedido seguinte poder ser so "manda: bom dia".
CHAT_APP = ""
CHAT_WHO = ""

_MSG_APPS = ("whatsapp", "teams", "telegram", "slack", "discord")


def _split_alvo(q: str) -> tuple[str, str, str]:
    """Aceita 'app|pessoa|texto', 'app|pessoa' ou so 'pessoa'."""
    partes = [p.strip() for p in (q or "").split("|")]
    partes += [""] * (3 - len(partes))
    app, pessoa, texto = partes[0], partes[1], partes[2]
    if app and not pessoa and _norm(app) not in _MSG_APPS:
        app, pessoa = "", app          # veio so o nome da pessoa
    if not app:
        app = CHAT_APP or "whatsapp"
    return app, pessoa, texto


def open_chat(query: str) -> str:
    """Abre a conversa com uma pessoa. Se vier texto junto, ja manda."""
    global CHAT_APP, CHAT_WHO
    app, pessoa, texto = _split_alvo(query)
    if not pessoa:
        return "diga com quem falar"
    import pc_read

    msg = pc_read.open_chat(app, pessoa)
    if not msg.startswith("conversa aberta"):
        return msg
    CHAT_APP, CHAT_WHO = app, pessoa
    if texto:
        return pc_read.send_message(app, texto, True)
    return msg


def send_msg(query: str) -> str:
    """Manda mensagem. Sem conversa aberta, precisa de 'app|pessoa|texto'."""
    global CHAT_APP, CHAT_WHO
    app, pessoa, texto = _split_alvo(query)
    if not texto and not pessoa:
        texto = (query or "").strip()
    if not texto and pessoa:
        # so um campo e ja ha conversa aberta: o campo e o texto
        texto, pessoa = pessoa, ""
    if not texto:
        return "diga o que escrever"
    import pc_read

    if pessoa:
        r = pc_read.open_chat(app, pessoa)
        if not r.startswith("conversa aberta"):
            return r
        CHAT_APP, CHAT_WHO = app, pessoa
    elif not CHAT_APP:
        return "abra a conversa primeiro"
    return pc_read.send_message(CHAT_APP or app, texto, True)


def run_action(name: str, query: str = "") -> str:
    global LAST_YT, YT_OPEN
    q = (query or "").strip()
    if name == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "tela travada"
    if name == "volume_up":
        key(0xAF)
        return "volume +"
    if name == "volume_down":
        key(0xAE)
        return "volume -"
    if name == "mute":
        key(0xAD)
        return "mudo"
    if name == "media":
        key(0xB3)
        return "play/pause"
    if name == "media_next":
        key(0xB0)
        return "proxima faixa"
    if name == "media_prev":
        key(0xB1)
        return "faixa anterior"
    if name == "screenshot":
        combo(0x5B, 0x10, 0x53)
        return "captura"
    if name == "desktop":
        combo(0x5B, 0x44)
        return "area de trabalho"
    if name == "taskmgr":
        combo(0x11, 0x10, 0x1B)
        return "gerenciador"
    if name == "settings":
        combo(0x5B, 0x49)
        return "configuracoes"
    if name == "switch_win":
        combo(0x12, 0x09)
        return "troca janela"
    if name == "maximize":
        combo(0x5B, 0x26)
        return "maximizado"
    if name == "minimize":
        combo(0x5B, 0x28)
        return "minimizado"
    if name == "youtube":
        term = q.strip()
        if term in ("__home__", "home", "inicio", "youtube"):
            LAST_YT = ""
            YT_OPEN = True
            try:
                import pc_browser

                return pc_browser.go("https://www.youtube.com")[:80]
            except Exception as exc:
                os.startfile("https://www.youtube.com")
                return ("youtube " + str(exc)[:40])[:80]
        junk = _norm(term)
        if junk in ("vamos abrir o", "abre o", "abrir o", "o", "a", "vamos"):
            term = ""
        if not term:
            try:
                import pc_browser

                YT_OPEN = True
                return pc_browser.go("https://www.youtube.com")[:80]
            except Exception as exc:
                os.startfile("https://www.youtube.com")
                return ("youtube " + str(exc)[:40])[:80]
        if YT_OPEN and _is_resume_media(junk):
            key(0xB3)
            return "play na aba"
        LAST_YT = term
        YT_OPEN = True
        try:
            import pc_browser

            return pc_browser.youtube_play(term)[:80]
        except Exception as exc:
            os.startfile("https://www.youtube.com/results?search_query=" + quote_plus(term))
            return ("youtube busca (sem clique): " + str(exc)[:40])[:80]
    if name == "close":
        ql = q.lower()
        procs = []
        if any(k in ql for k in ("bloco", "notepad")):
            procs = ["notepad.exe"]
        elif any(k in ql for k in ("calcul", "calc")):
            procs = ["CalculatorApp.exe", "Calculator.exe", "win32calc.exe"]
        elif "spotify" in ql:
            procs = ["Spotify.exe"]
        if procs:
            for exe in procs:
                subprocess.run(
                    ["taskkill", "/IM", exe, "/F"],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            return "fechou " + (procs[0].replace(".exe", ""))
        if any(k in ql for k in ("youtube", "chrome", "navegador", "browser", "aba", "google", "edge")):
            try:
                import pc_browser

                return pc_browser.tabs("close")
            except Exception:
                combo(0x11, 0x57)
                return "fechou a aba"
        combo(0x12, 0x73)
        return "fechou a janela"
    if name == "app":
        import pc_desktop

        return pc_desktop.focus_or_launch(q)[:110]
    if name == "focus":
        import pc_desktop

        return pc_desktop.focus_window(q)[:110]
    if name == "read":
        return read_text(q)[:1500]
    if name == "diag":
        import pc_log
        import pc_profiles

        nq = _norm(q)
        if "perfi" in nq:
            return pc_profiles.listar()[:400]
        if "resumo" in nq:
            return pc_log.resumo()[:400]
        return pc_log.falhas()[:400]
    if name == "forget":
        import pc_recipes

        nq = _norm(q)
        if "listar" in nq:
            return pc_recipes.listar()[:400]
        if "tudo" in nq:
            return pc_recipes.esquecer_tudo()[:110]
        return pc_recipes.esquecer_ultima()[:110]
    if name == "chat":
        return open_chat(q)[:110]
    if name == "msg":
        return send_msg(q)[:110]
    if name == "notepad":
        subprocess.Popen(["notepad.exe"], close_fds=True)
        return "notepad"
    if name == "explorer":
        subprocess.Popen(["explorer.exe"], close_fds=True)
        return "explorer"
    if name == "browser":
        try:
            import pc_browser

            return pc_browser.go("https://www.google.com")[:80]
        except Exception:
            os.startfile("https://www.google.com")
            return "navegador"
    if name in ("calc", "calc_alt"):
        subprocess.Popen(["calc.exe"], close_fds=True)
        return "calculadora"
    if name == "search":
        term = q or "google"
        url = "https://www.google.com/search?q=" + quote_plus(term)
        try:
            import pc_browser

            return pc_browser.go(url)[:80]
        except Exception:
            os.startfile(url)
            return ("google: " + term)[:80]
    if name.startswith("browser_"):
        try:
            import pc_browser

            return pc_browser.dispatch(name, q)[:80]
        except Exception as exc:
            return ("navegador: " + str(exc))[:80]
    if name == "reply":
        return (q or "ok")[:80]
    return "acao bloqueada"
