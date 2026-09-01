# Agente Windows (Pocket Deck)

Dois clientes usam o mesmo motor:

- **Cardputer ADV** pela Wi-Fi 2.4 GHz -> `agent.py` (HTTP na porta 8765)
- **Cursor / Claude Code** -> `mcp_server.py` (MCP stdio)

## Como subir

```
iniciar-tudo.bat
```

Anote o **PIN** e o **IP**. Libere o Python no firewall em **rede privada**.

No ADV: menu **PC IA** -> rede 2.4 GHz (nao a `_5G`) -> senha -> achar o PC
(ou digitar o IP) -> PIN -> comando. O ADV mostra o que vai fazer; **Enter**
confirma.

Para as acoes de navegador, rode tambem `iniciar-chrome-debug.bat`
(abre Chrome ou Edge com a porta de debug 9222).

## O que da pra pedir

| Pedido | Acao |
| --- | --- |
| abre o teams / excel / whatsapp / qualquer app | `app` |
| abre o teams e le as mensagens | `read` |
| selecione o natan no whatsapp | `chat` |
| natan teams / teams mike (forma curta) | `chat` |
| manda pro natan no whatsapp: cheguei | `msg` |
| tem email novo | `read` no Outlook |
| toca metallica | `youtube` |
| pesquisa receita de bolo | `search` |
| sobe o volume, trava o pc, tira um print | atalhos de sistema |
| clica em X, digita Y, fecha a aba, desce a pagina | navegador via CDP |
| falhas / resumo / perfis | `diag` |
| esquece isso / esquece tudo | `forget` |

## O que o aparelho mostra enquanto trabalha

O `/intent` nao bloqueia mais. Ele responde na hora com um id de trabalho e o
ADV pergunta o andamento a cada 0,4s, mostrando o que o PC esta fazendo:

```
enviando...  ->  pensando...  ->  abrindo whatsapp
             ->  abrindo conversa com Natan  ->  escrevendo
```

ESC no meio cancela (`/cancel`), e o laco para entre um passo e outro.

**Confirmacao.** So o que e dificil de desfazer para e espera o Enter: enviar
mensagem, travar a tela, fechar janela. Volume, abrir app e ler tela executam
direto. Quem decide e o servidor (campo `confirm` na resposta), porque e ele
que sabe o que e irreversivel.

Ate aqui isso nunca funcionou: `mode_ = Mode::Confirm` nao existia no firmware
e o `sendIntent()` chamava `sendDo()` direto — a tela de confirmacao estava
escrita mas era inalcancavel, e tudo executava sozinho.

Compatibilidade: `/intent` com `{"sync":true}` responde do jeito antigo, so no
fim. Serve para firmware nao atualizado.

## Como o pedido vira acao: 4 camadas

Da mais rapida para a mais esperta. A camada seguinte so entra se a anterior
nao resolveu, entao o que ja funciona continua instantaneo.

| # | Camada | Custo | Cobre |
| --- | --- | --- | --- |
| 0 | receita aprendida (`pc_recipes.py`) | ~0s | pedidos que ja deram certo antes |
| 1 | regras deterministicas (`pc_intent.route`) | ~0s | os 69 casos dos testes |
| 2 | modelo escolhendo UMA acao (`pc_intent.ask_model`) | ~3s | variacoes do que ja e mapeado |
| 3 | laco de ferramentas (`pc_agentloop.py`) | 10-40s | o que nao esta mapeado |

### Camada 3: o laco (`pc_agentloop.py` + `pc_tools.py`)

O modelo recebe as ferramentas do PC e as combina sozinho, um passo por vez,
vendo o resultado real de cada um. E o que permite tarefas novas sem mexer no
codigo.

`planejar()` roda so o que e **reversivel** — abre app, procura contato, le
tela. Ao topar numa acao irreversivel (enviar, travar, fechar), guarda e para.
O Cardputer mostra um rotulo tipo `Enviar p/ natan` e um Enter libera:
`executar_pendentes()` roda so essa parte. Por isso o `/do` continua rapido
(medido: 2,1s num envio) e nao precisou mexer no timeout do firmware.

**A auto-validacao esta no codigo, nao no modelo.** Medido com qwen2.5:3b:

- sozinho ele pula o `open_chat` e escreve na conversa que estiver aberta;
- ao receber um erro seco, desiste;
- com a regra de ordem na descricao da ferramenta e uma **dica** anexada ao
  erro, ele investiga com `ui_list` e acerta na segunda.

Dai os guardrails, todos em `pc_agentloop`:

- mapa `DICAS`: erro observado -> o que tentar em seguida;
- pre-condicao no executor: `send_message` so roda depois de um `open_chat`
  bem-sucedido no mesmo plano;
- chamada identica repetida e interrompida;
- tres "empurroes" para quando ele responde sem chamar ferramenta, desiste
  depois de um erro, ou pergunta em vez de agir;
- `_limpar_final` impede que a dica interna vire resposta no visor;
- teto de 8 passos e 45s;
- o laco so enxerga 10 das 12 ferramentas (`no_laco=False` em `ui_click` e
  `ui_type`): com as 12 o 3b escolhia `ui_click "Enviar mensagem"` e se perdia.
  O MCP continua expondo todas, porque la o cliente e um modelo grande.

O modelo e aquecido na largada (`aquecer()`): a primeira chamada custa ~30s so
para subir os pesos e o template de tool calling, e isso estourava o teto de
tempo no meio do primeiro pedido.

### Camada 0: receitas (`pc_recipes.py`)

Depois de um plano dar certo, a sequencia de ferramentas e guardada em
`%LOCALAPPDATA%\PocketDeck\recipes.json`. Na proxima vez o mesmo pedido roda
sem chamar o modelo.

A generalizacao e **deterministica**, nao vem do modelo: os valores usados nas
ferramentas sao procurados dentro da frase, e onde batem viram grupo de
captura.

```
frase : "manda bom dia pro natan no whatsapp"
vira  : manda (?P<c1>.+?) pro (?P<c2>.+?) no (?P<c3>.+?)
depois: "manda boa tarde pro pedro no whatsapp"  ->  reaproveita, ~0s
```

Antes de gravar, o padrao tem de reproduzir exatamente os passos originais;
senao vira correspondencia por frase exata. Pelo Cardputer: `esquece isso`
apaga a ultima, `esquece tudo` limpa, `o que voce aprendeu` lista.

## Detalhes das regras (`pc_intent.py`)

1. **Regras deterministicas** (`route`) resolvem a maioria dos comandos, com
   limite de palavra em vez de "esta contido em". `abre o <X>` so vira `app`
   se `<X>` existir mesmo no indice de apps instalados.
2. **Modelo local** (Ollama) so entra no que a regra nao resolveu, com prompt
   curto e exemplos. A saida passa por `repair()`, que conserta os erros
   tipicos de modelo pequeno.
3. **Fallback**: saudacao vira resposta, o resto vira busca no Google.

O resultado do modelo **nao** e mais sobrescrito por heuristica depois —
era isso que fazia "abre o teams" virar busca no YouTube.

## Abrir programas (`pc_apps.py`)

O indice vem de `shell:AppsFolder`, a mesma lista do menu Iniciar
"Todos os apps" — cobre Win32 e UWP/MSIX (Teams, WhatsApp, Calculadora).
Qualquer item abre com `explorer.exe "shell:AppsFolder\<AUMID>"`.

Cache em `%LOCALAPPDATA%\PocketDeck\apps.json`, revalidado a cada 6 h e
reindexado na hora quando um nome nao bate.

`focus_or_launch` traz a janela para frente se o app ja estiver aberto, em
vez de abrir outra instancia.

## Ler e agir dentro de uma janela (`pc_read.py`)

UI Automation numa thread COM propria. Funciona em Outlook classico, Bloco de
notas, Explorer, **e tambem em Teams e WhatsApp**.

O Teams e WebView2 (`TeamsWebView` + `Chrome_WidgetWin_0`) e o Chromium so
monta a arvore de acessibilidade sob demanda: com a janela nunca ativada o UIA
volta vazio. Por isso `read_text` chama `focus_or_launch` antes de desistir.
Se ainda assim vier vazio, cai para a versao web no navegador do CDP
(`teams.microsoft.com`), que precisa de um login uma vez no perfil
`%LOCALAPPDATA%\PocketDeck\chrome-cdp`.

Para **agir** dentro do app existe a trinca `ui_list` / `ui_click` / `ui_type`.
Clicar por pixel nao funciona em Teams e WhatsApp: eles desenham tudo numa
superficie unica, entao a foto da tela nao diz onde estao os controles. A
arvore de acessibilidade diz.

Mandar mensagem, por exemplo:

```
launch_app  name=whatsapp
ui_list     app=WhatsApp kind=click     -> nomes das conversas
ui_click    app=WhatsApp text=<contato>
ui_list     app=WhatsApp kind=edit      -> "Digite uma mensagem para ..."
ui_type     app=WhatsApp field="Digite uma mensagem" text="..." send=false
```

`send=false` deixa escrito sem enviar. So passe `send=true` depois que a
pessoa confirmar o texto.

### Trocar de conversa e nao errar o destinatario

`open_chat` (MCP) e a acao `chat` (Cardputer) fazem, nesta ordem:

1. **limpam o filtro de busca** — um filtro deixado para tras esconde o resto
   da lista e, no WhatsApp, some ate com o proprio campo de busca da arvore de
   acessibilidade; sem isso a segunda troca de conversa nunca acha ninguem;
2. procuram a pessoa na lista, ou digitam o nome na busca do app;
3. acionam o item;
4. **confirmam que a conversa trocou** antes de dizer que deu certo.

O passo 4 nao e enfeite. A caixa de escrever demora a acompanhar o clique;
sem esperar, o texto seguinte vai para a conversa ANTERIOR. `send_message`
aceita `person=` e **recusa escrever** se a conversa aberta nao for a dela.

Cada app expoe a lista de um jeito: **DataItem** no WhatsApp, **TreeItem** no
Teams. Isso agora e dado, nao codigo: fica em `pc_profiles.py`, e app
desconhecido passa por uma sondagem que monta o histograma de tipos de
controle e escolhe o que parece linha de conversa (muitos irmaos, nomes
compridos). O que der certo e gravado em `profiles.json` — na segunda vez ja
funciona sem editar nada.

Confirmar a troca tambem muda por app. No WhatsApp a caixa vira "Digite uma
mensagem para <pessoa>". No Teams nao da: a caixa e sempre "Digite uma
mensagem" e o titulo da janela **nao acompanha a aba** (fica em "Calendar |
..." mesmo com o Chat aberto). O sinal que vale la e o
`SelectionItemPattern.IsSelected` do item clicado.

Itens da lista do WhatsApp nao tem `InvokePattern` e `Select()` marca sem
navegar: o que troca a conversa e um clique de mouse de verdade nas
coordenadas do elemento. Por isso `move_mouse` usa a area de TODOS os
monitores (`SM_XVIRTUALSCREEN`): limitado ao monitor principal, o clique nunca
chegava numa janela em x negativo.

## MCP (Cursor, Claude Code)

`.cursor/mcp.json` ja aponta para `mcp_server.py`. 27 ferramentas.

O transporte stdio do MCP e **JSON por linha**. A versao anterior usava o
framing `Content-Length` do LSP, e por isso nenhum cliente conseguia falar com
o servidor — ele lia a linha do JSON como se fosse cabecalho e travava. Agora
os dois framings sao aceitos e o `protocolVersion` do cliente e devolvido.

Ferramentas que valem citar:

- `launch_app` / `find_app` — abre ou procura qualquer app instalado
- `read_window` / `window_titles` — le texto de janela (melhor que screenshot)
- `browser_*` — Chrome/Edge via CDP 9222
- `desktop_snapshot` + `click` — ultimo recurso, clique por pixel

## Ollama

Container Docker em `localhost:11434`, modelo padrao `qwen2.5:3b`
(`OLLAMA_MODEL` muda). Sem Ollama o agente continua funcionando: so as
regras deterministicas respondem, e o `read` devolve texto truncado em vez
de resumido.

## Testes

```
py -3 pc-agent\tests\test_router.py        # 57 frases -> acao, sem modelo
py -3 pc-agent\tests\test_model_fake.py    # Ollama falso: saidas ruins viram acao valida
py -3 pc-agent\tests\test_model_real.py    # qwen2.5:3b de verdade (precisa do Ollama no ar)
py -3 pc-agent\tests\test_desktop_e2e.py   # abre app fechado, escreve, le de volta, fecha
```

`test_desktop_e2e.py` mexe na tela de verdade (abre e fecha o Bloco de notas).

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `agent.py` | HTTP para o ADV, voz, Ollama, resumo curto para o visor |
| `pc_intent.py` | pedido -> acao (regras + modelo + reparo) |
| `pc_tools.py` | registro unico de ferramentas (laco + MCP) |
| `pc_agentloop.py` | laco de ferramentas com os guardrails |
| `pc_recipes.py` | memoria do que ja deu certo |
| `pc_jobs.py` | trabalhos em andamento, progresso e cancelamento |
| `pc_profiles.py` | como cada app expoe a lista de conversas |
| `pc_log.py` | registro de pedidos e passos, para diagnostico |
| `pc_apps.py` | indice e abertura de apps instalados |
| `pc_read.py` | leitura de janelas via UI Automation |
| `pc_control.py` | allowlist de acoes |
| `pc_desktop.py` | mouse, teclado, janelas, screenshot |
| `pc_browser.py` | Chrome/Edge via CDP + Playwright |
| `mcp_server.py` | servidor MCP stdio |
