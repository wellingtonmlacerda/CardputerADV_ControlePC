#!/usr/bin/env python3
"""Agente local Pocket Deck: o Cardputer ADV manda comandos na rede 2.4 GHz.

Uso:
  python agent.py

O PIN aparece aqui. Digite o mesmo PIN no ADV.
Firewall do Windows: permitir Python em rede privada.
"""

from __future__ import annotations

import io
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pc_control as pc
import pc_intent
import pc_jobs
import pc_log
from pc_control import ACTIONS, _norm, run_action

PORT = 8765
UDP_PORT = 18765
APPDIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "PocketDeck"
PIN_FILE = APPDIR / "pin.txt"


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def load_pin() -> str:
    APPDIR.mkdir(parents=True, exist_ok=True)
    if PIN_FILE.exists():
        return PIN_FILE.read_text(encoding="utf-8").strip()
    pin = f"{random.randint(0, 999999):06d}"
    PIN_FILE.write_text(pin, encoding="utf-8")
    return pin


PIN = ""
IP = ""
LAST_Q = ""
HISTORY: list[tuple[str, str, str]] = []
AI_ON = False
AI_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


def remember(user: str, act: str, q: str) -> None:
    global LAST_Q, HISTORY
    LAST_Q = q or user
    HISTORY.append((user, act, q))
    if len(HISTORY) > 12:
        del HISTORY[0]
    if act == "youtube" and q:
        pc.LAST_YT = q
        pc.YT_OPEN = True
    if act == "close":
        nq = _norm(q)
        if any(k in nq for k in ("youtube", "aba", "navegador", "chrome", "janela")):
            pc.YT_OPEN = False


def _clean(s: str) -> str:
    return "".join(" " if c in '"\\' else c for c in s).strip()[:120]


def ollama_up() -> bool:
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _compose_file() -> Path:
    return Path(__file__).resolve().parent / "docker-compose.yml"


def docker_up_ai() -> bool:
    compose = _compose_file()
    if not compose.exists():
        print("IA: falta", compose, flush=True)
        return False
    try:
        subprocess.check_call(
            ["docker", "compose", "-f", str(compose), "up", "-d"],
            timeout=180,
        )
        return True
    except Exception as exc:
        print("IA: docker compose falhou:", exc, flush=True)
        return False


def list_models() -> list[str]:
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode())
        return [str(m.get("name", "")) for m in data.get("models", [])]
    except Exception:
        return []


def pull_model(name: str) -> bool:
    print("IA: baixando modelo", name, "no container (pode demorar)...", flush=True)
    body = json.dumps({"name": name, "stream": False}).encode()
    try:
        req = Request(
            "http://127.0.0.1:11434/api/pull",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=600) as r:
            r.read()
        return True
    except Exception:
        pass
    try:
        subprocess.check_call(
            ["docker", "exec", "pocketdeck-ollama", "ollama", "pull", name],
            timeout=600,
        )
        return True
    except Exception as exc:
        print("IA: pull falhou:", exc, flush=True)
        return False


def ensure_ollama() -> str:
    global AI_ON, AI_MODEL
    if not ollama_up():
        print("IA: subindo container Docker...", flush=True)
        if not docker_up_ai():
            AI_ON = False
            return "off"
        for _ in range(60):
            time.sleep(1)
            if ollama_up():
                break
        else:
            print("IA: container nao respondeu em :11434", flush=True)
            AI_ON = False
            return "off"

    models = list_models()
    want = AI_MODEL
    has = any(want in m or m.startswith(want.split(":")[0]) for m in models)
    if not has:
        if not pull_model(want):
            if models:
                AI_MODEL = models[0]
                print("IA: usando modelo ja baixado:", AI_MODEL, flush=True)
            else:
                AI_ON = False
                return "off"
        models = list_models()
    for m in models:
        if want in m or m.startswith(want.split(":")[0]):
            AI_MODEL = m
            break

    AI_ON = True
    print("IA ligada (Docker). Modelo:", AI_MODEL, flush=True)
    # sobe os pesos e o template de tool calling agora: se isso acontecesse no
    # meio de um pedido, os ~30s de carga estourariam o teto do laco
    import pc_agentloop

    print("IA: aquecendo...", "ok" if pc_agentloop.aquecer(AI_MODEL) else "falhou",
          flush=True)
    return AI_MODEL


def _context() -> str:
    """Contexto curto para o modelo nao repetir o que ja foi feito."""
    if not HISTORY:
        return ""
    parts = [f"{u} -> {a} {q}".strip() for u, a, q in HISTORY[-3:]]
    ctx = "Ja feito: " + " | ".join(parts)
    if pc.YT_OPEN and pc.LAST_YT:
        ctx += f" | youtube tocando {pc.LAST_YT}"
    return ctx + "\nAgora: "


_QUESTION = ("que ", "qual", "quem", "quando", "como", "onde", "porque",
             "por que", "quanto", "quais")
_GREET = ("oi", "ola", "eai", "e ai", "opa", "hello", "hi", "bom dia",
          "boa tarde", "boa noite")


def _last_resort(text: str) -> tuple[str, str]:
    t = _norm(text)
    if t in _GREET or any(t.startswith(g + " ") for g in _GREET):
        return "reply", "Oi! Manda o comando."
    if "?" in text or any(t.startswith(q) for q in _QUESTION):
        return ("search", text.strip()) if not AI_ON else (
            "reply", "Nao consegui responder. Tenta de novo.")
    if len(t) >= 3:
        return "search", text.strip()
    return "reply", "Nao entendi."


# Qual camada resolveu o ultimo pedido, para o registro de falhas.
ULTIMA_CAMADA = ["?"]

# Planos aguardando o Enter do aparelho. id -> Plano.
PLANOS: dict[str, object] = {}
_PLANO_SEQ = [0]

# frases que cheiram a ordem: se o modelo devolveu conversa fiada para uma
# delas, vale gastar o laco de ferramentas em vez de responder qualquer coisa
_ORDEM = (
    "abre", "abra", "abrir", "manda", "mande", "envia", "envie", "escreve",
    "escreva", "fala", "responde", "procura", "procure", "pesquisa", "pesquise",
    "seleciona", "selecione", "le ", "leia", "toca", "clica", "clique", "fecha",
    "coloca", "poe", "chama", "mostra", "copia", "salva", "baixa", "anexa",
)


def _guardar_plano(plano) -> str:
    _PLANO_SEQ[0] += 1
    pid = "p%d" % _PLANO_SEQ[0]
    PLANOS.clear()          # um plano por vez; o aparelho confirma na hora
    PLANOS[pid] = plano
    return pid


def _parece_ordem(t: str) -> bool:
    n = _norm(t)
    return any(n.startswith(v) or (" " + v) in n for v in _ORDEM)


def _viavel(act: str, q: str) -> bool:
    """A acao escolhida tem chance de dar certo?

    Checagem barata e sem efeito colateral, feita ANTES de executar. Sem ela o
    agente devolvia "janela nao encontrada" repetidas vezes e nunca tentava
    outro caminho: o laco so entrava quando o pedido nao era mapeado, nunca
    quando a acao mapeada estava fadada a falhar.
    """
    import pc_apps
    import pc_desktop

    alvo = (q or "").strip()
    if act == "focus":
        if not alvo:
            return False
        n = pc_apps.norm(alvo)
        return any(n in pc_apps.norm(str(w["title"]))
                   for w in pc_desktop.list_windows(40))
    if act == "app":
        return bool(pc_apps.resolve(alvo))
    if act in ("chat", "msg"):
        app = alvo.split("|")[0] if "|" in alvo else ""
        return bool(pc_apps.resolve(app)) if app else True
    return True


def _do_plano(raw: str, plano, src: str) -> tuple[str, str, str]:
    """Transforma um Plano no que o aparelho entende."""
    if plano.erro and not plano.passos:
        print(f"  [{src}] falhou: {plano.erro}", flush=True)
        return "reply", ACTIONS["reply"], plano.erro[:95]
    if plano.precisa_confirmar:
        pid = _guardar_plano(plano)
        print(f"  [{src}] plano {pid}: {len(plano.passos)} passos feitos, "
              f"{len(plano.pendentes)} aguardando Enter ({plano.segundos:.0f}s)",
              flush=True)
        return "plan", plano.rotulo(), pid
    # nada irreversivel: ja esta tudo feito, so relatar
    aprender(raw, plano)
    print(f"  [{src}] concluido em {plano.segundos:.0f}s: {plano.resumo()}", flush=True)
    return "reply", ACTIONS["reply"], plano.resumo()


def aprender(raw: str, plano) -> None:
    """Guarda a receita do que deu certo, para a proxima vez ser instantanea."""
    import pc_agentloop
    import pc_recipes

    if plano.erro:
        return
    trilha = pc_agentloop.trilha(plano)
    if not trilha:
        return
    try:
        print("  aprendi:", pc_recipes.salvar(raw, trilha), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("  nao consegui aprender:", str(exc)[:60], flush=True)


def interpret(text: str) -> tuple[str | None, str, str]:
    raw = (text or "").strip()
    if not raw:
        return None, "", ""

    import pc_agentloop
    import pc_recipes

    # camada 0: ja fizemos isso antes
    try:
        passos = pc_recipes.procurar(raw)
    except Exception:  # noqa: BLE001
        passos = None
    if passos:
        ULTIMA_CAMADA[0] = "receita"
        pc_jobs.progresso("receita conhecida")
        plano = pc_agentloop.executar_passos(raw, passos)
        remember(raw, "plan", raw)
        return _do_plano(raw, plano, "receita")

    # camada 1: regras deterministicas
    hit = pc_intent.route(raw)
    src = "regra"
    ULTIMA_CAMADA[0] = "regra"

    # camada 2: modelo escolhendo uma acao
    if hit is None and AI_ON:
        pc_jobs.progresso("pensando...")
        hit = pc_intent.ask_model(raw, AI_MODEL, _context())
        src = "IA"
        ULTIMA_CAMADA[0] = "modelo"

    # camada 3: laco de ferramentas. Entra em tres casos: nada mapeado,
    # conversa fiada no lugar de uma ordem, ou acao mapeada que vai falhar.
    conversa_fiada = hit is not None and hit[0] == "reply" and _parece_ordem(raw)
    fadada = hit is not None and not _viavel(hit[0], hit[1])
    if fadada:
        print(f"  [{src}] {hit[0]} {hit[1]} nao tem alvo valido, escalando",
              flush=True)
    if AI_ON and (hit is None or conversa_fiada or fadada):
        print("  [laco] montando plano...", flush=True)
        pc_jobs.progresso("montando plano...")
        ULTIMA_CAMADA[0] = "laco"
        plano = pc_agentloop.planejar(raw, AI_MODEL)
        if plano.passos or plano.pendentes:
            remember(raw, "plan", raw)
            return _do_plano(raw, plano, "laco")
        if hit is None:
            hit = ("reply", plano.erro or "Nao consegui fazer isso.")
            src = "laco"

    if hit is None:
        hit = _last_resort(raw)
        src = "fallback"

    act, q = hit
    print(f"  [{src}] {act} {q}".rstrip(), flush=True)
    remember(raw, act, q)
    return act, ACTIONS.get(act, act), q


def _precisa_confirmar(act: str, q: str) -> bool:
    """So o que e dificil de desfazer para e espera o Enter no aparelho.

    Volume, abrir app e ler tela executam direto. Enviar mensagem, travar a
    tela e fechar janela passam pela tela de confirmacao.
    """
    import pc_tools

    if act == "plan":
        plano = PLANOS.get((q or "").strip())
        return bool(plano is not None and getattr(plano, "pendentes", None))
    if act == "msg":
        return True
    if act == "close":
        return True
    return pc_tools.irreversivel("pc_do", {"action": act})


def resolver(q: str) -> dict[str, object]:
    """Interpreta um pedido e monta a resposta que o aparelho entende."""
    t0 = time.time()
    try:
        act, label, extra = interpret(q)
    except Exception as exc:  # noqa: BLE001
        pc_log.pedido(q, "erro", "", "", False, int((time.time() - t0) * 1000),
                      str(exc)[:200])
        print("  -> erro:", str(exc)[:120], flush=True)
        return {"ok": False, "error": ("falhou: " + str(exc))[:90]}
    ms = int((time.time() - t0) * 1000)
    if not act:
        print("  -> nao entendi", flush=True)
        pc_log.pedido(q, "?", "", "", False, ms, "nao entendi")
        return {"ok": False, "error": "nao entendi"}
    alvo = extra or q
    confirma = _precisa_confirmar(act, alvo)
    print("  ->", act, alvo, "(confirma)" if confirma else "", flush=True)
    pc_log.pedido(q, ULTIMA_CAMADA[0], act, alvo, True, ms, label)
    return {"ok": True, "action": act, "label": label, "q": alvo,
            "confirm": confirma}


def _trabalhar(jid: str, q: str) -> None:
    """Roda o pedido numa thread, publicando o andamento para o aparelho."""
    pc_jobs.assumir(jid)
    try:
        resultado = resolver(q)
    except Exception as exc:  # noqa: BLE001
        resultado = {"ok": False, "error": ("falhou: " + str(exc))[:90]}
    finally:
        if pc_jobs.cancelado(jid):
            resultado = {"ok": False, "error": "cancelado"}
        pc_jobs.concluir(jid, resultado)
        pc_jobs.largar()


def run_plan(pid: str) -> str:
    """Executa a parte irreversivel de um plano ja confirmado no aparelho."""
    import pc_agentloop

    plano = PLANOS.pop((pid or "").strip(), None)
    if plano is None:
        return "esse plano expirou, peca de novo"
    try:
        saida = pc_agentloop.executar_pendentes(plano)
    except Exception as exc:  # noqa: BLE001
        return ("falhou: " + str(exc))[:95]
    aprender(plano.pedido, plano)
    return saida[:95]


def shorten(text: str, limit: int = 88) -> str:
    """Resume um texto longo para caber no visor do Cardputer."""
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    if AI_ON:
        body = json.dumps({
            "model": AI_MODEL,
            "stream": False,
            "keep_alive": "30m",
            "options": {"num_predict": 60, "temperature": 0.1},
            "messages": [
                {"role": "system", "content":
                    "Resuma em portugues em ate 80 caracteres, numa frase so, "
                    "sem aspas. Diga quem mandou e o assunto."},
                {"role": "user", "content": clean[:2500]},
            ],
        }).encode()
        try:
            req = Request("http://127.0.0.1:11434/api/chat", data=body,
                          headers={"Content-Type": "application/json"},
                          method="POST")
            with urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode())
            out = " ".join(str(data.get("message", {}).get("content", "")).split())
            if out:
                return out[:limit]
        except Exception as exc:  # noqa: BLE001
            print("resumo falhou:", exc, flush=True)
    return clean[:limit]


def pcm16_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe(pcm: bytes, rate: int) -> str:
    wav = pcm16_to_wav(pcm, rate)
    path = ""
    try:
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        Path(path).write_bytes(wav)
        try:
            import speech_recognition as sr

            rec = sr.Recognizer()
            with sr.AudioFile(path) as source:
                audio = rec.record(source)
                text = rec.recognize_google(audio, language="pt-BR")
            if text:
                return str(text)[:120]
        except ImportError:
            print("instale: pip install SpeechRecognition", flush=True)
        except Exception as exc:
            print("stt google:", exc, flush=True)
        try:
            import whisper

            model = whisper.load_model("tiny")
            out = model.transcribe(path, language="pt")
            return str(out.get("text", "")).strip()
        except ImportError:
            pass
        except Exception as exc:
            print("stt whisper:", exc, flush=True)
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _auth(self) -> bool:
        return self.headers.get("X-Token", "") == PIN

    def _json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/ping"):
            self._json(200, {"ok": True, "ip": IP})
            return
        self._json(404, {"ok": False})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth():
            self._json(401, {"ok": False, "error": "PIN errado"})
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n)
        if self.path.startswith("/voice"):
            rate = int(self.headers.get("X-Rate", "16000") or 16000)
            print("voz: %d bytes @ %d Hz" % (len(raw), rate), flush=True)
            try:
                text = transcribe(raw, rate)[:120]
            except Exception as exc:
                print("voz erro:", exc, flush=True)
                self._json(200, {"ok": False, "error": "voz falhou no PC"})
                return
            print("  ouviu:", text or "(vazio)", flush=True)
            if not text:
                self._json(200, {"ok": False, "error": "nao ouvi, fale de novo"})
                return
            self._json(200, {"ok": True, "q": text})
            return
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "json"})
            return
        if self.path.startswith("/intent"):
            q = str(payload.get("q", "")).strip()[:180]
            print("pedido:", q, flush=True)
            # sync=true mantem o comportamento antigo, para firmware nao
            # atualizado continuar funcionando enquanto o novo nao e gravado
            if payload.get("sync"):
                self._json(200, resolver(q))
                return
            jid = pc_jobs.criar(q)
            threading.Thread(target=_trabalhar, args=(jid, q), daemon=True).start()
            self._json(200, {"ok": True, "job": jid})
            return
        if self.path.startswith("/job"):
            self._json(200, pc_jobs.ler(str(payload.get("id", ""))))
            return
        if self.path.startswith("/cancel"):
            jid = str(payload.get("id", ""))
            ok = pc_jobs.cancelar(jid)
            print("cancelado:", jid if ok else "(nada a cancelar)", flush=True)
            self._json(200, {"ok": ok})
            return
        if self.path.startswith("/do"):
            act = str(payload.get("action", ""))
            q = str(payload.get("q", "")).strip()[:180] or LAST_Q
            if act not in ACTIONS:
                self._json(400, {"ok": False, "error": "acao bloqueada"})
                return
            if act == "plan":
                msg = run_plan(q)
            else:
                msg = run_action(act, q)
            print("executou:", act, "->", msg[:160].replace("\n", " / "), flush=True)
            if act == "read":
                msg = shorten(msg)
            self._json(200, {"ok": True, "msg": msg[:400]})
            return
        self._json(404, {"ok": False})


def beacon() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = f"PKDK|{IP}|{PORT}".encode()
    while True:
        try:
            sock.sendto(msg, ("255.255.255.255", UDP_PORT))
        except OSError:
            pass
        time.sleep(2)


def main() -> None:
    global PIN, IP
    PIN = load_pin()
    IP = local_ip()
    print("=== Pocket Deck agente ===")
    print(f"IP deste PC : {IP}")
    print(f"Porta       : {PORT}")
    print(f"PIN (ADV)   : {PIN}")
    print("Deixe esta janela aberta. ADV na WiFi 2.4 GHz da mesma casa.")
    print("Firewall: permita Python em rede privada.")
    print("IA: Ollama em container Docker (porta 11434).")
    ensure_ollama()
    print("Voz no ADV: pip install SpeechRecognition (PC precisa de internet).")
    threading.Thread(target=beacon, daemon=True).start()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")


if __name__ == "__main__":
    main()
