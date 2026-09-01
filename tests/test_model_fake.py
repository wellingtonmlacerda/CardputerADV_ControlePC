"""Ollama falso: prova o parsing de ask_model e o conserto do repair().

Cada caso e uma saida crua que um modelo pequeno realmente produz,
incluindo as ruins. Checamos o que sai do outro lado.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pc_intent as I

REPLY = {"raw": ""}
SEEN = {"body": None}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        SEEN["body"] = json.loads(self.rfile.read(n).decode())
        if REPLY["raw"] == "__http500__":
            self.send_response(500)
            self.end_headers()
            return
        out = json.dumps({"message": {"content": REPLY["raw"]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 11533), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
I.OLLAMA = "http://127.0.0.1:11533"

# (rotulo, pedido, saida crua do modelo, action esperada, q esperada)
CASES = [
    ("json limpo",
     "abre o spotify", '{"action":"app","q":"spotify"}',
     # spotify NAO esta instalado -> repair deve virar busca, nao app quebrado
     "search", "spotify"),

    ("app real",
     "poe o teams na tela", '{"action":"app","q":"teams"}',
     "app", "Microsoft Teams"),

    ("prosa em volta do json",
     "abre o excel",
     'Claro! Aqui esta:\n{"action":"app","q":"excel"}\nEspero ter ajudado.',
     "app", "Excel"),

    ("frase inteira no q",
     "abre o teams por favor",
     '{"action":"app","q":"abre o teams por favor"}',
     "app", "Microsoft Teams"),

    ("navegador vindo como app",
     "abre o navegador", '{"action":"app","q":"navegador"}',
     "browser", ""),

    ("app inventado com ponto",
     "abre o uol", '{"action":"app","q":"uol.com.br"}',
     "browser_go", "uol.com.br"),

    ("youtube com frase inteira",
     "poe pra tocar aquela musica do queen que eu gosto",
     '{"action":"youtube","q":"poe pra tocar aquela musica do queen que eu gosto"}',
     "youtube", "__home__"),

    ("youtube q vazio",
     "abre o youtube", '{"action":"youtube","q":""}',
     "youtube", "__home__"),

    ("search sem q",
     "cotacao do dolar hoje", '{"action":"search","q":""}',
     "search", "cotacao do dolar hoje"),

    ("reply sem q",
     "sei la", '{"action":"reply","q":""}',
     "reply", "Nao entendi. Tenta de outro jeito."),

    ("read com ruido no q",
     "le as novidades", '{"action":"read","q":"o app do outlook"}',
     "read", "Outlook"),

    ("acao inexistente",
     "faz um cafe", '{"action":"fazer_cafe","q":"forte"}',
     None, None),

    ("json quebrado",
     "abre o teams", 'action: app, q: teams',
     None, None),

    ("resposta vazia",
     "abre o teams", '',
     None, None),

    ("http 500",
     "abre o teams", '__http500__',
     None, None),
]

ok = bad = 0
fails = []
for label, pedido, raw, exp_act, exp_q in CASES:
    REPLY["raw"] = raw
    got = I.ask_model(pedido, "fake-model")
    act, q = got if got else (None, None)
    good = (act == exp_act) and (exp_q is None or q == exp_q)
    if good:
        ok += 1
    else:
        bad += 1
        fails.append((label, pedido, exp_act, exp_q, act, q))

print(f"modelo: {ok}/{len(CASES)} ok, {bad} falhas")
for label, pedido, ea, eq, ga, gq in fails:
    print(f"  FALHA [{label}] {pedido!r}")
    print(f"        esperado {ea!r} q={eq!r}")
    print(f"        obtido   {ga!r} q={gq!r}")

# sanidade do prompt que realmente vai pro modelo
b = SEEN["body"]
print()
print("prompt enviado:")
print("  mensagens      :", len(b["messages"]), "(system + exemplos + pedido)")
print("  system chars   :", len(b["messages"][0]["content"]))
print("  temperature    :", b["options"]["temperature"])
print("  format         :", b.get("format"))
print("  keep_alive     :", b.get("keep_alive"))
srv.shutdown()
sys.exit(1 if bad else 0)
