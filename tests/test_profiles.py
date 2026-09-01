"""Perfis de app: os medidos, a sondagem e o que fica aprendido."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_profiles as P

P.ARQUIVO = Path(tempfile.mkdtemp()) / "profiles.json"

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("1) os perfis medidos a mao")
w = P.obter("WhatsApp")
check("whatsapp usa DataItem", w.itens == ("DataItemControl",), str(w.itens))
check("whatsapp verifica pela caixa", w.verifica == P.COMPOSE, w.verifica)
t = P.obter("Calendar | Microsoft Teams")
check("teams usa TreeItem", t.itens == ("TreeItemControl",), str(t.itens))
check("teams verifica pela selecao", t.verifica == P.SELECIONADO, t.verifica)

print("2) app desconhecido comeca generico")
x = P.obter("SlackZinho")
check("aceita os tres tipos", x.itens == P.TODOS_ITENS, str(x.itens))
check("verificacao automatica", x.verifica == P.AUTO)

print("3) sondagem acha a linha de conversa")
# lista de conversas: muitos itens, nomes compridos (nome + previa)
hist = {"TreeItemControl": 24, "ListItemControl": 5, "DataItemControl": 0}
nomes = {
    "TreeItemControl": ["Fulano de Tal ontem: bom dia pessoal, tudo certo?"] * 24,
    "ListItemControl": ["Chat", "Equipes", "Calendario", "Chamadas", "Mais"],
}
check("escolheu TreeItem", P.sondar(hist, nomes) == ("TreeItemControl",),
      str(P.sondar(hist, nomes)))

print("4) menu curto nao e confundido com conversa")
hist2 = {"ListItemControl": 8}
nomes2 = {"ListItemControl": ["Email", "Chat", "Calendario", "Arquivos",
                             "Mais", "Ajuda", "Sair", "Inicio"]}
check("nao escolhe o menu", P.sondar(hist2, nomes2) == P.TODOS_ITENS,
      str(P.sondar(hist2, nomes2)))

print("5) poucos itens nao viram perfil")
check("3 itens minimo", P.sondar({"DataItemControl": 1},
                                 {"DataItemControl": ["um nome bem comprido aqui"]})
      == P.TODOS_ITENS)

print("6) o aprendido volta do disco")
novo = P.Perfil(itens=("ListItemControl",), verifica=P.TITULO,
                nav=("conversas",), busca=("buscar",))
P.guardar("SlackZinho", novo)
lido = P.obter("SlackZinho")
check("tipo gravado", lido.itens == ("ListItemControl",), str(lido.itens))
check("verificacao gravada", lido.verifica == P.TITULO, lido.verifica)
check("marcado como descoberto", lido.descoberto)

print("7) aprender qual sinal funcionou")
P.aprender_verificacao("SlackZinho", P.SELECIONADO)
check("trocou o sinal", P.obter("SlackZinho").verifica == P.SELECIONADO)
P.aprender_verificacao("whatsapp", P.TITULO)
check("nao sobrescreve o medido a mao",
      P.obter("whatsapp").verifica == P.COMPOSE)
P.aprender_verificacao("SlackZinho", "invalido")
check("ignora sinal invalido", P.obter("SlackZinho").verifica == P.SELECIONADO)

print("8) esquecer")
print("  ", P.esquecer("SlackZinho"))
check("voltou ao generico", P.obter("SlackZinho").verifica == P.AUTO)

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
