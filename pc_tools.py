"""Registro unico das ferramentas que o PC expoe.

Serve tres consumidores: o laco de ferramentas (pc_agentloop), o servidor MCP
e as receitas gravadas. Ter uma definicao so evita que a descricao vista pelo
modelo local divirja da vista pelo cliente MCP.

Nao ha logica nova aqui: cada ferramenta so aponta para o que ja existe em
pc_desktop, pc_apps, pc_read, pc_browser e pc_control.

As descricoes carregam a REGRA DE ORDEM de proposito. Medido com qwen2.5:3b:
sem "OBRIGATORIO antes de send_message" na descricao, ele pula o open_chat e
escreve na conversa que estiver aberta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# acoes de pc_control que mudam algo de forma dificil de desfazer
_PC_DO_IRREVERSIVEL = {"lock", "close"}


@dataclass
class Tool:
    nome: str
    descricao: str
    schema: dict[str, Any]
    executar: Callable[..., str]
    # so le, pode ser chamada a vontade pelo laco
    observa: bool = False
    # precisa destas ferramentas terem dado certo antes, no mesmo plano
    exige: tuple[str, ...] = ()
    # decide pelos argumentos se a chamada e irreversivel
    risco: Callable[[dict[str, Any]], bool] = field(default=lambda a: False)
    # oferecida ao laco local? Medido: com 12 ferramentas o qwen2.5:3b escolhe
    # ui_click "Enviar mensagem" em vez de send_message e se perde. O MCP
    # continua expondo todas, porque la o cliente e um modelo grande.
    no_laco: bool = True


def _s(**props: Any) -> dict[str, Any]:
    obrigatorios = [k for k, v in props.items() if v.pop("_req", False)]
    return {"type": "object", "properties": props, "required": obrigatorios}


def _txt(desc: str, req: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "string", "description": desc}
    if req:
        d["_req"] = True
    return d


def _bool(desc: str) -> dict[str, Any]:
    return {"type": "boolean", "description": desc}


# --- implementacoes: tudo delegado ------------------------------------------

def _launch_app(name: str = "") -> str:
    import pc_desktop

    return pc_desktop.focus_or_launch(name)


def _find_app(name: str = "") -> str:
    import pc_apps

    return pc_apps.suggest(name)


def _read_window(title: str = "") -> str:
    import pc_control

    return pc_control.read_text(title)[:2500]


def _window_titles() -> str:
    import pc_read

    return pc_read.list_window_titles()


def _open_chat(app: str = "", person: str = "") -> str:
    import pc_read

    return pc_read.open_chat(app, person)


def _send_message(app: str = "", text: str = "", send: bool = False,
                  person: str = "") -> str:
    import pc_read

    return pc_read.send_message(app, text, bool(send), person)


def _ui_list(app: str = "", kind: str = "") -> str:
    import pc_read

    return pc_read.ui_list(app, kind, 40)


def _ui_click(app: str = "", text: str = "") -> str:
    import pc_read

    return pc_read.ui_click(app, text)


def _ui_type(app: str = "", field_: str = "", text: str = "") -> str:
    import pc_read

    return pc_read.ui_type(app, field_, text, False)


def _browser_go(query: str = "") -> str:
    import pc_browser

    return pc_browser.go(query)


def _browser_snap() -> str:
    import pc_browser

    return pc_browser.snapshot()


def _pc_do(action: str = "", query: str = "") -> str:
    import pc_control

    if action not in pc_control.ACTIONS or action in ("reply", "plan"):
        return "acao bloqueada: " + action
    return pc_control.run_action(action, query)


# --- registro ----------------------------------------------------------------

TOOLS: dict[str, Tool] = {}


def _reg(t: Tool) -> None:
    TOOLS[t.nome] = t


_reg(Tool(
    nome="launch_app",
    descricao=("Abre um programa instalado pelo nome falado (teams, outlook, "
               "excel, whatsapp...). Se ja estiver aberto, so traz para frente."),
    schema=_s(name=_txt("nome do app, ex. whatsapp", req=True)),
    executar=_launch_app,
))

_reg(Tool(
    nome="find_app",
    descricao="Lista apps instalados com nome parecido. Use se launch_app nao achar.",
    schema=_s(name=_txt("nome aproximado", req=True)),
    executar=_find_app,
    observa=True,
))

_reg(Tool(
    nome="window_titles",
    descricao="Lista as janelas abertas agora. Use para saber o que ja esta na tela.",
    schema=_s(),
    executar=_window_titles,
    observa=True,
))

_reg(Tool(
    nome="read_window",
    descricao=("Le o texto de uma janela: emails, mensagens, campos. "
               "Use isto para responder perguntas sobre o que esta na tela."),
    schema=_s(title=_txt("parte do titulo ou nome do app", req=True)),
    executar=_read_window,
    observa=True,
))

_reg(Tool(
    nome="ui_list",
    descricao=("Lista os controles reais dentro de um app: conversas, botoes, "
               "campos. Use SEMPRE que precisar descobrir o nome exato de algo, "
               "e principalmente quando open_chat ou ui_click nao acharem."),
    schema=_s(
        app=_txt("nome do app", req=True),
        kind=_txt("click para clicaveis, edit para campos, vazio para tudo"),
    ),
    executar=_ui_list,
    observa=True,
))

_reg(Tool(
    nome="open_chat",
    descricao=("OBRIGATORIO antes de send_message. Abre a conversa com uma "
               "pessoa ou grupo num app de mensagem (whatsapp, teams). "
               "Confirma que a conversa trocou antes de responder."),
    schema=_s(
        app=_txt("whatsapp ou teams", req=True),
        person=_txt("nome do contato ou grupo", req=True),
    ),
    executar=_open_chat,
))

_reg(Tool(
    nome="send_message",
    descricao=("Escreve na conversa ABERTA. So funciona depois de open_chat. "
               "send=false deixa escrito sem enviar; send=true envia de vez. "
               "Passe person com o mesmo nome usado no open_chat."),
    schema=_s(
        app=_txt("whatsapp ou teams", req=True),
        text=_txt("o texto da mensagem", req=True),
        person=_txt("destinatario esperado; protege contra conversa errada"),
        send=_bool("true envia; false so deixa escrito"),
    ),
    executar=_send_message,
    exige=("open_chat",),
    risco=lambda a: bool(a.get("send")),
))

_reg(Tool(
    nome="ui_click",
    descricao=("Clica num controle pelo nome dentro de um app. O nome vem de "
               "ui_list. Prefira open_chat para abrir conversas."),
    schema=_s(
        app=_txt("nome do app", req=True),
        text=_txt("nome exato do controle", req=True),
    ),
    executar=_ui_click,
    no_laco=False,
))

_reg(Tool(
    nome="ui_type",
    descricao="Escreve num campo do app, sem enviar. Use field com o nome do campo.",
    schema=_s(
        app=_txt("nome do app", req=True),
        field_=_txt("nome do campo; vazio usa o primeiro"),
        text=_txt("o que escrever", req=True),
    ),
    executar=_ui_type,
    no_laco=False,
))

_reg(Tool(
    nome="browser_go",
    descricao="Abre um site ou uma busca no navegador. Aceita dominio, URL ou termos.",
    schema=_s(query=_txt("globo.com, uma URL, ou termos de busca", req=True)),
    executar=_browser_go,
))

_reg(Tool(
    nome="browser_snap",
    descricao="Le o titulo, a URL e o conteudo da pagina aberta no navegador.",
    schema=_s(),
    executar=_browser_snap,
    observa=True,
))

_reg(Tool(
    nome="pc_do",
    descricao=("Atalhos do sistema: volume_up, volume_down, mute, media, "
               "media_next, media_prev, screenshot, desktop, taskmgr, settings, "
               "switch_win, maximize, minimize, search, youtube, lock, close."),
    schema=_s(
        action=_txt("nome do atalho", req=True),
        query=_txt("termo, quando o atalho pedir (search, youtube)"),
    ),
    executar=_pc_do,
    risco=lambda a: str(a.get("action", "")) in _PC_DO_IRREVERSIVEL,
))


# --- consumo -----------------------------------------------------------------

def schemas_ollama() -> list[dict[str, Any]]:
    """Formato de tools do /api/chat do Ollama, so o que o laco deve ver."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.nome,
                "description": t.descricao,
                "parameters": t.schema,
            },
        }
        for t in TOOLS.values() if t.no_laco
    ]


def irreversivel(nome: str, args: dict[str, Any]) -> bool:
    t = TOOLS.get(nome)
    return bool(t and t.risco(args or {}))


def executar(nome: str, args: dict[str, Any] | None = None) -> str:
    t = TOOLS.get(nome)
    if t is None:
        return "ferramenta desconhecida: " + str(nome)
    kwargs = dict(args or {})
    # o modelo costuma mandar "field"; o parametro python e field_
    if "field" in kwargs and "field_" not in kwargs:
        kwargs["field_"] = kwargs.pop("field")
    validos = set(t.schema.get("properties", {}))
    kwargs = {k: v for k, v in kwargs.items() if k in validos}
    try:
        return str(t.executar(**kwargs))
    except TypeError as exc:
        return "argumentos errados para " + nome + ": " + str(exc)[:60]
    except Exception as exc:  # noqa: BLE001
        return "erro em " + nome + ": " + str(exc)[:80]
