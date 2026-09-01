"""Bateria do roteador deterministico: casos esperados vs obtidos."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pc_intent as I

# (frase, action esperada, q esperada)  q=None -> nao checa
CASES = [
    # abrir programas
    ("abre o teams",                    "app", "teams"),
    ("abra o teams",                    "app", "teams"),
    ("abrir teams",                     "app", "teams"),
    ("inicia o excel",                  "app", "excel"),
    ("abre o word",                     "app", "word"),
    ("abre o cursor",                   "app", "cursor"),
    ("abre o whatsapp",                 "app", "whatsapp"),
    ("abre a calculadora",              "app", "calculadora"),
    ("abre o bloco de notas",           "app", "bloco de notas"),
    ("abre o outlook",                  "app", "outlook"),
    ("abre o sql server management studio", "app", None),
    # ler
    ("abre o teams e le as mensagens",  "read", "teams"),
    ("le as mensagens do teams",        "read", "teams"),
    ("leia as mensagens do teams",      "read", "teams"),
    ("me fala as mensagens do whatsapp","read", "whatsapp"),
    ("tem email novo",                  "read", "outlook"),
    ("tem mensagem nova no teams",      "read", "teams"),
    ("chegou mensagem no teams",        "read", "teams"),
    ("resume a caixa de entrada",       "read", None),
    # musica / video
    ("toca metallica",                  "youtube", "metallica"),
    ("toca uma musica do pink floyd",   "youtube", "pink floyd"),
    ("reproduz bohemian rhapsody",      "youtube", "bohemian rhapsody"),
    ("poe pra tocar caetano veloso",    "youtube", "caetano veloso"),
    ("toca chico buarque no youtube",   "youtube", "chico buarque"),
    ("toca",                            "media", ""),
    ("play",                            "media", ""),
    ("toca de novo",                    "media", ""),
    ("toca a musica",                   "media", ""),
    ("pausa a musica",                  "media", ""),
    ("proxima musica",                  "media_next", ""),
    ("musica anterior",                 "media_prev", ""),
    # navegador
    ("abre o youtube",                  "youtube", "__home__"),
    ("abre o navegador",                "browser", ""),
    ("abre o chrome",                   "browser", ""),
    ("abre o globo.com",                "browser_go", "globo.com"),
    ("fecha a aba",                     "browser_tab", "fecha"),
    ("nova aba",                        "browser_tab", "nova"),
    ("volta a pagina",                  "browser_back", ""),
    ("desce a pagina",                  "browser_scroll", "down"),
    ("clica em entrar",                 "browser_click", "entrar"),
    ("digita bom dia",                  "browser_type", "bom dia"),
    # sistema
    ("sobe o volume",                   "volume_up", ""),
    ("aumenta o som",                   "volume_up", ""),
    ("abaixa o volume",                 "volume_down", ""),
    ("muda pra mudo",                   "mute", ""),
    ("trava o pc",                      "lock", ""),
    ("tira um print",                   "screenshot", ""),
    ("gerenciador de tarefas",          "taskmgr", ""),
    ("area de trabalho",                "desktop", ""),
    ("alt tab",                         "switch_win", ""),
    # busca
    ("pesquisa receita de bolo",        "search", "receita de bolo"),
    ("procura por cotacao do dolar",    "search", "cotacao do dolar"),
    ("pesquisa no youtube tropicalia",  "youtube", "tropicalia"),
    # conversas: escolher a pessoa
    ("selecione o natan no whatsapp",    "chat", "whatsapp|natan"),
    ("pesquise por natan no whats",      "chat", "whatsapp|natan"),
    ("pesquise no whatsapp por natan",   "chat", "whatsapp|natan"),
    ("abre a conversa do natan no whatsapp", "chat", "whatsapp|natan"),
    ("chama a maria no teams",           "chat", "teams|maria"),
    ("fala com o pedro no whatsapp",     "chat", "whatsapp|pedro"),
    # conversas: mandar mensagem
    ("manda mensagem pro natan no whatsapp dizendo bom dia",
     "msg", "whatsapp|natan|bom dia"),
    ("manda no whatsapp pro natan: reuniao as 14h",
     "msg", "whatsapp|natan|reuniao as 14h"),
    ("fala pro joao no teams que eu vou atrasar",
     "msg", "teams|joao|eu vou atrasar"),
    ("envia pra ana no whatsapp: cheguei", "msg", "whatsapp|ana|cheguei"),
    # forma curta sem verbo, como se digita no teclado do Cardputer
    ("natan teams",                      "chat", "teams|natan"),
    ("mike teams",                       "chat", "teams|mike"),
    ("teams mike",                       "chat", "teams|mike"),
    ("teams, foco mike",                 "chat", "teams|mike"),
    ("natan whatsapp",                   "chat", "whatsapp|natan"),
    # e o que NAO pode virar conversa
    ("abre o teams",                     "app", "teams"),
    ("abre o whatsapp",                  "app", "whatsapp"),
    ("le as mensagens do teams",         "read", "teams"),

    # nao pode virar conversa nem busca no Google
    ("manda o volume pra cima",          "volume_up", ""),
    ("pesquise por cotacao do dolar",    "search", "cotacao do dolar"),

    # devem cair pro modelo (nao ha regra segura)
    ("abre o spotify",                  None, None),
    ("qual a capital da franca",        None, None),
    ("oi",                              None, None),
    ("me ajuda com uma coisa",          None, None),
]

ok = bad = 0
fails = []
for frase, exp_act, exp_q in CASES:
    got = I.route(frase)
    act, q = got if got else (None, None)
    good = (act == exp_act) and (exp_q is None or q == exp_q)
    if good:
        ok += 1
    else:
        bad += 1
        fails.append((frase, exp_act, exp_q, act, q))

print(f"roteador: {ok}/{len(CASES)} ok, {bad} falhas")
for frase, ea, eq, ga, gq in fails:
    print(f"  FALHA  {frase!r}")
    print(f"         esperado {ea!r} q={eq!r}")
    print(f"         obtido   {ga!r} q={gq!r}")
sys.exit(1 if bad else 0)
