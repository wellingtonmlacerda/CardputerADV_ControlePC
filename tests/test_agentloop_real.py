"""Laco de ferramentas com o Ollama e o PC de verdade.

Usa pedidos NAO mapeados de proposito: se caissem numa regra, o laco nem
rodava. Nenhum deles envia mensagem.

Precisa do Ollama no ar. Mexe na tela (abre apps, le janelas).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import pc_agentloop
import pc_intent
import pc_recipes

agent.AI_ON = True
agent.AI_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


PEDIDOS = [
    "quantas janelas eu tenho abertas",
    "confere se o whatsapp esta aberto",
    "qual foi a ultima coisa que chegou no outlook",
]

print("0) as frases nao podem cair nas regras (senao o laco nem roda)")
for p in PEDIDOS:
    check(f"{p[:40]} vai pro laco", pc_intent.route(p) is None)

print()
print("1) o laco resolve cada pedido")
for pedido in PEDIDOS:
    t0 = time.time()
    plano = pc_agentloop.planejar(pedido, agent.AI_MODEL)
    dt = time.time() - t0
    usou = [p.ferramenta for p in plano.passos]
    print(f"  {pedido}")
    print(f"     {dt:5.1f}s  ferramentas={usou}")
    print(f"     resposta: {plano.resumo()[:80]}")
    check("  usou alguma ferramenta e nao travou",
          bool(plano.passos) and not plano.erro, plano.erro)
    check("  nada irreversivel ficou pendente", not plano.pendentes,
          str([p.ferramenta for p in plano.pendentes]))

print()
print("2) o que deu certo virou receita e a repeticao nao chama o modelo")
pc_recipes.esquecer_tudo()
pedido = PEDIDOS[0]
plano = pc_agentloop.planejar(pedido, agent.AI_MODEL)
agent.aprender(pedido, plano)
check("gravou a receita", pc_recipes.procurar(pedido) is not None)

chamou = {"n": 0}
real = pc_agentloop._chat


def espiao(msgs, modelo):
    chamou["n"] += 1
    return real(msgs, modelo)


pc_agentloop._chat = espiao
try:
    t0 = time.time()
    act, label, q = agent.interpret(pedido)
    dt = time.time() - t0
finally:
    pc_agentloop._chat = real

print(f"     2a vez: {dt:.1f}s, chamadas ao modelo = {chamou['n']}")
check("nao chamou o modelo", chamou["n"] == 0)
check("respondeu algo util", bool(q), f"{act} / {q[:50]}")

print()
print("3) limites do visor do Cardputer")
plano = pc_agentloop.planejar(PEDIDOS[1], agent.AI_MODEL)
check("rotulo <= 39", len(plano.rotulo()) <= 39, plano.rotulo())
check("resumo <= 95", len(plano.resumo()) <= 95, str(len(plano.resumo())))

pc_recipes.esquecer_tudo()
print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
