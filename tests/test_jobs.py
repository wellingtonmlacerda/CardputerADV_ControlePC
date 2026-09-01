"""Trabalhos assincronos: progresso, cancelamento, e o /intent nos dois modos."""
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import pc_jobs

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("1) ciclo de vida de um trabalho")
jid = pc_jobs.criar("pedido de teste")
check("criou com id", bool(jid), jid)
check("comeca nao pronto", pc_jobs.ler(jid).get("done") is False)
pc_jobs.progresso("abrindo whatsapp", jid)
check("progresso aparece", pc_jobs.ler(jid).get("progress") == "abrindo whatsapp")
pc_jobs.concluir(jid, {"ok": True, "action": "chat", "q": "whatsapp|natan"})
lido = pc_jobs.ler(jid)
check("terminou", lido.get("done") is True)
check("trouxe o resultado", lido.get("action") == "chat", str(lido))

print("2) trabalho inexistente nao explode")
r = pc_jobs.ler("nao-existe")
check("responde erro", r.get("ok") is False, str(r))

print("3) cancelamento")
jid = pc_jobs.criar("outro")
check("cancelou", pc_jobs.cancelar(jid))
check("marcado como cancelado", pc_jobs.cancelado(jid))
pc_jobs.concluir(jid, {"ok": True})
check("depois de pronto nao cancela mais", not pc_jobs.cancelar(jid))

print("4) a thread descobre o proprio trabalho sozinha")
jid = pc_jobs.criar("thread local")
visto = {}


def trabalhador():
    pc_jobs.assumir(jid)
    pc_jobs.progresso("dentro da thread")
    visto["cancelado"] = pc_jobs.cancelado()
    pc_jobs.largar()


t = threading.Thread(target=trabalhador)
t.start()
t.join()
check("progresso sem passar o id", pc_jobs.ler(jid).get("progress") == "dentro da thread")
check("cancelado() sem id", visto.get("cancelado") is False)

print("5) /intent assincrono e sync devolvem o mesmo")
agent.PIN = "123456"
agent.AI_ON = False          # so as regras: rapido e deterministico
srv = ThreadingHTTPServer(("127.0.0.1", 8793), agent.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)


def post(path, obj):
    r = Request("http://127.0.0.1:8793" + path, data=json.dumps(obj).encode(),
                headers={"Content-Type": "application/json", "X-Token": "123456"},
                method="POST")
    with urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


PEDIDO = "sobe o volume"
sinc = post("/intent", {"q": PEDIDO, "sync": True})
check("sync responde direto", sinc.get("action") == "volume_up", str(sinc))

assinc = post("/intent", {"q": PEDIDO})
jid = assinc.get("job")
check("assincrono devolve job", bool(jid), str(assinc))
fim = time.time() + 20
resultado = {}
while time.time() < fim:
    resultado = post("/job", {"id": jid})
    if resultado.get("done"):
        break
    time.sleep(0.2)
check("terminou pelo polling", resultado.get("done") is True, str(resultado)[:60])
check("mesma acao dos dois jeitos", resultado.get("action") == sinc.get("action"),
      "%s vs %s" % (resultado.get("action"), sinc.get("action")))

print("6) confirm so no irreversivel")
casos = [("sobe o volume", False), ("abre o teams", False),
         ("manda no whatsapp pro natan: oi", True)]
for frase, esperado in casos:
    r = post("/intent", {"q": frase, "sync": True})
    check("%-34s confirm=%s" % (frase, esperado),
          bool(r.get("confirm")) is esperado, str(r.get("action")))

print("7) /cancel responde")
r = post("/cancel", {"id": "nao-existe"})
check("cancelar inexistente e falso", r.get("ok") is False)

print("8) o progresso do laco chega ao aparelho")
# modelo e ferramentas simulados: sob teste esta o caminho do progresso,
# nao a esperteza do modelo
import pc_agentloop as L
import pc_tools

respostas = [
    {"tool_calls": [{"function": {"name": "launch_app",
                                  "arguments": {"name": "whatsapp"}}}]},
    {"tool_calls": [{"function": {"name": "open_chat",
                                  "arguments": {"app": "whatsapp",
                                                "person": "Natan"}}}]},
    {"content": "Pronto."},
]
_chat_real, _exec_real = L._chat, pc_tools.executar
_route_real, _ask_real = agent.pc_intent.route, agent.pc_intent.ask_model
L._chat = lambda m, mo, timeout=40: respostas.pop(0) if respostas else {"content": "fim"}


def _exec_lento(nome, args=None):
    time.sleep(0.8)                      # o app real tambem demora
    return "conversa aberta: Natan" if nome == "open_chat" else "ok"


pc_tools.executar = _exec_lento
agent.pc_intent.route = lambda t: None   # forca a descida ate o laco
agent.pc_intent.ask_model = lambda *a, **k: None
agent.AI_ON = True
try:
    jid = post("/intent", {"q": "tarefa nova qualquer"})["job"]
    vistos = []
    fim = time.time() + 30
    while time.time() < fim:
        r = post("/job", {"id": jid})
        if r.get("done"):
            break
        p = r.get("progress", "")
        if p and (not vistos or vistos[-1] != p):
            vistos.append(p)
        time.sleep(0.25)
finally:
    L._chat, pc_tools.executar = _chat_real, _exec_real
    agent.pc_intent.route, agent.pc_intent.ask_model = _route_real, _ask_real
    agent.AI_ON = False

check("varias linhas de progresso", len(vistos) >= 2, str(vistos))
check("anuncia o app que abriu", any("whatsapp" in v for v in vistos), str(vistos))
check("anuncia a conversa", any("Natan" in v for v in vistos), str(vistos))

srv.shutdown()
print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
