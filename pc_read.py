"""Le o conteudo de texto de uma janela do Windows via UI Automation.

Serve para "abre o Teams e le as mensagens", ler Outlook, WhatsApp, etc.
UIA roda numa thread propria (COM STA), igual ao pc_browser.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from typing import Any, Callable

_JOBS: queue.Queue = queue.Queue()
_WORKER: threading.Thread | None = None
_READY = threading.Event()

# Controles que costumam carregar texto util.
_TEXTY = {
    "TextControl",
    "EditControl",
    "DocumentControl",
    "ListItemControl",
    "TreeItemControl",
    "DataItemControl",
    "HyperlinkControl",
    "HeaderItemControl",
}

# Ruido de interface que nao interessa numa leitura.
_JUNK = re.compile(
    r"^(fechar|minimizar|maximizar|restaurar|close|minimize|maximize|"
    r"pesquisar|search|mais opcoes|more options|voltar|back|avancar|"
    r"menu|barra de|toolbar|navegacao|navigation)\b",
    re.I,
)


def _worker_loop() -> None:
    import comtypes

    comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    _READY.set()
    while True:
        item = _JOBS.get()
        if item is None:
            break
        fn, args, box = item
        try:
            box["ok"] = fn(*args)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc
        box["ev"].set()


def _call(fn: Callable[..., Any], *args: Any, timeout: int = 40) -> Any:
    global _WORKER
    if _WORKER is None or not _WORKER.is_alive():
        _READY.clear()
        _WORKER = threading.Thread(target=_worker_loop, name="uia", daemon=True)
        _WORKER.start()
        _READY.wait(timeout=10)
    box: dict[str, Any] = {"ev": threading.Event(), "ok": None, "err": None}
    _JOBS.put((fn, args, box))
    if not box["ev"].wait(timeout=timeout):
        raise TimeoutError("leitura da janela demorou demais")
    if box["err"] is not None:
        raise box["err"]
    return box["ok"]


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def _titles() -> list[tuple[int, str]]:
    """(hwnd, titulo) via Win32.

    Enumerar a arvore UIA a partir da raiz custa segundos porque cada Name e
    uma chamada entre processos. A lista do Win32 sai em milissegundos e da o
    mesmo conjunto de janelas.
    """
    import pc_desktop

    return [(int(w["hwnd"]), str(w["title"])) for w in pc_desktop.list_windows(40)]


def _find_window(title: str):
    import uiautomation as auto

    q = _norm(title).lower()
    if not q:
        return auto.GetForegroundControl()
    best_hwnd, best_len = 0, 10**9
    for hwnd, name in _titles():
        low = name.lower()
        # titulo mais curto que contem o alvo = janela mais provavel
        if q in low and len(low) < best_len:
            best_hwnd, best_len = hwnd, len(low)
    if not best_hwnd:
        return None
    return auto.ControlFromHandle(best_hwnd)


def _rank(ctype: str, text: str) -> int:
    """Conteudo primeiro, navegacao por ultimo.

    O tipo de controle nao separa os dois: no Outlook novo tanto a lista de
    emails quanto o menu lateral sao ListItemControl. O que separa e o
    tamanho — uma linha de mensagem traz remetente, assunto e data; um item
    de menu e uma palavra.
    """
    n = len(text)
    if n >= 60:
        return 0
    if n >= 25:
        return 1
    if ctype in ("DataItemControl", "DocumentControl", "EditControl"):
        return 2
    return 3


def _harvest(node: Any, depth: int, out: list[tuple[int, int, str]],
             seen: set[str], limit: int) -> None:
    if depth > 22 or len(out) >= limit:
        return
    try:
        children = node.GetChildren()
    except Exception:
        return
    for ch in children:
        if len(out) >= limit:
            return
        try:
            ctype = ch.ControlTypeName
            name = _norm(ch.Name)
        except Exception:
            continue
        text = name if (ctype in _TEXTY and name) else ""
        if ctype in ("EditControl", "DocumentControl"):
            try:
                val = _norm(ch.GetValuePattern().Value)
                if len(val) > len(text):
                    text = val
            except Exception:
                pass
        if text and len(text) > 1 and not _JUNK.match(text):
            key = text.lower()[:120]
            if key not in seen:
                seen.add(key)
                out.append((_rank(ctype, text), len(out), text[:300]))
        _harvest(ch, depth + 1, out, seen, limit)


def _read_sync(title: str, limit: int) -> str:
    win = _find_window(title)
    if win is None:
        return "janela nao encontrada: " + (title or "(foco)")
    try:
        if not win.IsTopmost():
            win.SetActive()
        time.sleep(0.4)
    except Exception:
        pass
    found: list[tuple[int, int, str]] = []
    _harvest(win, 0, found, set(), limit)
    head = _norm(win.Name)[:80]
    if not found:
        return head + "\n(sem texto legivel; a janela pode estar minimizada)"
    # conteudo primeiro, navegacao por ultimo; ordem original dentro de cada nivel
    found.sort(key=lambda p: (p[0], p[1]))
    return head + "\n" + "\n".join(t for _r, _i, t in found)


# --- interagir por UI Automation, nao por pixel ------------------------------
#
# Clicar por coordenada falha justamente nos apps que importam aqui: Teams e
# WhatsApp desenham tudo dentro de uma superficie unica, entao a foto da tela
# nao diz onde estao os controles. A arvore de acessibilidade diz.

_CLICKABLE = ("ButtonControl", "ListItemControl", "DataItemControl",
              "TabItemControl", "TreeItemControl", "HyperlinkControl",
              "MenuItemControl", "CheckBoxControl", "RadioButtonControl")
_EDITABLE = ("EditControl", "DocumentControl", "ComboBoxControl")
# uma linha de conversa: DataItem no WhatsApp, TreeItem no Teams, ListItem
# em varios outros. Procurar so os dois primeiros deixava o Teams de fora.
_CONVERSA = ("DataItemControl", "ListItemControl", "TreeItemControl")

# sinais de verificacao, definidos em pc_profiles
from pc_profiles import COMPOSE, SELECIONADO, TITULO  # noqa: E402


def _walk(node: Any, depth: int, out: list[Any], limit: int) -> None:
    """Percorre em LARGURA, nao em profundidade.

    Numa conversa aberta o historico gera centenas de nos profundos. Em
    profundidade o orcamento acabava dentro das mensagens e controles rasos
    e importantes - o campo de busca, as linhas da lista - nunca eram
    alcancados. Em largura eles vem primeiro.
    """
    fila = [(node, 0)]
    while fila and len(out) < limit:
        atual, d = fila.pop(0)
        if d > 22:
            continue
        try:
            filhos = atual.GetChildren()
        except Exception:
            continue
        for ch in filhos:
            if len(out) >= limit:
                return
            out.append(ch)
            fila.append((ch, d + 1))


def _elements(win: Any, kinds: tuple[str, ...] | None, limit: int = 1500) -> list[Any]:
    todos: list[Any] = []
    _walk(win, 0, todos, limit)
    saida = []
    for e in todos:
        try:
            if kinds and e.ControlTypeName not in kinds:
                continue
            if not (e.Name or "").strip():
                continue
        except Exception:
            continue
        saida.append(e)
    return saida


def _pick(win: Any, query: str, kinds: tuple[str, ...] | None) -> Any:
    """Melhor elemento cujo Name casa com a busca. Exato > comeca com > contem."""
    q = _norm(query).lower()
    if not q:
        return None
    melhor, nota_melhor = None, -1
    for e in _elements(win, kinds):
        nome = _norm(e.Name).lower()
        if q == nome:
            nota = 3
        elif nome.startswith(q):
            nota = 2
        elif q in nome:
            nota = 1
        else:
            continue
        # empate: nome mais curto e o alvo mais provavel
        nota = nota * 1000 - min(len(nome), 999)
        if nota > nota_melhor:
            melhor, nota_melhor = e, nota
    return melhor


def _activate_win(win: Any) -> None:
    try:
        win.SetActive()
        time.sleep(0.3)
    except Exception:
        pass


def _ui_list_sync(app: str, kind: str, limit: int) -> str:
    win = _find_window(app)
    if win is None:
        return "janela nao encontrada: " + app
    kinds = {"click": _CLICKABLE, "edit": _EDITABLE}.get(kind or "", None)
    linhas = []
    for e in _elements(win, kinds):
        try:
            linhas.append(f"{e.ControlTypeName[:-7]}: {_norm(e.Name)[:70]}")
        except Exception:
            continue
        if len(linhas) >= limit:
            break
    return "\n".join(dict.fromkeys(linhas)) or "nenhum elemento desse tipo"


def _ui_click_sync(app: str, query: str) -> str:
    win = _find_window(app)
    if win is None:
        return "janela nao encontrada: " + app
    _activate_win(win)
    alvo = _pick(win, query, _CLICKABLE) or _pick(win, query, None)
    if alvo is None:
        return "nao achei na janela: " + query[:50]
    nome = _norm(alvo.Name)[:60]
    try:
        alvo.Click(simulateMove=False, waitTime=0.1)
        return "clicou: " + nome
    except Exception:
        pass
    try:
        alvo.GetInvokePattern().Invoke()
        return "acionou: " + nome
    except Exception as exc:  # noqa: BLE001
        return f"achei '{nome}' mas nao consegui clicar: {str(exc)[:50]}"


def _ui_type_sync(app: str, campo: str, valor: str, enter: bool) -> str:
    import pc_desktop

    win = _find_window(app)
    if win is None:
        return "janela nao encontrada: " + app
    _activate_win(win)
    alvo = _pick(win, campo, _EDITABLE) if campo else None
    if alvo is None and campo:
        alvo = _pick(win, campo, None)
    if alvo is None:
        edits = _elements(win, _EDITABLE)
        if not edits:
            return "nao achei campo de texto em " + app
        alvo = edits[0]
    try:
        alvo.Click(simulateMove=False, waitTime=0.1)
    except Exception:
        try:
            alvo.SetFocus()
        except Exception:
            return "nao consegui focar o campo"
    time.sleep(0.25)
    # digitar como teclado: SetValue nao dispara os eventos que Teams e
    # WhatsApp escutam, e a mensagem nao "existe" para o app.
    pc_desktop.type_text(valor, mode="keys")
    time.sleep(0.2)
    if enter:
        pc_desktop.press_key("enter")
        return f"escreveu e enviou em {app}: {valor[:40]}"
    return f"escreveu em {app} (sem enviar): {valor[:40]}"


# --- conversas: abrir com uma pessoa e mandar mensagem -----------------------

def _campo(win: Any, *palavras: str) -> Any:
    """Primeiro campo de texto cujo nome contenha uma das palavras."""
    for e in _elements(win, _EDITABLE):
        nome = _norm(e.Name).lower()
        if any(p in nome for p in palavras):
            return e
    return None


def _compose(win: Any) -> Any:
    """Caixa de escrever mensagem.

    WhatsApp: 'Digite uma mensagem para ...'. Teams: 'Digite uma mensagem'.
    Se nenhum nome bater, o ultimo campo editavel costuma ser a caixa.
    """
    alvo = _campo(win, "mensagem", "message", "digite", "escreva")
    if alvo is not None:
        return alvo
    edits = [e for e in _elements(win, _EDITABLE)
             if "pesquis" not in _norm(e.Name).lower()]
    return edits[-1] if edits else None


def _clicar(e: Any) -> bool:
    """Aciona um elemento sem depender de coordenada.

    Clicar por pixel falha em monitor secundario (a janela fica em x negativo)
    e itens de lista do WhatsApp nem expoem InvokePattern - expoem
    SelectionItem. Por isso os padroes vem primeiro e o clique e o ultimo
    recurso.
    """
    import pc_desktop as D

    try:
        e.GetScrollItemPattern().ScrollIntoView()
        time.sleep(0.15)
    except Exception:
        pass

    # Botao: Invoke e limpo e nao mexe o mouse.
    try:
        e.GetInvokePattern().Invoke()
        return True
    except Exception:
        pass

    # Item de lista: so o clique de mouse de verdade troca a conversa no
    # WhatsApp. Select() marca o item mas nao navega. O clique tem de sair
    # daqui e nao do uiautomation, que erra com monitor de x negativo.
    def _centro():
        r = e.BoundingRectangle
        return (r.left + r.right) // 2, (r.top + r.bottom) // 2

    try:
        cx, cy = _centro()
        if cx or cy:
            D.click(cx, cy)
            return True
    except Exception:
        pass

    for tentativa in (
        lambda: e.GetSelectionItemPattern().Select(),
        lambda: e.GetLegacyIAccessiblePattern().DoDefaultAction(),
        lambda: e.Click(simulateMove=False, waitTime=0.1),
    ):
        try:
            tentativa()
            return True
        except Exception:
            continue
    return False


def _compose_nome(win: Any) -> str:
    c = _compose(win)
    try:
        return _norm(c.Name).lower() if c is not None else ""
    except Exception:
        return ""


def _limpar_busca(win: Any, campos: tuple[str, ...] = ()) -> None:
    """Zera o filtro da lista de conversas.

    Uma busca com texto esconde o resto da lista - e, no WhatsApp, some ate
    com o proprio campo na arvore de acessibilidade. Sem zerar, a segunda
    tentativa de abrir uma conversa nunca acha ninguem.
    """
    import pc_desktop as D

    for _ in range(3):
        campo = _campo(win, *(campos or ("pesquis", "search", "buscar")))
        if campo is not None:
            try:
                valor = campo.GetValuePattern().Value or ""
            except Exception:
                valor = ""
            if not valor.strip():
                return
            if _clicar(campo):
                time.sleep(0.2)
                D.hotkey("ctrl a")
                time.sleep(0.15)
                D.press_key("delete")
                time.sleep(0.8)
                continue
        # campo sumiu da arvore: estado sujo, Escape costuma devolver a lista
        D.press_key("escape")
        time.sleep(1.0)


def _titulo(win: Any) -> str:
    try:
        return _norm(win.Name).lower()
    except Exception:
        return ""


def app_desconhecido(app: str) -> bool:
    """Nao e um dos perfis medidos a mao."""
    import pc_profiles

    return pc_profiles.chave(app) not in pc_profiles.CONHECIDOS


def _ir_para_conversas(win: Any, nav: tuple[str, ...] = ()) -> None:
    """Garante que a lista de conversas esta a mostra.

    O Teams abre no Calendario e ai a lista de chats simplesmente nao existe
    na arvore: sobra 1 item e nenhuma busca encontra ninguem. O WhatsApp tem
    o mesmo botao ("Conversas"), entao a mesma tentativa serve para os dois.
    """
    alvos = nav or ("chat", "conversas")
    for alvo in alvos:
        e = _pick(win, alvo, ("ButtonControl", "TabItemControl", "ListItemControl"))
        if e is None:
            continue
        nome = _norm(e.Name).lower()
        if any(nome.startswith(a.lower()) for a in alvos):
            _clicar(e)
            time.sleep(0.9)
            return


# qual sinal confirmou a ultima troca de conversa (vira perfil aprendido)
_ULTIMO_SINAL = {"v": ""}


def _selecionado(e: Any) -> bool:
    """O item da lista ficou marcado como selecionado?

    E o unico sinal confiavel no Teams: o titulo da janela nao acompanha a
    troca de aba (fica em "Calendar | ..." mesmo no Chat) e a caixa de
    escrever chama-se sempre "Digite uma mensagem", sem o nome da pessoa.
    """
    try:
        return bool(e.GetSelectionItemPattern().IsSelected)
    except Exception:
        return False


def _sondar_perfil(win: Any, app: str) -> Any:
    """Descobre o perfil de um app desconhecido e grava.

    Monta o histograma de tipos de controle e deixa pc_profiles decidir qual
    e a linha de conversa. Sem isto, app novo simplesmente nao funciona.
    """
    import pc_profiles

    hist: dict[str, int] = {}
    nomes: dict[str, list[str]] = {}
    for e in _elements(win, pc_profiles.TODOS_ITENS):
        try:
            t = e.ControlTypeName
            n = _norm(e.Name)
        except Exception:
            continue
        hist[t] = hist.get(t, 0) + 1
        nomes.setdefault(t, []).append(n)
    itens = pc_profiles.sondar(hist, nomes)
    perfil = pc_profiles.obter(app)
    perfil.itens = itens
    pc_profiles.guardar(app, perfil)
    return perfil


def _ja_aberta(win: Any, alvo: Any, pessoa: str) -> bool:
    """A conversa pedida ja e a que esta na tela."""
    quero = _norm(pessoa).lower()
    if not quero:
        return False
    if _selecionado(alvo):
        return True
    primeiro = quero.split()[0] if quero.split() else ""
    for texto in (_compose_nome(win), _titulo(win)):
        if not texto:
            continue
        if quero in texto:
            return True
        if primeiro and len(primeiro) >= 3 and primeiro in texto:
            return True
    return False


def _sinal(win: Any, alvo: Any, antes: str, antes_titulo: str,
           pessoa: str) -> str:
    """Qual sinal indica, agora, que a conversa trocou. Vazio = nenhum."""
    quero = _norm(pessoa).lower()
    primeiro = quero.split()[0] if quero.split() else ""
    if alvo is not None and _selecionado(alvo):
        return SELECIONADO
    agora = _compose_nome(win)
    if quero and quero in agora:
        return COMPOSE
    titulo = _titulo(win)
    if quero and quero in titulo:
        return TITULO
    if primeiro and len(primeiro) >= 3 and primeiro in titulo:
        return TITULO
    if agora and agora != antes:
        return COMPOSE
    if titulo and titulo != antes_titulo:
        return TITULO
    if not antes and agora:
        return COMPOSE
    return ""


def _trocou(win: Any, antes: str, antes_titulo: str, pessoa: str,
            alvo: Any = None, espera: float = 6.0) -> bool:
    """Confirma que a conversa aberta mudou depois do clique.

    Sem isso a caixa de escrever ainda e a da conversa ANTERIOR e a mensagem
    sai para a pessoa errada.

    Tres sinais, porque os apps diferem: no WhatsApp a caixa vira "Digite uma
    mensagem para <pessoa>"; no Teams a caixa e sempre "Digite uma mensagem",
    o titulo nem acompanha a aba, e o que vale e o item ficar selecionado.
    Qual funcionou fica em _ULTIMO_SINAL para virar perfil aprendido.
    """
    fim = time.time() + espera
    while time.time() < fim:
        s = _sinal(win, alvo, antes, antes_titulo, pessoa)
        if s:
            _ULTIMO_SINAL["v"] = s
            return True
        time.sleep(0.3)
    _ULTIMO_SINAL["v"] = ""
    return False


def _open_chat_sync(app: str, pessoa: str) -> str:
    import pc_desktop
    import pc_profiles

    perfil = pc_profiles.obter(app)
    pc_desktop.focus_or_launch(app)
    win = None
    for _ in range(25):
        win = _find_window(app)
        if win is not None:
            break
        time.sleep(0.5)
    if win is None:
        return "nao abriu " + app
    _activate_win(win)
    # a arvore de acessibilidade do app leva um tempo para existir depois de
    # abrir/ativar; sem esperar, a lista e a busca aparecem vazias
    fim = time.time() + 8
    while time.time() < fim:
        if _elements(win, _EDITABLE) or _elements(win, perfil.itens):
            break
        time.sleep(0.4)

    # sempre comeca do zero: um filtro de busca deixado para tras esconde a
    # lista, e o app pode estar noutra aba (o Teams abre no Calendario)
    _ir_para_conversas(win, perfil.nav)
    _limpar_busca(win, perfil.busca)

    antes = _compose_nome(win)
    antes_titulo = _titulo(win)
    alvo = _pick(win, pessoa, perfil.itens)
    # ja esta aberta? Sem isto, pedir a mesma conversa duas vezes falha com
    # "a conversa nao trocou" - porque de fato nao trocou, ja estava certa.
    if alvo is not None and _ja_aberta(win, alvo, pessoa):
        return "conversa ja aberta: " + _norm(alvo.Name)[:50]
    if alvo is None and not perfil.descoberto and app_desconhecido(app):
        # app que nunca vimos: descobre como ele expoe a lista e tenta de novo
        perfil = _sondar_perfil(win, app)
        alvo = _pick(win, pessoa, perfil.itens)
    if alvo is not None:
        nome = _norm(alvo.Name)[:50]
        if _clicar(alvo) and _trocou(win, antes, antes_titulo, pessoa, alvo):
            pc_profiles.aprender_verificacao(app, _ULTIMO_SINAL["v"])
            return "conversa aberta: " + nome

    # nao esta na lista visivel: usa a busca do proprio app
    busca = _campo(win, *perfil.busca)
    if busca is None:
        return "nao achei " + pessoa[:30] + " nem a busca de " + app
    import pc_desktop as D

    if not _clicar(busca):
        try:
            busca.SetFocus()
        except Exception:
            return "nao consegui usar a busca de " + app
    time.sleep(0.3)
    D.hotkey("ctrl a")
    time.sleep(0.15)
    D.press_key("delete")
    time.sleep(0.2)
    D.type_text(pessoa, mode="keys")
    time.sleep(1.6)

    antes = _compose_nome(win)
    alvo = _pick(win, pessoa, perfil.itens)
    if alvo is None:
        alvo = _pick(win, pessoa, pc_profiles.TODOS_ITENS)
    if alvo is None:
        _limpar_busca(win, perfil.busca)
        return "nao achei ninguem chamado " + pessoa[:30]
    nome = _norm(alvo.Name)[:50]
    if not _clicar(alvo):
        _limpar_busca(win, perfil.busca)
        return "achei " + nome + " mas nao abriu"
    trocou = _trocou(win, antes, antes_titulo, pessoa, alvo)
    _limpar_busca(win, perfil.busca)   # nao deixa o filtro sujo para a proxima
    if not trocou:
        return "cliquei em " + nome + " mas a conversa nao trocou"
    pc_profiles.aprender_verificacao(app, _ULTIMO_SINAL["v"])
    return "conversa aberta: " + nome


def _send_msg_sync(app: str, texto: str, enviar: bool, pessoa: str = "") -> str:
    import pc_desktop as D

    win = _find_window(app)
    if win is None:
        return "janela nao encontrada: " + app
    _activate_win(win)
    caixa = _compose(win)
    if caixa is None:
        return "nenhuma conversa aberta em " + app
    # trava de seguranca: nunca escrever numa conversa que nao e a pedida
    if pessoa:
        aberto = _compose_nome(win)
        if aberto and _norm(pessoa).lower() not in aberto:
            return f"a conversa aberta nao e de {pessoa[:25]} - nao escrevi nada"
    if not _clicar(caixa):
        try:
            caixa.SetFocus()
        except Exception:
            return "nao consegui focar a caixa de mensagem"
    time.sleep(0.3)
    D.type_text(texto, mode="keys")
    time.sleep(0.35)
    if not enviar:
        return "escrito (nao enviado): " + texto[:50]
    D.press_key("enter")
    time.sleep(0.4)
    return "enviado: " + texto[:55]


def open_chat(app: str, pessoa: str) -> str:
    return str(_call(_open_chat_sync, app, pessoa, timeout=90))


def send_message(app: str, texto: str, enviar: bool = True, pessoa: str = "") -> str:
    return str(_call(_send_msg_sync, app, texto, enviar, pessoa, timeout=90))


def ui_list(app: str, kind: str = "", limit: int = 60) -> str:
    return str(_call(_ui_list_sync, app, kind, limit, timeout=60))


def ui_click(app: str, query: str) -> str:
    return str(_call(_ui_click_sync, app, query, timeout=60))


def ui_type(app: str, campo: str = "", valor: str = "", enter: bool = False) -> str:
    return str(_call(_ui_type_sync, app, campo, valor, enter, timeout=60))


def _wait_window_sync(title: str, secs: int) -> str:
    end = time.time() + max(1, secs)
    while time.time() < end:
        w = _find_window(title)
        if w is not None:
            return _norm(w.Name)[:80]
        time.sleep(0.6)
    return ""


def read_window(title: str = "", limit: int = 120) -> str:
    return str(_call(_read_sync, title, limit))


def wait_window(title: str, secs: int = 20) -> str:
    return str(_call(_wait_window_sync, title, secs, timeout=secs + 10))


def list_window_titles() -> str:
    names = [_norm(t)[:70] for _h, t in _titles() if _norm(t)]
    return "\n".join(dict.fromkeys(names)) or "nenhuma janela"
