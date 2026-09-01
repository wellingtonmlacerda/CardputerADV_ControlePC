"""Guardrails do laco de ferramentas, sem tocar em app nenhum.

O modelo e as ferramentas sao simulados: o que esta sob teste e o executor.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_agentloop as L
import pc_tools

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


def chamada(nome, **args):
    return {"tool_calls": [{"function": {"name": nome, "arguments": args}}]}


def texto(t):
    return {"content": t}


class Cenario:
    """Devolve respostas do modelo em sequencia e grava o que foi executado."""

    def __init__(self, respostas, resultados=None):
        self.respostas = list(respostas)
        self.resultados = resultados or {}
        self.executado = []
        self.vistos = []

    def chat(self, msgs, modelo):
        self.vistos.append(msgs[-1].get("content", ""))
        return self.respostas.pop(0) if self.respostas else texto("acabou")

    def executar(self, nome, args=None):
        self.executado.append((nome, dict(args or {})))
        r = self.resultados.get(nome, "ok")
        return r(args) if callable(r) else r


def rodar(cen):
    _chat, _exec = L._chat, pc_tools.executar
    L._chat = cen.chat
    pc_tools.executar = cen.executar
    try:
        return L.planejar("pedido de teste", "modelo-falso")
    finally:
        L._chat, pc_tools.executar = _chat, _exec


print("1) plano de 2 passos executa na ordem")
c = Cenario([
    chamada("launch_app", name="whatsapp"),
    chamada("open_chat", app="whatsapp", person="Natan"),
    texto("Conversa aberta."),
], {"launch_app": "abriu WhatsApp", "open_chat": "conversa aberta: Natan"})
p = rodar(c)
check("executou na ordem", [n for n, _ in c.executado] == ["launch_app", "open_chat"],
      str([n for n, _ in c.executado]))
check("guardou a frase final", p.final == "Conversa aberta.", p.final)

print("2) erro injeta dica e o laco tenta outro caminho")
c = Cenario([
    chamada("open_chat", app="whatsapp", person="natan"),
    chamada("ui_list", app="whatsapp", kind="click"),
    chamada("open_chat", app="whatsapp", person="Natan Salgado"),
    texto("Pronto."),
], {"open_chat": lambda a: ("conversa aberta: Natan Salgado"
                            if a.get("person") == "Natan Salgado"
                            else "nao achei ninguem chamado natan"),
    "ui_list": "DataItem: Natan Salgado"})
p = rodar(c)
dica_vista = any("DICA" in v and "ui_list" in v for v in c.vistos)
check("dica foi entregue ao modelo", dica_vista)
check("recuperou com o nome certo",
      ("open_chat", {"app": "whatsapp", "person": "Natan Salgado"}) in c.executado)

print("3) send_message sem open_chat e recusado pelo executor")
c = Cenario([
    chamada("send_message", app="whatsapp", text="oi", send=False),
    texto("Nao deu."),
])
p = rodar(c)
check("nao executou o envio", ("send_message" not in [n for n, _ in c.executado]),
      str(c.executado))
check("avisou que falta open_chat",
      any("BLOQUEADO" in v and "open_chat" in v for v in c.vistos))

print("4) acao irreversivel vira pendente, nao executa")
c = Cenario([
    chamada("open_chat", app="whatsapp", person="Natan"),
    chamada("send_message", app="whatsapp", text="bom dia", send=True, person="Natan"),
    texto("Pronto para enviar."),
], {"open_chat": "conversa aberta: Natan"})
p = rodar(c)
check("envio ficou pendente", len(p.pendentes) == 1 and p.pendentes[0].ferramenta == "send_message")
check("envio nao rodou", "send_message" not in [n for n, _ in c.executado])
check("precisa confirmar", p.precisa_confirmar)
check("rotulo cabe no visor", len(p.rotulo()) <= 39 and "Natan" in p.rotulo(), p.rotulo())
check("resumo cabe no visor", len(p.resumo()) <= 95, p.resumo())

print("5) chamada identica repetida e interrompida")
c = Cenario([
    chamada("ui_list", app="whatsapp"),
    chamada("ui_list", app="whatsapp"),
    chamada("ui_list", app="whatsapp"),
    texto("Desisti."),
], {"ui_list": "nada"})
p = rodar(c)
check("executou uma vez so", [n for n, _ in c.executado].count("ui_list") == 1,
      str(c.executado))
check("avisou a repeticao", any("ja tentou exatamente isso" in v for v in c.vistos))

print("6) teto de passos")
c = Cenario([chamada("window_titles") for _ in range(30)], {"window_titles": "x"})
# argumentos iguais seriam barrados pela regra 5; varia para exercitar o teto
c.respostas = [chamada("read_window", title=f"j{i}") for i in range(30)]
c.resultados = {"read_window": "conteudo"}
p = rodar(c)
check("parou no teto", len(c.executado) <= L.MAX_PASSOS, str(len(c.executado)))

print("7) executar_pendentes roda so o que ficou guardado")
c = Cenario([
    chamada("open_chat", app="whatsapp", person="Natan"),
    chamada("send_message", app="whatsapp", text="bom dia", send=True, person="Natan"),
    texto("ok"),
], {"open_chat": "conversa aberta: Natan"})
p = rodar(c)
_exec = pc_tools.executar
pc_tools.executar = c.executar
try:
    saida = L.executar_pendentes(p)
finally:
    pc_tools.executar = _exec
check("enviou na confirmacao", "send_message" in [n for n, _ in c.executado], saida[:40])
check("nao ficou nada pendente", not p.pendentes)

print("8) trilha serve de receita")
check("trilha tem os passos executados",
      [d["ferramenta"] for d in L.trilha(p)] == ["open_chat", "send_message"],
      str(L.trilha(p)))

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
