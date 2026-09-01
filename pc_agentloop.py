"""Laco de ferramentas: combina o que ja existe para tarefas nao mapeadas.

Divisao entre planejar e executar, para o Cardputer confirmar uma vez so:

- `planejar()` roda o laco de verdade, mas SO com ferramentas reversiveis:
  abre app, procura contato, le tela, escreve rascunho. Ao topar numa acao
  irreversivel (enviar, travar, fechar), guarda e para. E o que faz a
  auto-validacao valer: o modelo ve o resultado real de cada passo.
- `executar_pendentes()` roda so a parte irreversivel, depois do Enter.

A auto-validacao mora AQUI, nao no modelo. Medido com qwen2.5:3b: sozinho ele
desiste no primeiro erro; com a dica certa anexada ao erro, ele investiga com
ui_list e acerta na segunda.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request, urlopen

import pc_jobs
import pc_log
import pc_tools

OLLAMA = "http://127.0.0.1:11434"

MAX_PASSOS = 8
MAX_SEGUNDOS = 45.0        # /intent no aparelho espera 60s
TIMEOUT_MODELO = 40

SYSTEM = (
    "Voce controla um PC Windows chamando ferramentas. UMA por vez.\n"
    "Regras:\n"
    "- para mandar mensagem: SEMPRE open_chat primeiro, send_message depois;\n"
    "- se uma ferramenta devolver erro, NAO desista: siga a dica do erro,\n"
    "  normalmente ui_list mostra os nomes reais;\n"
    "- nao invente que fez algo: quem executa sao as ferramentas;\n"
    "- quando a tarefa estiver feita, responda UMA frase curta em portugues."
)

# erro observado -> o que tentar em seguida. Foi isto que fez o 3b se recuperar.
DICAS: tuple[tuple[str, str], ...] = (
    ("nao achei ninguem chamado",
     "Use ui_list com kind=click para ver os nomes reais das conversas e "
     "chame open_chat de novo com o nome completo."),
    ("nao achei o app",
     "Use find_app para descobrir o nome exato do programa."),
    ("janela nao encontrada",
     "Use window_titles para ver o que esta aberto, ou launch_app para abrir."),
    ("nenhuma conversa aberta",
     "Chame open_chat com a pessoa antes de escrever."),
    ("a conversa aberta nao e de",
     "Chame open_chat com essa pessoa antes de escrever."),
    ("nao achei na janela",
     "Use ui_list para ver os nomes exatos dos controles."),
    ("nao achei ninguem",
     "Use ui_list com kind=click para ver os nomes reais."),
    ("acao bloqueada",
     "Esse atalho nao existe. Veja os nomes validos na descricao de pc_do."),
    ("a conversa nao trocou",
     "Confirme com ui_list se o nome esta certo e tente de novo."),
)


# como cada ferramenta se anuncia no visor do Cardputer
_ANUNCIO = {
    "launch_app": "abrindo {name}",
    "find_app": "procurando o app {name}",
    "window_titles": "vendo o que esta aberto",
    "read_window": "lendo {title}",
    "ui_list": "olhando {app}",
    "open_chat": "abrindo conversa com {person}",
    "send_message": "escrevendo",
    "browser_go": "abrindo {query}",
    "browser_snap": "lendo a pagina",
    "pc_do": "{action}",
}


def anunciar(nome: str, args: dict[str, Any]) -> str:
    modelo = _ANUNCIO.get(nome, nome)
    try:
        return modelo.format(**{k: str(v)[:24] for k, v in (args or {}).items()})
    except Exception:  # noqa: BLE001
        return nome


def _dica(resultado: str) -> str:
    baixo = resultado.lower()
    for marca, dica in DICAS:
        if marca in baixo:
            return " DICA: " + dica
    if baixo.startswith("erro") or "nao consegui" in baixo:
        return " DICA: tente outro caminho, ou use ui_list para se orientar."
    return ""


def _limpar_final(texto: str) -> str:
    """Nao deixa instrucao interna virar resposta para a pessoa.

    As dicas sao escritas para o modelo. Quando ele desiste, costuma devolver
    a dica como se fosse a resposta ("Use o comando ui_list com kind=click...")
    e isso apareceria no visor do Cardputer.
    """
    baixo = (texto or "").lower()
    vazamentos = ("ui_list", "open_chat", "send_message", "launch_app",
                  "window_titles", "read_window", "find_app", "browser_go",
                  "pc_do", "ui_click", "ui_type", "dica:", "ferramenta")
    if any(v in baixo for v in vazamentos):
        return "Nao consegui fazer isso. Tente pedir de outro jeito."
    return texto


@dataclass
class Passo:
    ferramenta: str
    args: dict[str, Any]
    resultado: str = ""
    executado: bool = False


@dataclass
class Plano:
    pedido: str
    passos: list[Passo] = field(default_factory=list)
    pendentes: list[Passo] = field(default_factory=list)
    final: str = ""
    erro: str = ""
    segundos: float = 0.0

    @property
    def precisa_confirmar(self) -> bool:
        return bool(self.pendentes)

    def rotulo(self) -> str:
        """Ate 39 caracteres: e o que cabe em pendingLbl_ no aparelho."""
        if self.pendentes:
            p = self.pendentes[0]
            a = p.args
            if p.ferramenta == "send_message":
                quem = a.get("person") or a.get("app") or ""
                return ("Enviar p/ " + str(quem))[:39]
            return ("Confirmar " + p.ferramenta)[:39]
        return (self.final or "Plano pronto")[:39]

    def resumo(self) -> str:
        """Ate 95 caracteres: e o que cabe em status_ no aparelho."""
        if self.erro:
            return self.erro[:95]
        if self.final:
            return self.final[:95]
        if self.passos:
            return self.passos[-1].resultado[:95]
        return "nada a fazer"


def aquecer(modelo: str) -> bool:
    """Carrega o modelo COM as ferramentas, antes do primeiro pedido.

    A primeira chamada custa ~30s so para subir os pesos e o template de tool
    calling. Se isso acontecer no meio de um pedido, o teto de tempo estoura e
    o plano morre pela metade. Aquecer na largada tira esse custo do caminho.
    """
    try:
        _chat([{"role": "system", "content": "responda ok"},
               {"role": "user", "content": "ok"}], modelo, timeout=240)
        return True
    except Exception as exc:  # noqa: BLE001
        print("IA: aquecimento falhou:", str(exc)[:70], flush=True)
        return False


def _chat(msgs: list[dict[str, Any]], modelo: str,
          timeout: int = TIMEOUT_MODELO) -> dict[str, Any]:
    body = json.dumps({
        "model": modelo,
        "stream": False,
        "tools": pc_tools.schemas_ollama(),
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": msgs,
    }).encode()
    req = Request(OLLAMA + "/api/chat", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("message", {}) or {}


def _args(chamada: dict[str, Any]) -> dict[str, Any]:
    a = chamada.get("arguments")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:  # noqa: BLE001
            a = {}
    return a if isinstance(a, dict) else {}


def _assinatura(nome: str, args: dict[str, Any]) -> str:
    return nome + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)


def planejar(pedido: str, modelo: str) -> Plano:
    """Roda o laco ate o fim, guardando o que for irreversivel."""
    plano = Plano(pedido=pedido)
    inicio = time.time()
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": pedido},
    ]
    feitas: set[str] = set()
    ok_antes: set[str] = set()
    cutucadas = 0
    ultimo_erro = ""

    for _ in range(MAX_PASSOS):
        if pc_jobs.cancelado():
            plano.erro = "cancelado"
            break
        if time.time() - inicio > MAX_SEGUNDOS:
            # so e falha se nao deu para fazer nada; com passos ou um envio
            # ja montado, o plano vale e a pessoa decide
            if not plano.passos and not plano.pendentes:
                plano.erro = "demorou demais, parei no meio"
            break
        try:
            msg = _chat(msgs, modelo)
        except Exception as exc:  # noqa: BLE001
            plano.erro = "IA falhou: " + str(exc)[:60]
            break

        chamadas = msg.get("tool_calls") or []
        if not chamadas:
            texto = " ".join(str(msg.get("content") or "").split())
            # O modelo as vezes responde de cabeca sem olhar o PC, ou repete a
            # dica do erro como se fosse resposta. Nos dois casos vale um
            # empurrao, mas so uma vez para nao virar laco.
            empurrao = ""
            if not plano.passos and cutucadas < 1:
                empurrao = ("Voce nao chamou nenhuma ferramenta. Nao responda "
                            "de cabeca: use uma ferramenta para ver o estado "
                            "real do PC e so depois responda.")
            elif ultimo_erro and cutucadas < 2:
                empurrao = ("A ultima ferramenta falhou e voce nao tentou "
                            "outra. Siga a dica do erro e chame outra "
                            "ferramenta antes de responder.")
            elif texto.rstrip().endswith("?") and cutucadas < 2:
                # perguntar nao adianta: quem confirma e a pessoa no Cardputer,
                # depois. Aqui o certo e chamar a ferramenta e deixar pendente.
                empurrao = ("Nao pergunte, execute. Chame a ferramenta que "
                            "falta. Se a acao for irreversivel, chame mesmo "
                            "assim: a pessoa confirma depois, no aparelho.")
            if empurrao:
                cutucadas += 1
                msgs.append({"role": "assistant", "content": texto})
                msgs.append({"role": "user", "content": empurrao})
                continue
            plano.final = _limpar_final(texto)
            break

        chamada = chamadas[0].get("function") or {}
        nome = str(chamada.get("name") or "")
        args = _args(chamada)
        msgs.append({"role": "assistant", "tool_calls": [chamadas[0]]})

        assin = _assinatura(nome, args)
        if assin in feitas:
            msgs.append({"role": "tool", "content":
                         "Voce ja tentou exatamente isso e nao adiantou. "
                         "Mude a abordagem ou responda o que conseguiu."})
            continue
        feitas.add(assin)

        ferramenta = pc_tools.TOOLS.get(nome)
        if ferramenta is None:
            msgs.append({"role": "tool", "content":
                         "ferramenta desconhecida: " + nome})
            continue

        faltando = [d for d in ferramenta.exige if d not in ok_antes]
        if faltando:
            msgs.append({"role": "tool", "content":
                         f"BLOQUEADO: chame {faltando[0]} antes de {nome}."})
            continue

        passo = Passo(ferramenta=nome, args=args)
        if pc_tools.irreversivel(nome, args):
            plano.pendentes.append(passo)
            msgs.append({"role": "tool", "content":
                         "Guardado para a pessoa confirmar. Nao repita esta "
                         "acao. Se a tarefa acabou, responda uma frase curta."})
            continue

        pc_jobs.progresso(anunciar(nome, args))
        t_passo = time.time()
        passo.resultado = pc_tools.executar(nome, args)
        pc_log.passo(nome, args, passo.resultado,
                     int((time.time() - t_passo) * 1000))
        passo.executado = True
        plano.passos.append(passo)
        dica = _dica(passo.resultado)
        ultimo_erro = passo.resultado if dica else ""
        if not dica:
            ok_antes.add(nome)
        msgs.append({"role": "tool", "content": passo.resultado[:1200] + dica})

    plano.segundos = time.time() - inicio
    if not plano.final and not plano.erro and not plano.pendentes:
        plano.erro = "nao consegui concluir"
    return plano


def executar_passos(pedido: str, passos: list[dict[str, Any]]) -> Plano:
    """Roda uma sequencia pronta (receita), sem chamar o modelo.

    Mesma divisao do laco: o reversivel roda agora, o irreversivel espera
    confirmacao. Economiza os segundos do modelo, nao os do app.
    """
    plano = Plano(pedido=pedido)
    inicio = time.time()
    for p in passos:
        nome = str(p.get("ferramenta") or "")
        args = dict(p.get("args") or {})
        passo = Passo(ferramenta=nome, args=args)
        if pc_tools.irreversivel(nome, args):
            plano.pendentes.append(passo)
            continue
        pc_jobs.progresso(anunciar(nome, args))
        t_passo = time.time()
        passo.resultado = pc_tools.executar(nome, args)
        pc_log.passo(nome, args, passo.resultado,
                     int((time.time() - t_passo) * 1000))
        passo.executado = True
        plano.passos.append(passo)
        if _dica(passo.resultado):
            plano.erro = passo.resultado[:95]
            plano.pendentes = []      # deu ruim: nao envia nada
            break
    plano.segundos = time.time() - inicio
    if not plano.erro and not plano.pendentes:
        plano.final = plano.passos[-1].resultado if plano.passos else "feito"
    return plano


def executar_pendentes(plano: Plano) -> str:
    """Roda so o que ficou esperando confirmacao."""
    if not plano.pendentes:
        return plano.resumo()
    saidas = []
    for passo in plano.pendentes:
        passo.resultado = pc_tools.executar(passo.ferramenta, passo.args)
        passo.executado = True
        plano.passos.append(passo)
        saidas.append(passo.resultado)
    plano.pendentes = []
    return " | ".join(saidas)[:95]


def trilha(plano: Plano) -> list[dict[str, Any]]:
    """Passos executados, no formato que as receitas gravam."""
    return [{"ferramenta": p.ferramenta, "args": p.args}
            for p in plano.passos if p.executado]
