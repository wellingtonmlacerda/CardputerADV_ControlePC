"""Conversas de verdade: troca de conversa, trava de destinatario, rascunho.

Mexe no WhatsApp aberto. NUNCA envia: usa send_message(..., enviar=False) e
apaga o rascunho no fim.

Passe dois alvos existentes na sua lista:
    py -3 tests/test_chat.py "Desenvolvimento" "91668-2582"
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_control as C
import pc_desktop as D
import pc_read as R

A = sys.argv[1] if len(sys.argv) > 1 else "Desenvolvimento"
B = sys.argv[2] if len(sys.argv) > 2 else "91668-2582"
RASCUNHO = "teste pocket deck 4917"

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


def caixa():
    return R._call(lambda: R._compose_nome(R._find_window("WhatsApp")), timeout=40)


print("0) abrindo o WhatsApp")
C.run_action("app", "whatsapp")
time.sleep(2.5)

print("1) alternar entre duas conversas, 2 voltas")
for volta in (1, 2):
    for alvo in (A, B):
        r = C.run_action("chat", "whatsapp|" + alvo)
        c = caixa().lower()
        check(f"volta {volta}: abriu {alvo}",
              r.startswith("conversa aberta") and alvo.split()[0].lower() in c,
              r[:45])

print("2) trava: recusa escrever se a conversa aberta e outra")
# aqui a conversa aberta e B; pedimos para escrever para A
r = R.send_message("WhatsApp", "NAO DEVERIA APARECER", False, pessoa=A)
check("recusou destinatario errado", "nao escrevi nada" in r, r[:60])

print("3) rascunho na conversa certa (sem enviar)")
r = R.send_message("WhatsApp", RASCUNHO, False, pessoa=B)
check("escreveu", r.startswith("escrito"), r[:50])
time.sleep(0.7)


def valor():
    def s():
        w = R._find_window("WhatsApp")
        e = R._compose(w)
        if e is None:
            return ""
        try:
            return e.GetValuePattern().Value or ""
        except Exception:
            return ""
    return R._call(s, timeout=40)


check("texto chegou no campo", RASCUNHO in valor(), repr(valor())[:40])

print("4) limpando o rascunho")
D.hotkey("ctrl a")
time.sleep(0.3)
D.press_key("delete")
time.sleep(0.7)
check("campo limpo", RASCUNHO not in valor())

print("5) a busca nao ficou suja")
def busca_valor():
    def s():
        w = R._find_window("WhatsApp")
        e = R._campo(w, "pesquis", "search")
        if e is None:
            return "<sem campo>"
        try:
            return e.GetValuePattern().Value or ""
        except Exception:
            return ""
    return R._call(s, timeout=40)


bv = busca_valor()
check("busca vazia", bv.strip() == "", repr(bv)[:40])

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
