import os
import sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent, pc_intent as I

agent.AI_ON = True
agent.AI_MODEL = "qwen2.5:3b"

FRASES = [
    "abre o spotify",
    "qual a capital da franca",
    "oi",
    "me ajuda com uma coisa",
    "poe o teams na tela",
    "quero ver meus emails",
    "coloca uma musica boa pra trabalhar",
    "vai pro site da globo",
    "abre aquele programa de planilha",
    "some com essa janela",
    "que horas sao",
    "poe o volume no maximo",
    "quero ouvir djavan",
    "mostra o que tem no meu email",
]

# aquece o modelo (primeira chamada carrega os pesos)
t0 = time.time(); I.ask_model("oi", agent.AI_MODEL); warm = time.time() - t0
print(f"carga do modelo: {warm:.1f}s\n")

tempos = []
for f in FRASES:
    roteou = I.route(f)
    t0 = time.time()
    act, label, q = agent.interpret(f)
    dt = time.time() - t0
    if roteou is None:
        tempos.append(dt)
    origem = "regra " if roteou else "MODELO"
    print(f"  [{origem}] {f:36} -> {act:11} q={q!r:26} {dt:.1f}s")

if tempos:
    print(f"\nlatencia do modelo: min {min(tempos):.1f}s / media {sum(tempos)/len(tempos):.1f}s / max {max(tempos):.1f}s")
