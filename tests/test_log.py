"""Registro de falhas: grava, rotaciona por dia e resume."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_log as L

L.PASTA = Path(tempfile.mkdtemp())

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("1) grava pedidos")
L.pedido("abre o teams", "regra", "app", "teams", True, 120, "abriu Teams")
L.pedido("natan teams", "regra", "chat", "teams|natan", False, 4300,
         "cliquei mas a conversa nao trocou")
L.pedido("sobe o volume", "regra", "volume_up", "", True, 15, "volume +")
arqs = list(L.PASTA.glob("agent-*.jsonl"))
check("criou o arquivo do dia", len(arqs) == 1, str([a.name for a in arqs]))
check("uma linha por pedido",
      len(arqs[0].read_text(encoding="utf-8").strip().splitlines()) == 3)

print("2) falhas traz so o que deu errado")
f = L.falhas()
check("mostra a falha", "natan teams" in f, f)
check("nao mostra os sucessos", "sobe o volume" not in f and "abre o teams" not in f, f)

print("3) resumo conta certo")
r = L.resumo()
check("3 pedidos", "3 pedidos" in r, r)
check("1 falha", "1 falha" in r, r)
check("cita a camada", "regra 3" in r, r)

print("4) passos do laco tambem entram")
L.passo("open_chat", {"app": "teams", "person": "natan"}, "conversa aberta", 3200)
linhas = arqs[0].read_text(encoding="utf-8").strip().splitlines()
check("passo gravado", any('"tipo": "passo"' in x for x in linhas))
check("passo nao conta como pedido", "3 pedidos" in L.resumo(), L.resumo())

print("5) rotacao apaga o que passou de 7 dias")
velho = L.PASTA / ("agent-%s.jsonl" %
                   (datetime.now() - timedelta(days=30)).strftime("%Y%m%d"))
velho.write_text('{"tipo":"pedido"}\n', encoding="utf-8")
recente = L.PASTA / ("agent-%s.jsonl" %
                     (datetime.now() - timedelta(days=2)).strftime("%Y%m%d"))
recente.write_text('{"tipo":"pedido"}\n', encoding="utf-8")
L.pedido("qualquer coisa", "regra", "reply", "", True, 5, "ok")
check("apagou o de 30 dias", not velho.exists())
check("manteve o de 2 dias", recente.exists())

print("6) sem registros nao quebra")
L.PASTA = Path(tempfile.mkdtemp())
check("falhas vazio", "nenhuma falha" in L.falhas(), L.falhas())
check("resumo vazio", "sem registros" in L.resumo(), L.resumo())

print("7) erro de escrita nao derruba o agente")
L.PASTA = Path("Z:/nao/existe/mesmo")
try:
    L.pedido("x", "y", "z", "", True, 1, "")
    check("engoliu o erro", True)
except Exception as exc:  # noqa: BLE001
    check("engoliu o erro", False, str(exc)[:50])

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
