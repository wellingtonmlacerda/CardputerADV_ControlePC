"""Impede que o registro de ferramentas e o MCP se contradigam.

O MCP tem tools a mais (clique por pixel, hotkey) e parametros a mais em
algumas, porque o cliente dele e um modelo grande. O que NAO pode acontecer e
uma ferramenta existir nos dois lugares com contratos diferentes: o laco local
aprenderia um jeito e o MCP outro.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_server
import pc_tools

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("  " + detalhe if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("1) toda ferramenta do laco existe no MCP")
for nome in pc_tools.TOOLS:
    check(f"{nome} no MCP", nome in mcp_server.TOOLS)

print("2) parametros obrigatorios batem")
for nome, t in pc_tools.TOOLS.items():
    m = mcp_server.TOOLS.get(nome)
    if not m:
        continue
    props_mcp = set(m["schema"].get("properties", {}))
    props_reg = set(t.schema.get("properties", {}))
    # field_ no registro corresponde a field no MCP
    props_reg = {"field" if p == "field_" else p for p in props_reg}
    faltando = props_reg - props_mcp
    check(f"{nome}: MCP aceita os mesmos campos", not faltando, str(sorted(faltando)))

print("3) as duas descricoes citam a mesma regra de ordem")
reg = pc_tools.TOOLS["send_message"].descricao.lower()
mcp = mcp_server.TOOLS["send_message"]["description"].lower()
check("registro exige open_chat antes", "open_chat" in reg)
check("MCP exige open_chat antes", "open_chat" in mcp or "aberta" in mcp)

print("4) o laco nao expoe nada perigoso sem marcar risco")
for nome, t in pc_tools.TOOLS.items():
    if t.observa:
        check(f"{nome} so observa e nao tem risco", not t.risco({}))

print("5) schemas do Ollama sao validos")
for s in pc_tools.schemas_ollama():
    f = s["function"]
    ok = (isinstance(f.get("name"), str) and f.get("description")
          and f["parameters"].get("type") == "object"
          and isinstance(f["parameters"].get("properties"), dict))
    check(f"schema {f.get('name')}", bool(ok))
    # _req nao pode vazar para o schema publicado
    for p, d in f["parameters"]["properties"].items():
        check(f"{f['name']}.{p} sem _req", "_req" not in d)

print()
print("FALHAS:" if falhas else "TUDO OK")
for f in falhas:
    print(" -", f)
sys.exit(1 if falhas else 0)
