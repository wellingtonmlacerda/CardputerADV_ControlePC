"""Controle de desktop Windows para o MCP (tela, mouse, teclado, janelas)."""

from __future__ import annotations

import ctypes
import io
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
SW_RESTORE = 9
SW_MAXIMIZE = 3
SW_MINIMIZE = 6

MOD = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "windows": 0x5B,
}

VK = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f11": 0x7A,
    "f12": 0x7B,
    "printscreen": 0x2C,
}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


SHOT = {"iw": 0, "ih": 0, "sw": 0, "sh": 0}


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def virtual_screen() -> tuple[int, int, int, int]:
    """(x, y, largura, altura) de TODOS os monitores juntos.

    Um monitor a esquerda do principal tem x negativo. Limitar ao monitor
    principal deixaria o mouse preso e o clique cairia na tela errada.
    """
    return (
        user32.GetSystemMetrics(76),   # SM_XVIRTUALSCREEN
        user32.GetSystemMetrics(77),   # SM_YVIRTUALSCREEN
        user32.GetSystemMetrics(78),   # SM_CXVIRTUALSCREEN
        user32.GetSystemMetrics(79),   # SM_CYVIRTUALSCREEN
    )


def _to_screen(x: int, y: int) -> tuple[int, int]:
    iw, ih = SHOT["iw"], SHOT["ih"]
    sw, sh = SHOT["sw"], SHOT["sh"]
    if iw and ih and (iw != sw or ih != sh):
        x = int(x * sw / iw)
        y = int(y * sh / ih)
    vx, vy, vw, vh = virtual_screen()
    if vw <= 0 or vh <= 0:
        w, h = screen_size()
        vx, vy, vw, vh = 0, 0, w, h
    return (max(vx, min(int(x), vx + vw - 1)),
            max(vy, min(int(y), vy + vh - 1)))


def cursor_pos() -> tuple[int, int]:
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def move_mouse(x: int, y: int) -> str:
    x, y = _to_screen(x, y)
    user32.SetCursorPos(x, y)
    w, h = screen_size()
    return f"mouse {x},{y} (tela {w}x{h})"


def _mouse_event(down: int, up: int) -> None:
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.03)
    user32.mouse_event(up, 0, 0, 0, 0)


def click(x: int | None = None, y: int | None = None, button: str = "left", times: int = 1) -> str:
    if x is not None and y is not None:
        move_mouse(x, y)
        time.sleep(0.05)
    button = (button or "left").lower()
    pair = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button)
    if not pair:
        return "botao invalido"
    n = 1 if times < 1 else min(int(times), 3)
    for _ in range(n):
        _mouse_event(*pair)
        time.sleep(0.05)
    cx, cy = cursor_pos()
    return f"click {button} x{n} em {cx},{cy}"


def scroll(amount: int = -3) -> str:
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(amount) * 120, 0)
    return f"scroll {amount}"


def _send_vk(vk: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = 1
    inp.union.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _fill_key(slot: INPUT, vk: int, scan: int, flags: int) -> None:
    slot.type = 1
    slot.union.ki.wVk = vk
    slot.union.ki.wScan = scan
    slot.union.ki.dwFlags = flags
    slot.union.ki.time = 0
    slot.union.ki.dwExtraInfo = None


def _send_batch(chars: str) -> int:
    """Manda um bloco de caracteres numa unica chamada de SendInput.

    Devolve quantos eventos o Windows aceitou. Rajadas grandes sao engolidas
    por apps que fazem polling do input (o Bloco de notas novo e um deles),
    entao quem chama deve usar blocos pequenos.
    """
    if not chars:
        return 0
    buf = (INPUT * (len(chars) * 2))()
    i = 0
    for ch in chars:
        if ch in ("\n", "\t"):
            vk, scan, base = (VK["enter"] if ch == "\n" else VK["tab"]), 0, 0
        else:
            vk, scan, base = 0, ord(ch), KEYEVENTF_UNICODE
        _fill_key(buf[i], vk, scan, base)
        _fill_key(buf[i + 1], vk, scan, base | KEYEVENTF_KEYUP)
        i += 2
    return int(user32.SendInput(len(buf), ctypes.byref(buf), ctypes.sizeof(INPUT)))


def _send_unicode(ch: str) -> None:
    _send_batch(ch)


def _type_keys(text: str, interval_ms: int = 4) -> str:
    """Digita tecla a tecla, em blocos pequenos.

    Medido no Bloco de notas: blocos grandes chegam truncados ou com o ultimo
    caractere repetido, porque o app nao da conta da rajada. Blocos de 8 com
    uma pausa curta passam intactos.
    """
    delay = max(0, min(int(interval_ms), 80)) / 1000.0
    enviados = 0
    for i in range(0, len(text), 8):
        enviados += _send_batch(text[i:i + 8])
        if delay:
            time.sleep(delay)
    if enviados < len(text) * 2:
        return f"digitou parcial: {enviados // 2} de {len(text)} caracteres"
    return f"digitou {len(text)} caracteres"


def _type_paste(text: str) -> str:
    """Cola pelo clipboard: exato, instantaneo, imune a rajada.

    O conteudo anterior do clipboard e devolvido depois (so texto).
    """
    anterior = clipboard_get()
    clipboard_set(text)
    # o historico de clipboard do Windows processa em background: confirma
    # que o texto entrou antes de colar, senao cola o conteudo velho.
    for _ in range(20):
        time.sleep(0.05)
        if clipboard_get() == text:
            break
    else:
        return _type_keys(text)
    hotkey("ctrl v")
    time.sleep(0.35)
    if anterior:
        clipboard_set(anterior)
    return f"colou {len(text)} caracteres"


def type_text(text: str, mode: str = "auto", interval_ms: int = 4) -> str:
    """Escreve na janela em foco.

    mode: auto (cola se for longo), paste (sempre clipboard),
    keys (sempre teclado, para campos que bloqueiam colar).
    """
    text = (text or "")[:4000]
    if not text:
        return "nada para digitar"
    mode = (mode or "auto").lower()
    if mode == "paste" or (mode == "auto" and len(text) >= 12):
        try:
            return _type_paste(text)
        except Exception:  # noqa: BLE001
            pass  # sem clipboard: cai para o teclado
    return _type_keys(text, interval_ms)


def _vk_of(name: str) -> int | None:
    n = name.strip().lower()
    if n in MOD:
        return MOD[n]
    if n in VK:
        return VK[n]
    if len(n) == 1:
        c = n.upper()
        if "A" <= c <= "Z" or "0" <= c <= "9":
            return ord(c)
    return None


def press_key(name: str) -> str:
    vk = _vk_of(name)
    if vk is None:
        return "tecla desconhecida: " + name
    _send_vk(vk, False)
    time.sleep(0.02)
    _send_vk(vk, True)
    return "tecla " + name


def hotkey(combo: str) -> str:
    parts = [p.strip() for p in (combo or "").replace("+", " ").replace("-", " ").split() if p.strip()]
    if not parts or len(parts) > 4:
        return "atalho invalido"
    vks: list[int] = []
    for p in parts:
        vk = _vk_of(p)
        if vk is None:
            return "tecla desconhecida: " + p
        vks.append(vk)
    for vk in vks:
        _send_vk(vk, False)
        time.sleep(0.02)
    for vk in reversed(vks):
        _send_vk(vk, True)
        time.sleep(0.02)
    return "atalho " + "+".join(parts)


def _window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value.strip()


def list_windows(limit: int = 25) -> list[dict[str, int | str]]:
    found: list[dict[str, int | str]] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title or title in ("Program Manager",):
            return True
        rc = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title[:80],
                "x": int(rc.left),
                "y": int(rc.top),
                "w": int(rc.right - rc.left),
                "h": int(rc.bottom - rc.top),
            }
        )
        return len(found) < max(1, min(int(limit), 40))

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def _activate(hwnd: int, timeout: float = 2.5) -> bool:
    """Traz a janela para frente e SO retorna quando ela e mesmo a ativa.

    Um sleep fixo nao serve: com a maquina carregada a ativacao demora, e quem
    digitar em seguida escreve na janela errada. O Windows tambem recusa
    SetForegroundWindow as vezes, entao a chamada e repetida.
    """
    fim = time.time() + timeout
    user32.ShowWindow(hwnd, SW_RESTORE)
    while time.time() < fim:
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() == hwnd:
            time.sleep(0.05)
            return True
        time.sleep(0.08)
    return user32.GetForegroundWindow() == hwnd


def focus_window(query: str) -> str:
    q = (query or "").strip().lower()
    if not q:
        return "informe o titulo da janela"
    for w in list_windows(40):
        if q in str(w["title"]).lower():
            titulo = str(w["title"])
            if _activate(int(w["hwnd"])):
                return "foco: " + titulo
            return "nao consegui trazer para frente: " + titulo[:50]
    return "janela nao encontrada: " + query


def window_action(query: str, action: str) -> str:
    q = (query or "").strip().lower()
    action = (action or "").lower()
    for w in list_windows(40):
        if q and q not in str(w["title"]).lower():
            continue
        if not q and action != "foreground":
            continue
        hwnd = int(w["hwnd"])
        if action == "close":
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return "fechou: " + str(w["title"])
        if action == "maximize":
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            return "max: " + str(w["title"])
        if action == "minimize":
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            return "min: " + str(w["title"])
        if action == "focus":
            return focus_window(str(w["title"]))
        break
    return "janela nao encontrada"


def screenshot_jpeg(max_width: int = 1280, quality: int = 55) -> tuple[bytes, int, int]:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("instale Pillow: pip install Pillow") from exc
    img = ImageGrab.grab(all_screens=False)
    sw, sh = img.size
    SHOT["sw"], SHOT["sh"] = sw, sh
    w, h = sw, sh
    if w > max_width:
        nh = int(h * (max_width / w))
        img = img.resize((max_width, nh))
        w, h = img.size
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=int(quality), optimize=True)
    SHOT["iw"], SHOT["ih"] = w, h
    return buf.getvalue(), w, h


def open_url(url: str) -> str:
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return "url precisa comecar com http"
    os.startfile(u)
    return "abriu " + u[:80]


def open_path(path: str) -> str:
    p = Path((path or "").strip().strip('"'))
    if not p.exists():
        return "caminho nao existe"
    os.startfile(str(p))
    return "abriu " + str(p)[:80]


_APP_HINTS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "notepad": ["notepad.exe"],
    "explorer": ["explorer.exe"],
    "calc": ["calc.exe"],
    "spotify": [
        str(Path.home() / r"AppData\Roaming\Spotify\Spotify.exe"),
    ],
    "discord": [
        str(Path.home() / r"AppData\Local\Discord\Update.exe"),
    ],
    "code": [
        str(Path.home() / r"AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "cursor": [
        str(Path.home() / r"AppData\Local\Programs\cursor\Cursor.exe"),
    ],
}


def launch_app(name: str) -> str:
    """Abre qualquer app instalado (Win32, UWP/MSIX) pelo nome falado."""
    key = (name or "").strip()
    if not key:
        return "informe o app"
    if key.lower().startswith(("http://", "https://")):
        return open_url(key)
    p = Path(key.strip('"'))
    if p.exists():
        os.startfile(str(p))
        return "abriu " + str(p)[:80]
    # caminho fixo conhecido primeiro (mais rapido que indexar)
    for hint in _APP_HINTS.get(key.lower(), []):
        hp = Path(hint)
        if hp.exists():
            if hp.name.lower() == "update.exe" and "discord" in key.lower():
                subprocess.Popen([str(hp), "--processStart", "Discord.exe"], close_fds=True)
            else:
                os.startfile(str(hp))
            return "abriu " + key
    import pc_apps

    return pc_apps.launch(key)


# Palavras genericas demais para identificar uma janela sozinhas.
_WEAK = {"microsoft", "windows", "google", "app", "aplicativo", "new", "novo",
         "desktop", "for", "the", "studio", "visual"}


def _needles(name: str) -> list[str]:
    """Alvos de busca, do mais especifico para o menos."""
    import pc_apps

    out: list[str] = []
    app = pc_apps.resolve(name)
    asked = pc_apps.strip_noise(name)
    for n in (pc_apps.norm(app["name"]) if app else "", asked):
        if n and n not in out:
            out.append(n)
    for n in list(out):
        for tok in n.split():
            if len(tok) >= 4 and tok not in _WEAK and tok not in out:
                out.append(tok)
    return out


def focus_or_launch(name: str) -> str:
    """Se o app ja tem janela aberta, traz pra frente. Se nao, abre."""
    import pc_apps

    wins = list_windows(40)
    # tenta o alvo mais especifico contra todas as janelas antes de afrouxar
    for needle in _needles(name):
        for w in wins:
            if needle in pc_apps.norm(str(w["title"])):
                _activate(int(w["hwnd"]))
                return "foco: " + str(w["title"])[:60]
    return launch_app(name)


def win_run(command: str) -> str:
    """Win+R e executa um comando curto (sem encadeamento)."""
    cmd = (command or "").strip()
    if not cmd or len(cmd) > 80:
        return "comando Win+R invalido"
    bad = ("&", "|", ">", "<", "^", "\n", "&&", "||")
    if any(b in cmd for b in bad):
        return "Win+R bloqueou caracteres de shell"
    hotkey("win r")
    time.sleep(0.35)
    type_text(cmd, 6)
    time.sleep(0.1)
    press_key("enter")
    return "Win+R: " + cmd


def clipboard_get() -> str:
    """Texto que esta no clipboard, ou vazio."""
    cf_unicode = 13
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    if not user32.OpenClipboard(None):
        return ""
    try:
        h = user32.GetClipboardData(cf_unicode)
        if not h:
            return ""
        p = kernel32.GlobalLock(ctypes.c_void_p(h))
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(h))
    except Exception:  # noqa: BLE001
        return ""
    finally:
        user32.CloseClipboard()


def clipboard_set(text: str) -> str:
    """Handles do Windows sao ponteiros: sem c_void_p o ctypes trunca em 32 bits."""
    text = (text or "")[:8000]
    cf_unicode = 13
    gmem_moveable = 0x0002
    data = text.encode("utf-16le") + b"\x00\x00"
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    h = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not h:
        return "sem memoria para o clipboard"
    p = kernel32.GlobalLock(ctypes.c_void_p(h))
    if not p:
        return "nao travou a memoria do clipboard"
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(ctypes.c_void_p(h))
    if not user32.OpenClipboard(None):
        return "nao abriu clipboard"
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(cf_unicode, ctypes.c_void_p(h))
    finally:
        user32.CloseClipboard()
    return f"clipboard {len(text)} chars"


def desktop_summary() -> str:
    w, h = screen_size()
    cx, cy = cursor_pos()
    wins = list_windows(15)
    lines = [f"Tela {w}x{h}  mouse {cx},{cy}", "Janelas:"]
    for i, win in enumerate(wins, 1):
        lines.append(f"{i}. {win['title']} @ {win['x']},{win['y']} {win['w']}x{win['h']}")
    return "\n".join(lines)
