#!/usr/bin/env python3
"""MCP stdio: controle real do desktop Windows (tela, mouse, teclado, janelas)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_apps  # noqa: E402
import pc_browser  # noqa: E402
import pc_read  # noqa: E402
from pc_control import ACTIONS, read_text, run_action  # noqa: E402
from pc_desktop import (  # noqa: E402
    click,
    clipboard_set,
    cursor_pos,
    desktop_summary,
    focus_or_launch,
    focus_window,
    hotkey,
    launch_app,
    list_windows,
    move_mouse,
    open_path,
    open_url,
    press_key,
    screenshot_jpeg,
    scroll,
    type_text,
    win_run,
    window_action,
)

PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
_FRAME = {"lsp": False}
INSTRUCTIONS = (
    "Controla este PC Windows e o navegador via CDP 9222. Sem shell livre.\n"
    "ABRIR: launch_app com o nome falado (resolve Teams, Outlook, WhatsApp, "
    "Excel, apps UWP). Em duvida, find_app antes.\n"
    "LER: read_window, nao screenshot. window_titles mostra o que esta aberto. "
    "Se um app WebView2 (Teams, WhatsApp) vier vazio, chame launch_app antes "
    "para ativar a janela e leia de novo.\n"
    "AGIR DENTRO DE UM APP: ui_list para ver os controles, depois ui_click e "
    "ui_type. Isso vale para mandar mensagem no Teams ou WhatsApp: "
    "launch_app -> ui_click no contato -> ui_type no campo de mensagem. "
    "NAO tente achar esses controles por foto: Teams e WhatsApp desenham tudo "
    "numa superficie unica e a coordenada nao existe na imagem.\n"
    "ENVIAR MENSAGEM: escreva com ui_type send=false, mostre o texto para a "
    "pessoa e so use send=true depois que ela confirmar.\n"
    "NAVEGADOR: browser_go / browser_click / browser_type / browser_tab / "
    "browser_scroll / browser_back / browser_snap.\n"
    "Clicar em pixel e ultimo recurso: desktop_snapshot e depois click."
)


def _ok(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}]}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def tool_snapshot() -> dict[str, Any]:
    summary = desktop_summary()
    try:
        jpeg, w, h = screenshot_jpeg()
    except Exception as exc:  # noqa: BLE001
        return _err(summary + "\n\nFoto falhou: " + str(exc))
    b64 = base64.b64encode(jpeg).decode("ascii")
    cx, cy = cursor_pos()
    text = summary + f"\nFoto {w}x{h} JPEG. Clique usando estes pixels. Cursor {cx},{cy}."
    return {
        "content": [
            {"type": "text", "text": text},
            {"type": "image", "data": b64, "mimeType": "image/jpeg"},
        ]
    }


def tool_list_windows() -> dict[str, Any]:
    wins = list_windows(25)
    if not wins:
        return _ok("nenhuma janela visivel")
    lines = [f"{i}. {w['title']}  ({w['x']},{w['y']} {w['w']}x{w['h']})" for i, w in enumerate(wins, 1)]
    return _ok("\n".join(lines))


TOOLS: dict[str, dict[str, Any]] = {
    "desktop_snapshot": {
        "description": (
            "Olha o PC: lista janelas, posicao do mouse e FOTO da tela. "
            "Use SEMPRE antes de clicar. Coordenadas do clique = pixels desta foto."
        ),
        "schema": {"type": "object", "properties": {}},
        "run": lambda **k: tool_snapshot(),
    },
    "list_windows": {
        "description": "Lista janelas visiveis com titulo e posicao.",
        "schema": {"type": "object", "properties": {}},
        "run": lambda **k: tool_list_windows(),
    },
    "focus_window": {
        "description": "Traz para frente a janela cujo titulo contenha o texto.",
        "schema": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Parte do titulo, ex. Chrome, YouTube"}},
            "required": ["title"],
        },
        "run": lambda **k: _ok(focus_window(str(k.get("title", "")))),
    },
    "window_cmd": {
        "description": "Fecha, maximiza ou minimiza uma janela pelo titulo.",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "action": {"type": "string", "enum": ["close", "maximize", "minimize", "focus"]},
            },
            "required": ["title", "action"],
        },
        "run": lambda **k: _ok(window_action(str(k.get("title", "")), str(k.get("action", "")))),
    },
    "move_mouse": {
        "description": "Move o cursor. x,y em pixels da tela (iguais ao snapshot).",
        "schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
        "run": lambda **k: _ok(move_mouse(_i(k.get("x")), _i(k.get("y")))),
    },
    "click": {
        "description": "Clica. Passe x,y da foto. button: left|right|middle. times: 1 ou 2 (duplo).",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string"},
                "times": {"type": "integer"},
            },
        },
        "run": lambda **k: _ok(
            click(
                None if k.get("x") is None else _i(k.get("x")),
                None if k.get("y") is None else _i(k.get("y")),
                str(k.get("button") or "left"),
                _i(k.get("times"), 1),
            )
        ),
    },
    "scroll": {
        "description": "Roda o mouse. amount negativo desce, positivo sobe (ex. -5).",
        "schema": {
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
        },
        "run": lambda **k: _ok(scroll(_i(k.get("amount"), -3))),
    },
    "type_text": {
        "description": (
            "Escreve na janela em foco. Use depois de focus_window ou click no campo. "
            "mode auto (padrao) cola textos longos pelo clipboard, que e exato; "
            "keys forca tecla a tecla para campos que bloqueiam colar."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "mode": {"type": "string", "enum": ["auto", "paste", "keys"]},
            },
            "required": ["text"],
        },
        "run": lambda **k: _ok(
            type_text(str(k.get("text", "")), str(k.get("mode") or "auto"))
        ),
    },
    "press_key": {
        "description": "Uma tecla: enter, tab, esc, space, backspace, delete, up, down, left, right, f4, f11.",
        "schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        "run": lambda **k: _ok(press_key(str(k.get("key", "")))),
    },
    "hotkey": {
        "description": "Atalho: ctrl c, ctrl v, ctrl s, alt f4, alt tab, win d, ctrl shift esc, win r.",
        "schema": {
            "type": "object",
            "properties": {"keys": {"type": "string", "description": "ex. ctrl s  ou alt f4"}},
            "required": ["keys"],
        },
        "run": lambda **k: _ok(hotkey(str(k.get("keys", "")))),
    },
    "launch_app": {
        "description": (
            "Abre QUALQUER app instalado pelo nome (Win32 e UWP): teams, outlook, "
            "excel, whatsapp, cursor, calculadora... Se ja estiver aberto, so traz "
            "a janela para frente. Aceita tambem caminho de .exe ou URL."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome falado do app, ex. 'teams'"},
                "force_new": {
                    "type": "boolean",
                    "description": "true abre outra instancia em vez de focar a janela existente",
                },
            },
            "required": ["name"],
        },
        "run": lambda **k: _ok(
            launch_app(str(k.get("name", "")))
            if k.get("force_new")
            else focus_or_launch(str(k.get("name", "")))
        ),
    },
    "find_app": {
        "description": (
            "Procura no indice de apps instalados e devolve os nomes parecidos. "
            "Use antes de launch_app quando nao tiver certeza do nome."
        ),
        "schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "run": lambda **k: _ok(pc_apps.suggest(str(k.get("name", "")))),
    },
    "read_window": {
        "description": (
            "Le o TEXTO de uma janela via UI Automation: emails do Outlook, "
            "conversas, campos de formulario. Melhor que screenshot quando o "
            "objetivo e ler conteudo. Se o app for WebView2 (Teams), cai para a "
            "versao web no navegador do CDP. Vazio = janela em foco."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Parte do titulo ou nome do app"},
            },
        },
        "run": lambda **k: _ok(read_text(str(k.get("title", "") or ""))[:6000]),
    },
    "window_titles": {
        "description": "Lista os titulos das janelas abertas (fonte para read_window/focus_window).",
        "schema": {"type": "object", "properties": {}},
        "run": lambda **k: _ok(pc_read.list_window_titles()),
    },
    "ui_list": {
        "description": (
            "Lista os controles REAIS de um app pelo nome (botoes, conversas, "
            "campos). Use ISTO antes de ui_click/ui_type. Em Teams e WhatsApp o "
            "desenho e todo interno, entao a foto da tela nao serve para achar "
            "onde clicar - esta arvore serve."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Parte do titulo, ex. WhatsApp, Teams, Outlook"},
                "kind": {
                    "type": "string",
                    "enum": ["click", "edit", ""],
                    "description": "click = clicaveis, edit = campos de texto, vazio = tudo",
                },
                "limit": {"type": "integer"},
            },
            "required": ["app"],
        },
        "run": lambda **k: _ok(
            pc_read.ui_list(str(k.get("app", "")), str(k.get("kind") or ""), _i(k.get("limit"), 60))
        ),
    },
    "open_chat": {
        "description": (
            "Abre a conversa com uma pessoa/grupo num app de mensagem "
            "(whatsapp, teams). Limpa a busca, acha na lista ou procura pelo "
            "nome, clica e CONFIRMA que a conversa trocou antes de responder. "
            "Use antes de send_message."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "whatsapp, teams..."},
                "person": {"type": "string", "description": "nome do contato ou grupo"},
            },
            "required": ["app", "person"],
        },
        "run": lambda **k: _ok(
            pc_read.open_chat(str(k.get("app", "")), str(k.get("person", "")))
        ),
    },
    "send_message": {
        "description": (
            "Escreve na conversa JA aberta. send=false (padrao) deixa o texto "
            "sem enviar: mostre para a pessoa e so mande depois que ela "
            "confirmar. Passe 'person' para travar o envio se a conversa "
            "aberta nao for a dela."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string"},
                "text": {"type": "string"},
                "person": {
                    "type": "string",
                    "description": "destinatario esperado; recusa se a conversa aberta for outra",
                },
                "send": {"type": "boolean", "description": "true aperta Enter e ENVIA"},
            },
            "required": ["app", "text"],
        },
        "run": lambda **k: _ok(
            pc_read.send_message(
                str(k.get("app", "")),
                str(k.get("text", "")),
                bool(k.get("send")),
                str(k.get("person") or ""),
            )
        ),
    },
    "ui_click": {
        "description": (
            "Clica num controle pelo NOME dentro de um app (contato, conversa, "
            "botao, aba). Preferir sempre a click por pixel. O nome vem de ui_list."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string"},
                "text": {"type": "string", "description": "Nome do controle, ex. 'Joao Silva'"},
            },
            "required": ["app", "text"],
        },
        "run": lambda **k: _ok(pc_read.ui_click(str(k.get("app", "")), str(k.get("text", "")))),
    },
    "ui_type": {
        "description": (
            "Foca um campo de texto do app pelo nome e escreve nele. "
            "send=false (padrao) deixa a mensagem escrita SEM enviar - use assim "
            "e confirme com a pessoa antes de enviar. send=true aperta Enter."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string"},
                "field": {
                    "type": "string",
                    "description": "Nome do campo (de ui_list kind=edit). Vazio = primeiro campo.",
                },
                "text": {"type": "string"},
                "send": {"type": "boolean", "description": "true aperta Enter e ENVIA"},
            },
            "required": ["app", "text"],
        },
        "run": lambda **k: _ok(
            pc_read.ui_type(
                str(k.get("app", "")),
                str(k.get("field") or ""),
                str(k.get("text", "")),
                bool(k.get("send")),
            )
        ),
    },
    "open_url": {
        "description": "Abre URL no navegador padrao (http/https).",
        "schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "run": lambda **k: _ok(open_url(str(k.get("url", "")))),
    },
    "open_path": {
        "description": "Abre arquivo, pasta ou .exe que exista no disco.",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "run": lambda **k: _ok(open_path(str(k.get("path", "")))),
    },
    "win_run": {
        "description": "Abre Executar (Win+R) e sobe um comando curto, ex. notepad, calc, spotify.",
        "schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        "run": lambda **k: _ok(win_run(str(k.get("command", "")))),
    },
    "clipboard_set": {
        "description": "Copia texto para a area de transferencia (depois ctrl v se quiser colar).",
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "run": lambda **k: _ok(clipboard_set(str(k.get("text", "")))),
    },
    "browser_go": {
        "description": "Navega no Chrome CDP: URL, dominio ou termos de busca.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "run": lambda **k: _ok(pc_browser.go(str(k.get("query", "")))),
    },
    "browser_click": {
        "description": "Clica num botao, link ou texto visivel da pagina (nao use JS).",
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "run": lambda **k: _ok(pc_browser.click_in(str(k.get("text", "")))),
    },
    "browser_type": {
        "description": "Digita no campo focado da pagina do Chrome.",
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "run": lambda **k: _ok(pc_browser.type_in(str(k.get("text", "")))),
    },
    "browser_tab": {
        "description": "Abas: list, nova, fecha, proxima, anterior ou numero (1,2,3).",
        "schema": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
        },
        "run": lambda **k: _ok(pc_browser.tabs(str(k.get("cmd", "list")))),
    },
    "browser_scroll": {
        "description": "Rola a pagina. query: down, up ou pixels (ex. 800).",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        "run": lambda **k: _ok(pc_browser.scroll(str(k.get("query", "down")))),
    },
    "browser_back": {
        "description": "Volta uma pagina no Chrome.",
        "schema": {"type": "object", "properties": {}},
        "run": lambda **k: _ok(pc_browser.back()),
    },
    "browser_press": {
        "description": "Tecla no Chrome: Enter, Escape, Tab, ArrowDown.",
        "schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        "run": lambda **k: _ok(pc_browser.press(str(k.get("key", "Enter")))),
    },
    "browser_snap": {
        "description": "Le titulo, URL e arvore de acessibilidade da pagina atual.",
        "schema": {"type": "object", "properties": {}},
        "run": lambda **k: _ok(pc_browser.snapshot()),
    },
    "pc_do": {
        "description": (
            "Atalhos de midia/sistema: lock, volume_up, volume_down, mute, media, media_next, "
            "media_prev, screenshot, desktop, taskmgr, settings, search, youtube, close."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["action"],
        },
        "run": lambda **k: tool_pc_do(str(k.get("action", "")), str(k.get("query", "") or "")),
    },
}


def tool_pc_do(action: str = "", query: str = "") -> dict[str, Any]:
    action = (action or "").strip()
    if action not in ACTIONS or action == "reply":
        return _err("acao bloqueada")
    try:
        return _ok(run_action(action, query or ""))
    except Exception as exc:  # noqa: BLE001
        return _err("falhou: " + str(exc))


def _tools_list() -> list[dict[str, Any]]:
    return [
        {"name": n, "description": s["description"], "inputSchema": s["schema"]}
        for n, s in TOOLS.items()
    ]


def _read_msg() -> dict[str, Any] | None:
    """Le uma mensagem JSON-RPC.

    O transporte stdio do MCP e JSON por linha. Alguns clientes antigos usam
    o framing Content-Length do LSP, entao os dois sao aceitos.
    """
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(b"{"):
            try:
                return json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                continue
        low = stripped.lower()
        if low.startswith(b"content-length:"):
            n = int(stripped.split(b":", 1)[1].strip() or b"0")
            # consome o resto dos headers ate a linha em branco
            while True:
                h = sys.stdin.buffer.readline()
                if not h or h in (b"\r\n", b"\n"):
                    break
            raw = sys.stdin.buffer.read(n) if n > 0 else b""
            if not raw:
                return None
            _FRAME["lsp"] = True
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
        # linha desconhecida: ignora


def _write_msg(obj: dict[str, Any]) -> None:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _FRAME["lsp"]:
        sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(raw) + raw)
    else:
        sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def _handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        want = str(params.get("protocolVersion") or "")
        version = want if want in SUPPORTED else PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pocketdeck-pc", "version": "3.0.0"},
                "instructions": INSTRUCTIONS,
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _tools_list()}}
    if method == "tools/call":
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if not spec:
            return {"jsonrpc": "2.0", "id": mid, "result": _err("tool desconhecida: " + name)}
        if not isinstance(args, dict):
            args = {}
        return {"jsonrpc": "2.0", "id": mid, "result": spec["run"](**args)}
    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    sys.stderr.write("pocketdeck-pc MCP v3 (apps + leitura de janelas)\n")
    sys.stderr.flush()
    while True:
        try:
            msg = _read_msg()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("mcp read: %s\n" % exc)
            sys.stderr.flush()
            continue
        if msg is None:
            break
        try:
            resp = _handle(msg)
        except Exception as exc:  # noqa: BLE001
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32000, "message": str(exc)},
            }
        if resp is not None:
            _write_msg(resp)


if __name__ == "__main__":
    main()
