"""Ponta a ponta de verdade: abre app fechado, escreve, le de volta, fecha."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_control as C
import pc_desktop as D
import pc_read as R

MARCA = "POCKETDECK TESTE 4917 linha um"
MARCA2 = "segunda linha do teste"

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK   " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("1) Bloco de notas estava fechado?")
antes = [w["title"] for w in D.list_windows(40)]
fechado = not any("bloco de notas" in t.lower() or "notepad" in t.lower() for t in antes)
check("nao havia janela do Bloco de notas", fechado, str(antes[:3]))

print("2) run_action('app', 'bloco de notas')")
msg = C.run_action("app", "bloco de notas")
print("     ->", msg)
titulo = R.wait_window("Bloco de Notas", 20) or R.wait_window("Notepad", 10)
check("janela apareceu", bool(titulo), repr(titulo))

if titulo:
    print("3) escrevendo conteudo conhecido")
    D.focus_window(titulo)
    time.sleep(0.6)
    D.type_text(MARCA + "\n" + MARCA2)
    time.sleep(0.6)

    print("4) run_action('read', 'bloco de notas')")
    lido = C.run_action("read", "bloco de notas")
    print("     -> %d chars" % len(lido))
    check("leu a 1a linha", MARCA in lido)
    check("leu a 2a linha", MARCA2 in lido)

    print("5) limpando e fechando")
    # Alt+F4 + "Nao salvar" nao basta: o Bloco de notas restaura a aba nao
    # salva na proxima abertura. Esvaziar antes deixa a sessao limpa.
    D.focus_window(titulo)
    time.sleep(0.6)
    D.hotkey("ctrl a")
    time.sleep(0.3)
    D.press_key("delete")
    time.sleep(0.5)
    D.hotkey("ctrl w")     # aba vazia fecha sem perguntar
    time.sleep(1.5)
    resta = [w["title"] for w in D.list_windows(40)
             if "bloco de notas" in w["title"].lower() or "notepad" in w["title"].lower()]
    check("janela fechada", not resta, str(resta))

print()
print("6) reply deixou de ser bloqueado")
check("reply em ACTIONS", "reply" in C.ACTIONS)
check("run_action reply", C.run_action("reply", "oi tudo bem") == "oi tudo bem")

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
