"""Receitas: generalizar, casar de novo com outros valores, e recusar o que nao da.

Usa um arquivo temporario; nao mexe nas receitas reais.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_recipes as R

R.ARQUIVO = Path(tempfile.mkdtemp()) / "recipes.json"

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


TRILHA = [
    {"ferramenta": "open_chat", "args": {"app": "whatsapp", "person": "Natan Salgado"}},
    {"ferramenta": "send_message",
     "args": {"app": "whatsapp", "text": "bom dia", "person": "Natan Salgado", "send": True}},
]

print("1) generaliza uma frase com pessoa e texto variaveis")
print("  ", R.salvar("manda bom dia pro natan no whatsapp", TRILHA))
passos = R.procurar("manda bom dia pro natan no whatsapp")
check("casa com a frase original", passos is not None)
if passos:
    check("mesma sequencia", [p["ferramenta"] for p in passos] == ["open_chat", "send_message"])

print("2) casa com OUTRA pessoa e OUTRO texto")
passos = R.procurar("manda boa tarde pro pedro no whatsapp")
check("casou variando os dois", passos is not None)
if passos:
    a0 = passos[0]["args"]
    a1 = passos[1]["args"]
    check("pessoa virou pedro", a0.get("person") == "pedro", str(a0))
    check("texto virou boa tarde", a1.get("text") == "boa tarde", str(a1))
    check("app continua whatsapp", a0.get("app") == "whatsapp", str(a0))
    check("send preservado", a1.get("send") is True, str(a1))

print("3) frase diferente nao casa por acidente")
check("nao casa outro pedido", R.procurar("abre o excel") is None)
check("nao casa pedido parecido de outro app",
      R.procurar("le as mensagens do teams") is None)

print("4) sem nada variavel, grava como frase exata")
R.esquecer_tudo()
trilha2 = [{"ferramenta": "pc_do", "args": {"action": "screenshot"}}]
print("  ", R.salvar("tira um print da tela", trilha2))
check("acha pela frase exata", R.procurar("tira um print da tela") is not None)
check("nao acha frase diferente", R.procurar("tira um print da janela") is None)

print("5) padrao invalido nao e gravado")
ruim = R.generalizar("oi", [{"ferramenta": "pc_do", "args": {"action": "zzz"}}])
check("recusou generalizar sem trecho variavel", ruim is None, str(ruim))

print("6) esquecer")
R.esquecer_tudo()
R.salvar("manda bom dia pro natan no whatsapp", TRILHA)
R.salvar("tira um print da tela", trilha2)
print("  ", R.esquecer_ultima())
check("removeu a ultima", R.procurar("tira um print da tela") is None)
check("manteve a outra", R.procurar("manda bom dia pro natan no whatsapp") is not None)
print("  ", R.esquecer_tudo())
check("limpou tudo", R.procurar("manda bom dia pro natan no whatsapp") is None)

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
