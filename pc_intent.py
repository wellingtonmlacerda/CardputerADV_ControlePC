"""Entende o pedido falado e escolhe UMA acao do allowlist.

Ordem: regras deterministicas -> modelo local (Ollama) -> "nao entendi".

Diferenca para a versao antiga: as regras usam limite de palavra (e nao
"esta contido em"), o indice real de apps instalados decide se "abre o X" e
um programa, e o resultado do modelo NAO e mais sobrescrito por heuristica.
"""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.request import Request, urlopen

import pc_apps
from pc_control import ACTIONS

OLLAMA = "http://127.0.0.1:11434"


def norm(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower().strip())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _has(t: str, *phrases: str) -> bool:
    """Casa frase inteira respeitando limite de palavra."""
    for p in phrases:
        if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", t):
            return True
    return False


def _after(t: str, *starts: str) -> str:
    for s in starts:
        m = re.search(r"(?<!\w)" + re.escape(s) + r"\s+(.+)$", t)
        if m:
            return m.group(1).strip(" :,-")
    return ""


# --- comandos de sistema: frases curtas, sem ambiguidade -------------------

_SYSTEM: list[tuple[str, tuple[str, ...]]] = [
    ("lock", ("trava o pc", "trava a tela", "travar a tela", "bloqueia o pc",
              "bloquear a tela", "lock", "trava tudo")),
    ("volume_down", ("abaixa o volume", "abaixa o som", "diminui o volume",
                     "diminuir o volume", "menos volume", "volume baixo", "volume pra baixo",
                     "volume para baixo", "diminua o volume")),
    ("volume_up", ("aumenta o volume", "aumenta o som", "sobe o volume",
                   "sobe o som", "mais volume", "volume alto", "volume pra cima",
                   "volume para cima", "aumente o volume")),
    ("mute", ("mudo", "muta", "mute", "tira o som", "silencia", "sem som")),
    ("media_next", ("proxima faixa", "proxima musica", "proximo video",
                    "pula a musica", "skip")),
    ("media_prev", ("musica anterior", "faixa anterior", "video anterior",
                    "volta a musica")),
    ("screenshot", ("print", "tira um print", "screenshot", "captura de tela",
                    "captura a tela", "printa a tela")),
    ("desktop", ("area de trabalho", "minimiza tudo", "mostra a mesa")),
    ("taskmgr", ("gerenciador de tarefas", "task manager", "taskmgr")),
    ("settings", ("configuracoes do windows", "abre as configuracoes")),
    ("switch_win", ("alt tab", "troca de janela", "outra janela", "proxima janela")),
    ("maximize", ("maximiza", "maximizar", "tela cheia")),
    ("minimize", ("minimiza a janela", "minimizar a janela", "minimiza isso")),
    ("media", ("play pause", "pausa a musica", "pausa o video", "da um pause",
               "continua a musica", "despausa")),
]

# "quero ouvir/ver algo", nao "abrir um programa"
_PLAY = ("toca", "toque", "tocar", "reproduz", "reproduza", "poe pra tocar",
         "coloca pra tocar", "quero ouvir", "bota pra tocar", "play")

_READ = ("le", "leia", "ler", "me fala", "resume", "resuma", "o que tem em",
         "o que tem no", "o que tem na", "quais as mensagens",
         "tem mensagem", "tem mensagens", "tem email", "tem emails",
         "email novo", "emails novos", "mensagem nova", "mensagens novas",
         "novidades", "chegou")

_OPEN = ("abre", "abra", "abrir", "inicia", "inicie", "iniciar", "chama",
         "executa", "roda", "sobe", "poe", "coloca", "bota", "traz", "vai pro",
         "vai para o", "volta pro")

# "poe o teams NA TELA" - cauda que nao faz parte do nome do app
_TAIL = re.compile(r"\s+(na tela|na frente|aqui|pra mim|para mim|agora|de volta)$")

_BROWSER_WORDS = ("navegador", "browser", "chrome", "edge", "firefox")

_READ_SUBJECT = ("mensagem", "mensagens", "email", "emails", "e mail",
                 "tela", "janela", "conversa", "chat", "caixa de entrada")


def _read_target(t: str) -> str:
    """De 'le as mensagens do teams' tira 'teams'."""
    for w in ("teams", "outlook", "whatsapp", "slack", "discord", "email"):
        if _has(t, w):
            return "outlook" if w == "email" else w
    m = re.search(r"\b(?:do|da|no|na|em|de)\s+([a-z0-9 ]{2,30})$", t)
    if m:
        return m.group(1).strip()
    return ""


# --- conversas ---------------------------------------------------------------
#
# "pesquise por natan no whatsapp" NAO e uma busca no Google: e procurar uma
# pessoa dentro do app. Por isso estas regras rodam antes da regra de pesquisa.

_APPS_MSG = ("whatsapp", "whats", "zap", "teams", "telegram", "slack", "discord")

_APP_CANON = {"whats": "whatsapp", "zap": "whatsapp"}

# verbos de escolher/abrir uma conversa
_PICK = ("seleciona", "selecione", "escolhe", "escolha", "abre a conversa",
         "abre conversa", "abrir conversa", "chama", "chame", "procura",
         "procure", "pesquisa", "pesquise", "acha", "ache", "encontra",
         "fala com", "falar com", "conversa com")

# verbos de enviar
_SEND = ("manda", "mande", "mandar", "envia", "envie", "enviar", "escreve",
         "escreva", "responde", "responda", "diz", "diga", "fala", "fale")

# o que separa o destinatario do texto da mensagem
_SAYS = re.compile(
    r"\s+(?:dizendo|falando|escrito|com o texto|a mensagem|o seguinte|assim|que)\s+|"
    r"\s*[:\-]\s+"
)


def _app_in(t: str) -> str:
    for a in _APPS_MSG:
        if _has(t, a):
            return _APP_CANON.get(a, a)
    return ""


def _strip_app(t: str, app: str) -> str:
    """Tira 'no whatsapp' / 'pelo teams' da frase."""
    for a in _APPS_MSG:
        t = re.sub(r"\s*\b(no|na|pelo|pela|em|do|de)?\s*\b" + a + r"\b", " ", t)
    return " ".join(t.split())


def _clean_pessoa(s: str) -> str:
    s = s.strip()
    # tira artigos e preposicoes encadeados: "a conversa do natan" -> "natan"
    for _ in range(3):
        novo = re.sub(
            r"^(a conversa |o chat |conversa |chat |do |da |de |dos |das |"
            r"o |a |os |as |pro |pra |para o |para a |para |ao |com o |com a |com )",
            "", s)
        if novo == s:
            break
        s = novo
    s = re.sub(r"\b(no|na|pelo|pela)\b.*$", "", s).strip()
    return s.strip(" ,.:;-")[:40]


# "me diz", "quantas", "se o ..." sao perguntas sobre o PC, nao mensagens.
# Sem esta guarda, "abre o teams e me DIZ quantas conversas tem" virava um
# envio com o resto da frase como texto.
_PERGUNTA = ("me diz", "me fala", "me conta", "me informa", "me mostra",
             "quantas", "quantos", "qual", "quais", "se o", "se a", "tem?")


def _chat_intent(t: str) -> tuple[str, str] | None:
    if _has(t, *_PERGUNTA):
        return None
    app = _app_in(t)

    # 1) enviar: "manda mensagem pro natan no whatsapp dizendo bom dia"
    for v in _SEND:
        rest = _after(t, v)
        if not rest:
            continue
        rest = re.sub(r"^(uma |um )?(mensagem|msg|recado|zap)\s*", "", rest).strip()
        corpo = _strip_app(rest, app).strip()
        if not corpo:
            continue
        alvo, texto = "", ""
        m = _SAYS.search(corpo)
        if m:
            alvo, texto = corpo[:m.start()].strip(), corpo[m.end():].strip()
        elif re.match(r"^(pro|pra|para|ao|a o|com)\b", corpo):
            # "fala COM o pedro" e escolher a conversa, nao o texto da mensagem
            alvo = corpo          # so o destinatario, texto vem depois
        else:
            texto = corpo         # so o texto, conversa ja aberta
        alvo = _clean_pessoa(alvo)
        if alvo and texto:
            return "msg", f"{app or 'whatsapp'}|{alvo}|{texto[:120]}"
        if alvo:
            return "chat", f"{app or 'whatsapp'}|{alvo}"
        if texto:
            # sem destinatario so faz sentido com uma conversa ja aberta;
            # senao "manda o volume pra cima" viraria mensagem
            import pc_control

            if app or pc_control.CHAT_APP:
                return "msg", (f"{app}||{texto[:120]}" if app else texto[:120])
            return None

    # 2) escolher a conversa: "seleciona o natan no whatsapp"
    if app:
        for v in _PICK:
            rest = _after(t, v)
            if not rest:
                continue
            alvo = _clean_pessoa(_strip_app(rest, app))
            alvo = re.sub(r"^(por|pelo|pela)\s+", "", alvo).strip()
            if alvo:
                return "chat", f"{app}|{alvo}"
    return None


def route(text: str) -> tuple[str, str] | None:
    """Regra deterministica. Devolve (action, q) ou None se nao tiver certeza."""
    t = norm(text)
    if not t:
        return None

    # diagnostico pelo proprio aparelho
    if _has(t, "falhas", "o que deu errado", "deu errado", "ultimos erros"):
        return "diag", "falhas"
    if _has(t, "resumo", "como esta indo", "estatistica"):
        return "diag", "resumo"
    if _has(t, "perfis", "perfil dos apps"):
        return "diag", "perfis"

    # manutencao do que foi aprendido
    if _has(t, "esquece", "esqueca", "esquecer"):
        if _has(t, "tudo", "todas", "tudo isso"):
            return "forget", "tudo"
        return "forget", ""
    if _has(t, "o que voce aprendeu", "o que aprendeu", "lista o aprendido"):
        return "forget", "listar"

    for act, phrases in _SYSTEM:
        if _has(t, *phrases):
            return act, ""

    # ler / resumir alguma coisa
    if _has(t, *_READ) and _has(t, *_READ_SUBJECT):
        return "read", _read_target(t)

    # tocar musica / video
    for p in _PLAY:
        if t == p:
            return "media", ""
        raw = _after(t, p)
        if raw:
            vague = {"", "a musica", "o video", "ela", "isso", "aquela", "de novo",
                     "agora", "ai", "o som", "a faixa", "pra mim", "musica",
                     "video", "som", "de volta", "novamente", "ela de novo",
                     "a musica de novo", "isso de novo"}
            if raw in vague:
                return "media", ""
            rest = re.sub(r"^(na |no |ai |la )?(o |a |um |uma )?"
                          r"(video |musica |som |faixa )?(do |da |de )?",
                          "", raw).strip()
            rest = re.sub(r"\b(no|pelo|pela)\s+(youtube|yt|spotify)\b", "", rest).strip()
            if rest in vague:
                return "media", ""
            return "youtube", rest[:80]

    # conversas antes de "abrir programa": "abre a conversa do natan" e
    # "chama a maria no teams" comecam com verbos que tambem abrem apps
    conversa = _chat_intent(t)
    if conversa:
        return conversa

    # abrir programa / site
    target = ""
    for o in _OPEN:
        target = _after(t, o)
        if target:
            break
    if target:
        tgt = re.sub(r"^(o |a |os |as |um |uma |meu |minha )", "", target).strip()
        tgt = _TAIL.sub("", tgt).strip()
        if _has(tgt, *_BROWSER_WORDS):
            return "browser", ""
        if _has(tgt, "youtube", "yt"):
            return "youtube", "__home__"
        first = tgt.split()[0] if tgt.split() else ""
        if "." in first and " " not in tgt:
            return "browser_go", tgt
        if pc_apps.resolve(tgt):
            return "app", tgt
        return None  # nao e app conhecido: o modelo decide

    # pesquisa explicita
    for p in ("pesquisa por", "pesquise por", "pesquisar", "pesquisa", "pesquise",
              "procura por", "procure por", "procura", "procure", "busca por",
              "busca", "busque", "google"):
        rest = _after(t, p)
        if rest:
            rest = re.sub(r"\b(no|na)\s+(google|internet|web)\b", "", rest).strip()
            if _has(rest, "youtube", "yt"):
                rest = re.sub(r"\b(no\s+)?(youtube|yt)\b", "", rest).strip()
                return "youtube", rest[:80]
            return "search", rest[:80]

    # navegador
    if _has(t, "fecha a aba", "fechar a aba", "fecha aba"):
        return "browser_tab", "fecha"
    if _has(t, "nova aba", "abre uma aba"):
        return "browser_tab", "nova"
    if _has(t, "proxima aba", "outra aba"):
        return "browser_tab", "proxima"
    if _has(t, "aba anterior"):
        return "browser_tab", "anterior"
    if _has(t, "volta a pagina", "pagina anterior", "voltar pagina") or t in ("voltar", "volta"):
        return "browser_back", ""
    if _has(t, "desce a pagina", "rola pra baixo", "rola a pagina") or t in ("desce", "rola"):
        return "browser_scroll", "down"
    if _has(t, "sobe a pagina", "rola pra cima"):
        return "browser_scroll", "up"
    rest = _after(t, "clica em", "clique em", "clica no", "clica na")
    if rest:
        return "browser_click", rest[:60]
    rest = _after(t, "digita", "escreve", "escreva")
    if rest:
        return "browser_type", rest[:200]

    if (_has(t, "fecha a janela", "fechar a janela", "fecha isso",
             "some com essa janela", "some com isso", "tira essa janela")
            or t in ("fecha", "fechar", "feche")):
        return "close", t

    # forma curta, sem verbo: "natan teams", "teams mike", "teams, foco mike".
    # No teclado do Cardputer e assim que se digita, e sem esta regra o modelo
    # chutava focus com a frase inteira e nao achava janela nenhuma.
    app = _app_in(t)
    if app:
        resto = _strip_app(t, app)
        resto = re.sub(r"\b(foco|foca|focar|chat|conversa|com|no|na|do|da)\b",
                       " ", resto)
        resto = _clean_pessoa(" ".join(resto.split()))
        # um apelido digitado no teclado do Cardputer tem 1 ou 2 palavras.
        # Sem este limite, "confere se o whatsapp esta aberto e me diz" virava
        # uma conversa com alguem chamado "confere se o esta aberto e me diz".
        curto = len(resto.split()) <= 2 and len(resto) <= 24
        if len(resto) >= 3 and curto and not pc_apps.resolve(resto):
            return "chat", f"{app}|{resto}"

    return None


# --- modelo local -----------------------------------------------------------

SYSTEM = """Voce roteia pedidos de voz para UMA acao no Windows.
Responda so JSON: {"action":"...","q":"..."}

acoes:
app      q=nome do programa      (abrir Teams, Excel, Word, qualquer app)
read     q=nome do programa      (ler mensagens/emails/tela de um app)
focus    q=titulo da janela      (ir para uma janela ja aberta)
chat     q=app|pessoa            (abrir/selecionar a conversa com alguem)
msg      q=app|pessoa|texto      (mandar mensagem; sem pessoa se ja esta aberta)
youtube  q=nome da musica        (ou __home__ para so abrir o YouTube)
search   q=termos                (pesquisar no Google)
browser  q=""                    (abrir o navegador vazio)
browser_go q=dominio ou URL      (site especifico, ex. globo.com)
browser_click q=texto do botao
browser_type q=texto
browser_tab q=nova|fecha|proxima|anterior
browser_scroll q=down|up
browser_back q=""
media q="" | media_next | media_prev | volume_up | volume_down | mute | lock
screenshot | desktop | taskmgr | settings | switch_win | maximize | minimize | close
reply    q=resposta curta em portugues (perguntas, conversa, ou nada se aplica)

regras:
- programa instalado -> app. site -> browser_go. musica -> youtube.
- "abre o X e le as mensagens" -> read com q=X
- falar com alguem num app de conversa -> chat ou msg, NUNCA search nem reply.
- q e so o alvo, nunca a frase toda.
- VOCE NAO EXECUTA NADA, so escolhe a acao. Nunca escreva que ja abriu,
  ja mandou ou ja fez algo: quem executa e o programa, depois de voce.
- nao sabe? use reply, mas descrevendo o que falta, nunca fingindo sucesso."""

SHOTS: list[tuple[str, dict[str, str]]] = [
    ("abre o teams", {"action": "app", "q": "teams"}),
    ("abre o teams e le as mensagens", {"action": "read", "q": "teams"}),
    ("tem email novo", {"action": "read", "q": "outlook"}),
    ("toca metallica", {"action": "youtube", "q": "metallica"}),
    ("abre o youtube", {"action": "youtube", "q": "__home__"}),
    ("abre o globo.com", {"action": "browser_go", "q": "globo.com"}),
    ("quanto e 2 mais 2", {"action": "reply", "q": "Quatro."}),
    ("sobe o volume", {"action": "volume_up", "q": ""}),
    ("me ajuda com uma coisa", {"action": "reply", "q": "Claro, o que voce quer no PC?"}),
    ("some com essa janela", {"action": "close", "q": ""}),
    ("quero ver meus emails", {"action": "read", "q": "outlook"}),
    ("seleciona o natan no whatsapp", {"action": "chat", "q": "whatsapp|natan"}),
    ("manda pro natan no whatsapp que estou chegando",
     {"action": "msg", "q": "whatsapp|natan|estou chegando"}),
    ("responde bom dia", {"action": "msg", "q": "||bom dia"}),
]


def _clean(s: str) -> str:
    return "".join(" " if c in '"\\' else c for c in (s or "")).strip()[:120]


def ask_model(text: str, model: str, context: str = "",
              timeout: int = 45) -> tuple[str, str] | None:
    msgs: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    for user, out in SHOTS:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
    msgs.append({"role": "user", "content": (context + text).strip()})
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": "30m",
        "options": {"num_predict": 80, "temperature": 0, "num_ctx": 2048},
        "messages": msgs,
    }).encode()
    try:
        req = Request(OLLAMA + "/api/chat", data=body,
                      headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        content = data.get("message", {}).get("content", "") or ""
        i, j = content.find("{"), content.rfind("}")
        if i < 0 or j <= i:
            return None
        obj = json.loads(content[i:j + 1])
    except Exception as exc:  # noqa: BLE001
        print("IA erro:", exc, flush=True)
        return None

    act = str(obj.get("action", "")).strip()
    q = _clean(str(obj.get("q", "")))
    if act not in ACTIONS:
        return None
    return repair(act, q, text)


_DOMAIN = re.compile(r"^(https?://)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.I)


def repair(act: str, q: str, text: str) -> tuple[str, str]:
    """Conserta os erros tipicos de um modelo pequeno."""
    t = norm(text)
    if act in ("app", "focus", "read"):
        # dominio antes de normalizar: strip_noise comeria os pontos
        if act == "app" and _DOMAIN.match(q.strip()):
            return "browser_go", q.strip()
        q = pc_apps.strip_noise(q) or pc_apps.strip_noise(t)
        if act == "app" and _has(q, *_BROWSER_WORDS):
            return "browser", ""
        app = pc_apps.resolve(q)
        # "focus natan teams" nao e janela: e conversa. Sem isto o focus falha
        # com "janela nao encontrada" e a pessoa repete o pedido sem sair do
        # lugar, que foi exatamente o que aconteceu no uso real.
        if act in ("focus", "app") and not app:
            msg = _app_in(t)
            if msg:
                pessoa = _clean_pessoa(_strip_app(q or t, msg))
                if len(pessoa) >= 3:
                    return "chat", f"{msg}|{pessoa}"
        if act == "app" and not app:
            # modelo inventou um app: provavelmente e busca
            return "search", q or text.strip()
        if app:
            # "email" nao casa com nenhum titulo de janela; "Outlook" casa.
            q = app["name"]

    if act in ("chat", "msg"):
        partes = [p.strip() for p in q.split("|")]
        partes += [""] * (3 - len(partes))
        app, pessoa, texto = partes[0], partes[1], partes[2]
        canon = norm(app)
        if canon and canon not in ("whatsapp", "teams", "telegram", "slack", "discord"):
            # modelo pos o nome da pessoa no lugar do app
            app, pessoa, texto = _app_in(t), app, (pessoa or texto)
        if not app:
            app = _app_in(t)
        if act == "chat" and not pessoa:
            return "reply", "Diga com quem voce quer falar."
        if act == "msg" and not texto and not pessoa:
            return "reply", "Diga o que escrever."
        return act, "|".join((app, pessoa, texto)).rstrip("|")

    if act in ("browser_click", "browser_type"):
        # o alvo do clique tem de ter saido da boca da pessoa, senao e invencao
        alvo = norm(q)
        if alvo and not any(w in t for w in alvo.split() if len(w) > 2):
            return "reply", "Nao entendi. Pode repetir de outro jeito?"
    if act == "youtube":
        q = q.strip() or "__home__"
        if norm(q) == t and len(t.split()) > 4:
            q = "__home__"
    if act == "search" and not q:
        q = text.strip()
    if act == "reply":
        if not q:
            q = "Nao entendi. Tenta de outro jeito."
        elif _FINGIU.search(norm(q)):
            # o modelo nao executa nada; se ele diz que executou, e invencao
            q = "Nao consegui fazer isso. Diga o app e a pessoa."
    return act, q


# "ja mandei", "abri o whatsapp", "enviei a mensagem": sucesso inventado
_FINGIU = re.compile(
    r"\b(ja )?(mandei|enviei|abri|cliquei|escrevi|fiz|executei|realizei|"
    r"mandou|enviou|abriu|foi enviad[ao]|foi abert[ao]|pronto, )\b"
)
