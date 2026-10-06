# 🦌 DeerFlow - 2.0

[English](./README.md) | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md) | Português

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> Em 28 de fevereiro de 2026, o DeerFlow chegou ao 🏆 1º lugar do GitHub Trending logo após o lançamento da versão 2. Muito obrigado à nossa comunidade, foram vocês que fizeram isso acontecer! 💪🔥

O DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) é um **super agent harness** de código aberto que orquestra **sub-agents**, **memória** e **sandboxes** para fazer quase qualquer coisa, com base em **skills extensíveis**.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **O DeerFlow 2.0 foi reescrito do zero.** Ele não compartilha código com a v1. Se você procura o framework original de Deep Research, ele continua mantido no [branch `1.x`](https://github.com/bytedance/deer-flow/tree/main-1.x), e contribuições lá ainda são bem-vindas. O desenvolvimento ativo passou para a 2.0.

## Site oficial

Saiba mais e veja **demos reais** no nosso [**site oficial**](https://deerflow.tech).
Os estudos de caso da landing page abrem como vitrines somente leitura, liberadas por allowlist, sem exigir login.

## Projetos irmãos

<img width="446" height="280" alt="image" align="middle" src="https://github.com/user-attachments/assets/077edef4-d560-41af-bb0d-d0a5f14fcc20" />

- [**LLM Space**](https://github.com/deer-flow/llm-space) - Conheça a nossa arma secreta por trás do DeerFlow: uma ferramenta desktop para prototipar ideias de agentes, inspecionar cada passo do harness, reproduzir falhas e medir desempenho.

## Coding Plan da ByteDance Volcengine

- Recomendamos fortemente usar Doubao-Seed-2.0-Code, DeepSeek v3.2 e Kimi 2.5 para rodar o DeerFlow
- [Saiba mais](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陆地区的开发者请点击这里](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

O reader, a busca na web e a busca de imagens do InfoQuest usam um timeout de inatividade de 30 segundos para conexão e leitura HTTP. As configurações `timeout` e `navigation_timeout` do crawl continuam sendo opções separadas, do lado do servidor, e não controlam o timeout HTTP local.

O DeerFlow passou a integrar o conjunto de ferramentas de busca e crawling inteligentes desenvolvido pela própria BytePlus: [InfoQuest (com experiência online gratuita)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Índice

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Site oficial](#site-oficial)
  - [Projetos irmãos](#projetos-irmãos)
  - [Coding Plan da ByteDance Volcengine](#coding-plan-da-bytedance-volcengine)
  - [InfoQuest](#infoquest)
  - [Índice](#índice)
  - [Configuração do agente em uma linha](#configuração-do-agente-em-uma-linha)
  - [Início rápido](#início-rápido)
    - [Configuração](#configuração)
    - [Executando a aplicação](#executando-a-aplicação)
      - [Dimensionamento da implantação](#dimensionamento-da-implantação)
      - [Opção 1: Docker (recomendado)](#opção-1-docker-recomendado)
      - [Atualizando um checkout existente](#atualizando-um-checkout-existente)
      - [Opção 2: desenvolvimento local](#opção-2-desenvolvimento-local)
      - [Modos de inicialização](#modos-de-inicialização)
      - [LangGraph Studio (opcional)](#langgraph-studio-opcional)
      - [Implantação em produção com Docker](#implantação-em-produção-com-docker)
    - [Avançado](#avançado)
      - [Modo de sandbox](#modo-de-sandbox)
      - [Servidor MCP](#servidor-mcp)
      - [Canais de IM](#canais-de-im)
      - [Correlação de trace de requisições](#correlação-de-trace-de-requisições)
      - [Tracing com LangSmith](#tracing-com-langsmith)
      - [Tracing com Langfuse](#tracing-com-langfuse)
      - [Tracing com Monocle](#tracing-com-monocle)
      - [Usando vários provedores](#usando-vários-provedores)
      - [Ações de stream em runs existentes](#ações-de-stream-em-runs-existentes)
      - [Tokens de acesso pessoal](#tokens-de-acesso-pessoal)
  - [De Deep Research a super agent harness](#de-deep-research-a-super-agent-harness)
  - [Principais recursos](#principais-recursos)
    - [Skills e ferramentas](#skills-e-ferramentas)
      - [Exportando skills personalizadas](#exportando-skills-personalizadas)
      - [Integração com o Claude Code](#integração-com-o-claude-code)
    - [Recuperação de conhecimento privado (RAGFlow)](#recuperação-de-conhecimento-privado-ragflow)
    - [Arquivo de conversas](#arquivo-de-conversas)
    - [Objetivos de sessão](#objetivos-de-sessão)
    - [Compactação manual de contexto](#compactação-manual-de-contexto)
    - [Sub-agents](#sub-agents)
    - [Sandbox e sistema de arquivos](#sandbox-e-sistema-de-arquivos)
    - [Controle agêntico do navegador](#controle-agêntico-do-navegador)
    - [Engenharia de contexto](#engenharia-de-contexto)
    - [Leitura de uma conversa referenciada](#leitura-de-uma-conversa-referenciada)
    - [Notas da tarefa atual](#notas-da-tarefa-atual)
    - [Memória de longo prazo](#memória-de-longo-prazo)
  - [Modelos recomendados](#modelos-recomendados)
  - [Cliente Python embutido](#cliente-python-embutido)
  - [Projetos](#projetos)
    - [Instruções do projeto](#instruções-do-projeto)
    - [Estante de documentos](#estante-de-documentos)
    - [Semântica de leitura do arquivamento](#semântica-de-leitura-do-arquivamento)
    - [Lixeira](#lixeira)
  - [Tarefas agendadas](#tarefas-agendadas)
    - [Pré-visualizar ocorrências de cron pela API](#pré-visualizar-ocorrências-de-cron-pela-api)
    - [Notas de atualização](#notas-de-atualização)
  - [Workbench de terminal (TUI)](#workbench-de-terminal-tui)
  - [Documentação](#documentação)
  - [⚠️ Aviso de segurança](#️-aviso-de-segurança)
    - [Implantação inadequada pode introduzir riscos de segurança](#implantação-inadequada-pode-introduzir-riscos-de-segurança)
    - [Admin do Gateway equivale a execução de código](#admin-do-gateway-equivale-a-execução-de-código)
    - [Papéis de mensagem em chats externos](#papéis-de-mensagem-em-chats-externos)
    - [Padrões de implantação](#padrões-de-implantação)
    - [Recomendações de segurança](#recomendações-de-segurança)
  - [Contribuindo](#contribuindo)
  - [Licença](#licença)
  - [Agradecimentos](#agradecimentos)
    - [Principais contribuidores](#principais-contribuidores)
  - [Histórico de estrelas](#histórico-de-estrelas)

## Configuração do agente em uma linha

Se você usa Claude Code, Codex, Cursor, Windsurf ou outro agente de código, dá para passar as instruções de configuração em uma única frase:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

Esse prompt foi pensado para agentes de código. Ele manda o agente clonar o repositório se for preciso, escolher Docker quando disponível e parar informando o próximo comando exato, além de qualquer configuração que o usuário ainda precise fornecer.

## Início rápido

### Configuração

Operadores podem estender os prompts do lead agent, dos subagents e da extração do DeerMem com configuração literal de prepend/append, sem editar os templates do código-fonte. Veja [prompt overlays](backend/docs/CONFIGURATION.md#prompt-overlays).

O [`request_admission`](backend/docs/CONFIGURATION.md#model-request-admission) opcional, definido por modelo, espaça as requisições para ajudar a ficar dentro dos limites de requisições por minuto do provedor. Vem desativado por padrão; o guia do link explica como ativar.

Para o endpoint oficial do Gemini compatível com OpenAI, do Google, use o [perfil de reasoning do Gemini](backend/docs/CONFIGURATION.md#gemini-via-googles-openai-compatible-endpoint).

1. **Clone o repositório do DeerFlow**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Rode o assistente de configuração**

   No diretório raiz do projeto (`deer-flow/`), execute:

   ```bash
   make setup
   ```

   Isso abre um assistente interativo que ajuda você a escolher um provedor de LLM, uma busca na web opcional e preferências de execução e segurança, como modo de sandbox, acesso ao bash e ferramentas de escrita de arquivos. Ele gera um `config.yaml` mínimo e grava suas chaves no `.env`. Leva cerca de 2 minutos.

   O assistente também permite configurar um provedor de busca na web opcional, ou deixar isso para depois.

   Os fetches de página do Jina, do Browserless e do InfoQuest resolvem links relativos e origens de imagem usando a URL da página solicitada (ou uma URL base válida do HTML), de modo que o Markdown retornado traz os destinos completos. A resolução de links preserva o HTML de origem ao redor, inclusive a formatação de páginas malformadas.

   Os fetches do Jina aceitam novas tentativas limitadas, por opt-in, via `max_retries` (padrão `0`) e `retry_budget_seconds` (padrão `30`) na configuração da ferramenta. As esperas entre tentativas são aleatórias dentro do orçamento de tempo. Novas tentativas podem aumentar o número de requisições ao upstream e o custo; veja [Jina fetch retries](backend/docs/CONFIGURATION.md#jina-fetch-retries).

   Rode `make doctor` a qualquer momento para verificar sua configuração e receber dicas práticas de correção. Se você for abrir uma issue no GitHub sobre um problema de configuração local ou de runtime, rode `make support-bundle`. O comando mostra os próximos passos para quem reporta, grava um arquivo `*-issue-summary.md` para colar na issue, um arquivo `*-issue-draft.md` para abertura de issue assistida por IA e um zip opcional de evidências em `.deer-flow/support-bundles/`. Se um assistente de IA abrir a issue, parta do rascunho e substitua cada placeholder REQUIRED em vez de inventar os fatos que faltam. Anexe o zip só se um mantenedor pedir, ou se o resumo sozinho não bastar. Mantenedores e ferramentas de triagem por IA podem começar pelo `triage.json`; o bundle inclui apenas diagnósticos com dados sensíveis removidos e manifestos de arquivos, e não inclui o `.env`, mensagens brutas de conversas nem o conteúdo de arquivos do usuário.

   > **Configuração avançada / manual**: se você prefere editar o `config.yaml` diretamente, rode `make config` para copiar o template completo. A detecção automática de dependências opcionais aceita arquivos de configuração UTF-8 com ou sem byte-order mark (BOM). Veja o `config.example.yaml` para a referência completa, incluindo provedores baseados em CLI (Codex CLI, Claude Code OAuth), OpenRouter, Responses API, limites de runtime de subagents como `subagents.max_total_per_run` e mais.

   O preço opcional por modelo precisa usar uma única moeda em todos os modelos com preço. Quando as moedas estão misturadas, o DeerFlow desativa as estimativas de custo do Console em vez de mostrar um total inválido.

   Administradores também podem abrir **Settings → Models** para adicionar, editar, testar e ativar ou desativar modelos compartilhados de Chat Completions compatíveis com OpenAI, sem editar o `config.yaml`. Informe um nome único, a URL base, o ID do modelo e, se quiser, uma chave de API; ao salvar, a lista de modelos do chat é atualizada. O teste de conexão envia uma requisição curta de tool call em streaming e pode gerar cobrança do provedor. Ele não salva o rascunho nem verifica suporte a imagens; defina o suporte a imagens e os limites de tokens conforme a documentação do provedor. Modelos oficiais da DeepSeek em `https://api.deepseek.com` ou `https://api.deepseek.com/v1` (porta HTTPS padrão) usam automaticamente o adaptador DeepSeek do DeerFlow, que preserva o conteúdo de reasoning entre tool calls e respeita os limites de tokens de saída. O chat usa o modo de thinking selecionado; o teste de conexão desativa o thinking temporariamente porque a DeepSeek rejeita a seleção forçada de ferramenta nesse modo. O teste verifica a conectividade de ferramentas em streaming, e não todos os fluxos do agente nem o comportamento do modo thinking. Perfis DeepSeek já salvos recebem esse adaptador sem que seja preciso informar as credenciais de novo. Configurações específicas da DeepSeek para proxies de terceiros, outros adaptadores nativos e configurações avançadas de reasoning continuam sendo feitas em YAML.

   Os testes de regressão da DeepSeek rodam offline junto com a suíte normal do backend. Para verificar o provedor real de forma explícita, defina `DEEPSEEK_TEST_API_KEY` no seu ambiente e rode a partir de `backend/`:

   ```bash
   DEER_FLOW_RUN_LIVE_TESTS=1 uv run --no-sync pytest tests/test_managed_deepseek_live.py -q
   ```

   Esses testes são opt-in, enviam requisições curtas à DeepSeek e podem gerar cobrança; eles usam estado temporário, nunca salvam credenciais no catálogo da implantação e são pulados no CI. `DEEPSEEK_TEST_MODEL` permite escolher outro ID de modelo da DeepSeek (padrão: `deepseek-flash`). Os mesmos testes podem ser rodados em revisões com e sem a correção; o resultado esperado é sempre sucesso.

   Os modelos definidos em YAML continuam somente leitura nessa página e têm precedência em conflitos de nome. Os modelos gerenciados entram depois dos modelos YAML; as edições valem para novos snapshots de configuração, enquanto runs ativos mantêm o snapshot que já tinham. Desativar um modelo o remove de seleções e resoluções futuras, então atualize antes qualquer definição de agente personalizado ou de tarefa agendada que o referencie explicitamente. Os modelos gerenciados são compartilhados pela implantação, não são perfis pessoais de chave de API, e continuam sujeitos à política de autorização de modelos existente.

   O catálogo criptografado e uma chave de criptografia local gerada ficam em `$DEER_FLOW_HOME/managed-models/` (padrão `.deer-flow/managed-models/`). Persista e faça backup do **diretório inteiro**, restrinja o acesso no sistema de arquivos e compartilhe-o entre os workers/réplicas do Gateway que devem usar o mesmo catálogo. A chave local é protegida por permissões do sistema de arquivos; a criptografia não protege contra quem consegue ler os dois arquivos. Perder a chave exige restaurar o backup. Leituras e escritas falham se o catálogo não puder ser descriptografado, em vez de substituí-lo. Esse armazenamento é independente do backend SQL e funciona com mounts YAML somente leitura.

   Quando há vários modelos configurados, abra qualquer um dos seletores de modelo e use a estrela ao lado de um modelo para favoritá-lo. Os favoritos aparecem primeiro tanto no seletor do chat principal quanto no do Side Chat, sem mudar o modelo selecionado ou padrão de nenhum dos dois. Eles ficam guardados para o usuário logado no navegador atual, portanto não sincronizam com outro navegador ou dispositivo e não exigem nenhuma configuração de inicialização. O seletor compacto de favoritos omite a busca de propósito e apenas acrescenta a ordenação por favoritos à lista de modelos em duas linhas.

   <details>
   <summary>Exemplos de configuração manual de modelos</summary>

   ```yaml
   models:
     - name: gpt-4o
       display_name: GPT-4o
       use: langchain_openai:ChatOpenAI
       model: gpt-4o
       api_key: $OPENAI_API_KEY

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENROUTER_API_KEY
       base_url: https://openrouter.ai/api/v1

     - name: gpt-5-responses
       display_name: GPT-5 (Responses API)
       use: langchain_openai:ChatOpenAI
       model: gpt-5
       api_key: $OPENAI_API_KEY
       use_responses_api: true
       output_version: responses/v1

     - name: qwen3-32b-vllm
       display_name: Qwen3 32B (vLLM)
       use: deerflow.models.vllm_provider:VllmChatModel
       model: Qwen/Qwen3-32B
       api_key: $VLLM_API_KEY
       base_url: http://localhost:8000/v1
       supports_thinking: true
       when_thinking_enabled:
         extra_body:
           chat_template_kwargs:
             enable_thinking: true
   ```

   O OpenRouter e gateways semelhantes compatíveis com OpenAI devem ser configurados com `langchain_openai:ChatOpenAI` mais `base_url`. Se você preferir um nome de variável de ambiente específico do provedor, aponte `api_key` para essa variável explicitamente (por exemplo `api_key: $OPENROUTER_API_KEY`).

   Para rotear modelos da OpenAI por `/v1/responses`, continue usando `langchain_openai:ChatOpenAI` e defina `use_responses_api: true` com `output_version: responses/v1`.

   Modelos cujo contrato com o provedor difere das premissas genéricas de thinking/effort do DeerFlow podem declarar, por modelo, um bloco `reasoning:` em forma de mapping (thinking `unsupported`/`optional`/`required`, os valores de effort aceitos com aliases e um padrão, o dialeto do payload e o requisito de histórico de reasoning). O perfil Z.AI GLM-5.3-Flash do assistente de configuração usa esse bloco: o thinking fica ligado em toda chamada de foreground e de background, e o seletor de effort oferece os níveis próprios do modelo, `low`/`high`/`max`. O booleano `reasoning: true` já existente do Ollama continua sendo uma configuração nativa do provedor e é repassado ao ChatOllama. Ao migrar um perfil para um `path` de effort personalizado, remova qualquer configuração antiga de `reasoning_effort` do perfil e dos templates de thinking; a validação da configuração rejeita a chave que sobrar. A interface do chat descarta um effort específico de provedor que estava memorizado quando você troca para um modelo legado que não o anuncia. Perfis sem o bloco mantêm o comportamento atual do provedor. Veja no `config.example.yaml` o formato e a configuração manual equivalente.

   Para o vLLM 0.19.0, use `deerflow.models.vllm_provider:VllmChatModel`. Em modelos de reasoning no estilo Qwen, o DeerFlow liga e desliga o reasoning com `extra_body.chat_template_kwargs.enable_thinking` e preserva o campo não padrão `reasoning` do vLLM ao longo de conversas com tool calls em vários turnos. Configurações legadas de `thinking` são normalizadas automaticamente por compatibilidade. Se o endpoint reportar um snapshot de uso acumulado em cada chunk do streaming, defina `cumulative_stream_usage: true` para que o DeerFlow converta esses snapshots em deltas por chunk; a opção vem desativada por padrão e deixa o uso inalterado quando não há um id de completion estável. Modelos de reasoning também podem exigir que o servidor seja iniciado com `--reasoning-parser ...`. Se a sua implantação local do vLLM aceita qualquer chave de API não vazia, você ainda pode definir `VLLM_API_KEY` com um valor de placeholder.

   Exemplos de provedores baseados em CLI:

   ```yaml
   models:
     - name: gpt-5.4
       display_name: GPT-5.4 (Codex CLI)
       use: deerflow.models.openai_codex_provider:CodexChatModel
       model: gpt-5.4
       supports_thinking: true
       supports_reasoning_effort: true

     - name: claude-sonnet-4.6
       display_name: Claude Sonnet 4.6 (Claude Code OAuth)
       use: deerflow.models.claude_provider:ClaudeChatModel
       model: claude-sonnet-4-6
       max_tokens: 4096
       supports_thinking: true
   ```

   - O Codex CLI lê `~/.codex/auth.json`
   - O provedor de modelo Codex retorna as respostas concluídas sem esperar a conexão SSE fechar. Respostas com falha ou incompletas reportam o erro ou o motivo informado pelo provedor; uma saída parcial não é devolvida como resposta bem-sucedida. Detalhes de erro que não são objetos são reportados como texto.
   - O Claude Code aceita `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_CREDENTIALS_PATH` ou `~/.claude/.credentials.json`
   - As entradas de agentes ACP são separadas dos provedores de modelo: se você configurar `acp_agents.codex`, aponte para um adaptador ACP do Codex, como `npx -y @zed-industries/codex-acp`
   - O MiniMax Code fala ACP diretamente. Instale e autentique, depois adicione como agente ACP:

   ```bash
   npm install --global @minimax-ai/code
   mcode login
   ```

   ```yaml
   acp_agents:
     mcode:
       command: mcode
       args: ["acp"]
       description: MiniMax Code for implementation, refactoring, debugging, and repository tasks
       auto_approve_permissions: false
   ```

   O `mcode` precisa estar no `PATH` do processo do Gateway; instalar só no host do Docker não o torna disponível dentro do container do Gateway. O DeerFlow o invoca por meio de `invoke_acp_agent` em um workspace ACP por thread e repassa os servidores MCP habilitados. Mantenha `auto_approve_permissions: false` para tarefas não confiáveis; ative apenas quando o mcode precisar editar arquivos ou rodar comandos e você confiar na tarefa.
   - No macOS, exporte a autenticação do Claude Code explicitamente, se necessário:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

   As chaves de API também podem ser definidas manualmente no `.env` (recomendado) ou exportadas no seu shell:

   ```bash
   OPENAI_API_KEY=your-openai-api-key
   TAVILY_API_KEY=your-tavily-api-key
   ```

   </details>

Para usar um arquivo dotenv explícito no backend, exporte `DEER_FLOW_ENV_FILE` antes da inicialização, junto com `DEER_FLOW_CONFIG_PATH` se necessário. Por exemplo, a partir de `backend/`:

```bash
DEER_FLOW_ENV_FILE=/srv/deer-flow/stage.env DEER_FLOW_CONFIG_PATH=/srv/deer-flow/stage.yaml make gateway
```

Caminhos dotenv relativos usam o diretório de trabalho do processo do backend; caminhos absolutos funcionam independentemente desse diretório. Variáveis já existentes no processo prevalecem. Um seletor não definido preserva a descoberta padrão do dotenv; um caminho informado que esteja vazio, não exista, não seja um arquivo ou não possa ser lido faz a inicialização falhar. A seleção explícita também falha quando `PYTHON_DOTENV_DISABLED` desativa o carregamento do dotenv. Reinicie depois de alterar o arquivo. Isso seleciona apenas a entrada dotenv do backend: os launchers de shell, o Docker Compose e o frontend mantêm o próprio carregamento de ambiente, e os valores que eles já exportam prevalecem. Não seleciona perfis `ENV` nem isola bancos de dados, armazenamento ou tenants. Veja [backend dotenv selection](backend/docs/CONFIGURATION.md#backend-dotenv-selection).

### Executando a aplicação

#### Dimensionamento da implantação

Use a tabela abaixo como ponto de partida prático para escolher como rodar o DeerFlow:

| Alvo de implantação | Ponto de partida | Recomendado | Observações |
|---------|-----------|------------|-------|
| Avaliação local / `make dev` | 4 vCPU, 8 GB de RAM, 20 GB livres em SSD | 8 vCPU, 16 GB de RAM | Bom para um desenvolvedor ou uma sessão leve com APIs de modelo hospedadas. `2 vCPU / 4 GB` normalmente não basta. |
| Desenvolvimento com Docker / `make docker-start` | 4 vCPU, 8 GB de RAM, 25 GB livres em SSD | 8 vCPU, 16 GB de RAM | Builds de imagem, bind mounts e containers de sandbox pedem mais folga do que o desenvolvimento local puro. |
| Servidor de longa duração / `make up` | 8 vCPU, 16 GB de RAM, 40 GB livres em SSD | 16 vCPU, 32 GB de RAM | Preferível para uso compartilhado, runs multiagente, geração de relatórios ou cargas de sandbox mais pesadas. |

- Esses números cobrem o DeerFlow em si. Se você também hospeda um LLM local, dimensione esse serviço à parte.
- Linux com Docker é o alvo recomendado para um servidor persistente. macOS e Windows funcionam melhor como ambientes de desenvolvimento ou avaliação.
- Se o uso de CPU ou memória ficar no limite, primeiro reduza os runs concorrentes e só depois suba para a próxima faixa.

#### Opção 1: Docker (recomendado)

Requer Docker Desktop / Docker Engine e **Docker Compose v2.24+** (`docker compose version`). Clientes Compose mais antigos não conseguem interpretar a sintaxe opcional de `env_file` em `docker/docker-compose-dev.yaml`.

**Desenvolvimento** (hot-reload, mounts do código-fonte):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
make docker-logs    # View logs
```

O `make docker-start` só inicia o `provisioner` quando o `config.yaml` usa o modo provisioner (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` com `provisioner_url`).

Os builds do Docker usam o registry upstream do `uv` por padrão. Se você precisa de mirrors mais rápidos em redes restritas, exporte `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` e `NPM_REGISTRY=https://registry.npmmirror.com` antes de rodar `make docker-init` ou `make docker-start`.

O tráfego de controle do sandbox AIO local é sempre direto: endereços de loopback/privados, hosts de cluster de rótulo único e hostnames internos do Docker/Podman não herdam `HTTP_PROXY` nem `HTTPS_PROXY`. FQDNs externos de sandbox e IPs públicos continuam respeitando as configurações de proxy do ambiente.

Os processos do backend pegam as mudanças do `config.yaml` automaticamente no próximo acesso à configuração, então atualizar metadados de modelo não exige reinício manual durante o desenvolvimento.

Os runs do Gateway usam o `recursion_limit` de nível superior do `config.yaml` quando a requisição de API não informa um. O padrão é `100`; valores válidos por requisição têm precedência, e `max_recursion_limit` (padrão `1000`) limita os dois. As mudanças valem para o próximo run sem reiniciar o Gateway. Essa configuração de nível superior se aplica aos runs da API do Gateway; os runs de canais de IM e do `DeerFlowClient` embutido mantêm os próprios padrões e caminhos de override por chamada. As configurações de armazenamento de checkpoint `database.checkpoint_channel_mode` e `database.checkpoint_delta.snapshot_frequency` (padrão `10`) são exceções: as duas ficam congeladas quando o processo constrói um agente pela primeira vez (inclusive via `DeerFlowClient`) e exigem reinício do processo para serem alteradas com segurança.

A seção opcional `database.checkpoint_cache` (apenas no modo de canal delta) faz cache dos históricos de checkpoint materializados: `type` é `memory` (padrão) ou `redis`, e `max_entries: 0` desativa o cache. O backend `redis` funciona só no Gateway/async; o caminho síncrono da TUI e do cliente embutido aceita apenas `memory`. O cache serve só para desempenho, os resultados são idênticos com ele desativado. Por isso ele nunca é congelado, e workers que compartilham o mesmo banco de checkpoints podem usar configurações de cache diferentes sem problema.

> [!TIP]
> No Linux, se os comandos baseados em Docker falharem com `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, adicione seu usuário ao grupo `docker` e faça login de novo antes de tentar outra vez. Veja a correção completa em [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied).

**Produção** (constrói as imagens localmente, monta a configuração de runtime e os dados):

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

Acesso: http://localhost:2026

O `make up` espera o endpoint `/health` do Gateway antes de reportar sucesso. Se o Gateway não ficar saudável dentro da janela de inicialização, a implantação sai com código diferente de zero e mostra o status dos containers e os logs recentes do Gateway. A imagem de produção parte do ambiente já construído e nunca resolve nem instala dependências Python na inicialização do container.

Para implantações persistentes, configure `database.backend` como `sqlite` ou `postgres`. O backend escolhido é compartilhado pelo checkpointer do LangGraph, pelo LangGraph Store e pelos dados de aplicação do DeerFlow. A seção `checkpointer`, já descontinuada, sobrescreve os dois primeiros quando presente, por compatibilidade.

A inicialização do Gateway repara automaticamente o schema de run-change ausente que afeta alguns bancos existentes (#5516). O reparo preserva o histórico de runs e as posições de mudança existentes; fazer downgrade do reparo para a versão anterior também mantém o schema e as posições exigidos por ela.

Para persistência leve de eventos em processo único, `run_events.backend: jsonl` mantém intacto o conteúdo Unicode das mensagens, inclusive separadores de linha e de parágrafo. Registros JSONL válidos já existentes continuam legíveis sem reescrever os arquivos.

Em auditorias de uso por chamada, um replay imediato da resposta do LLM com o uso preenchido atualiza tanto o uso aninhado quanto os contadores de tokens de nível superior, mesmo que o uso inicial estivesse ausente ou zerado. A requisição original, o modelo e os metadados de status ficam intactos; eventos já gravados não são reescritos. Veja o [contrato de eventos de run](contracts/run_event_stream_contract.json).

O endpoint unificado do nginx é same-origin por padrão e não emite cabeçalhos CORS para o navegador. Se você roda um cliente de navegador em origem separada ou com port-forward, defina `GATEWAY_CORS_ORIGINS` com origens exatas separadas por vírgula, como `http://localhost:3000`; o Gateway então aplica a allowlist de CORS e as verificações de origem de CSRF correspondentes.

Com a autorização granular ativada, as conexões do Live Browser exigem `threads:write` além da posse da thread, mesmo para quem só visualiza frames: a mesma conexão pode controlar o navegador. As verificações de permissão rodam na conexão. Reinicie o Gateway depois de atualizar para desconectar sessões admitidas pelo código antigo.

O login pelo navegador usa cookies de sessão `HttpOnly`. A página de login oferece a opção "keep me signed in", que estende a sessão do navegador quando a requisição é HTTPS (inclusive com `X-Forwarded-Proto: https` confiável) ou HTTP em localhost. A exceção de localhost usa o `Host` direto da requisição e ignora cabeçalhos de host encaminhados. Implantações HTTP públicas, incluindo muitas URLs temporárias de sandbox, voltam para cookies de sessão por padrão. O DeerFlow nunca guarda a senha no armazenamento do navegador; a interface pode lembrar apenas o endereço de e-mail.

O DeerFlow continua usando os cabeçalhos `Forwarded` / `X-Forwarded-*` para recuperar o esquema e a origem vistos pelo navegador quando está atrás de um proxy. O nginx que acompanha o projeto define `X-Forwarded-Proto`, mas preserva um valor HTTPS vindo do upstream e não sobrescreve todos os cabeçalhos encaminhados. Configure o proxy externo confiável para substituir ou remover os cabeçalhos de encaminhamento enviados pelo cliente antes que o tráfego chegue ao DeerFlow.

> [!IMPORTANT]
> O Gateway ainda é dono, em processo, das tasks de runs ativos, então a produção usa por padrão um único worker do Gateway (`GATEWAY_WORKERS=1`). Implantações com vários workers exigem Postgres, a stream bridge do Redis (`stream_bridge.type: redis`), `run_ownership.heartbeat_enabled: true` e `run_events.backend: db`; os event stores de memória/JSONL, locais ao processo, não conseguem garantir recibos de entrega únicos entre workers. A bridge compartilha entre workers a entrega SSE e o replay limitado por `Last-Event-ID`. Quando um cursor de reconexão válido já foi aparado, ou quando um assinante que já havia iniciado uma espera em stream vazio fica para trás antes da primeira entrega, Memory e Redis emitem um evento SSE `gap` legível por máquina em vez de devolver um replay parcial em silêncio; a Web UI recarrega o estado durável de thread/eventos e retoma a partir do trecho final retido. A reconciliação de leases marca como erro os runs de workers mortos, persiste seus recibos de entrega, publica o marcador terminal do stream, agenda a limpeza do stream retido e atualiza o status da thread afetada. SSE, `/wait` e consumidores internos de stream usam `stream_bridge.heartbeat_interval_seconds` (padrão `15`) para checar atividade em períodos ociosos; alterar esse valor exige reiniciar o Gateway. IDs de reconexão do Redis malformados passam a acompanhar os novos eventos ao vivo em vez de reproduzir o buffer retido, e o TTL rotativo do buffer retido (`stream_ttl_seconds`) continua sendo uma rede de segurança para limpeza, não um timeout de run. O estado dos canais de IM e outros serviços locais ao processo ainda precisam de coordenação própria entre workers.
>
> Em implantações JSONL de processo único, cancelar uma mutação do event store já admitida espera o I/O de arquivo em background, o rollback e a contabilidade terminarem antes de liberar o lock de escrita da thread. Isso impede que uma escrita antiga cancelada recrie registros apagados ou desfaça uma escrita posterior bem-sucedida. Por isso o cancelamento pode ficar esperando um armazenamento lento; ele não interrompe uma operação de sistema de arquivos em andamento. Chamadores que ainda aguardam o lock podem cancelar sem iniciar uma mutação. Um lote que abrange várias threads termina o grupo da thread atual antes de propagar o cancelamento; os grupos de threads seguintes não começam.
>
> Depois que um run publica o marcador terminal do stream, o `RunRecord` local ao processo continua disponível pelo período de tolerância de cinco minutos já existente antes da limpeza; o histórico durável de runs continua disponível pelo `RunStore`, enquanto a stream bridge retém o trecho final de entrega no seu próprio cronograma de limpeza.
>
> O cancelamento de um run pode cair em qualquer worker do Gateway. Um worker que não é dono agora persiste o pedido de interrupção ou rollback para o dono ativo, que o observa durante a renovação do lease e executa o fluxo normal de cancelamento; o roteamento do load balancer sozinho não gera mais um 409. A primeira ação aceita vence mesmo que uma nova tentativa caia no dono, e o cancelamento aceito compete de forma atômica com a conclusão pelo dono. Donos mortos continuam seguindo a tomada de lease e a recuperação de órfãos. A latência de cancelamento fica, portanto, limitada pelo intervalo de heartbeat do lease.

> Cancelar um probe de recuperação de modelo, inclusive enquanto ele está na fila ou esperando para tentar de novo, permite que a próxima chamada verifique se o provedor se recuperou. O cancelamento não conta como falha do provedor nem libera o probe de recuperação ativo de outra chamada.
>
> Com o heartbeat de lease ativado, um erro transitório de renovação no RunStore só é repetido até o último lease confirmado expirar; o worker obsoleto então cancela a execução local e suprime a finalização de checkpoint, de completion hook, de recibo de entrega e de status da thread. Um efeito colateral de ferramenta remota que já esteja em andamento pode ficar fora do alcance do cancelamento local.
>
> A reconciliação usa um claim atômico de takeover que confere o lease de novo depois da seleção de candidatos, de modo que uma renovação bem-sucedida pelo dono vence a recuperação de órfãos e apenas um reconciliador pode reportar um run como recuperado. Quando vários workers do Gateway compartilham o backend de sandbox Docker/AIO ou E2B, configure também `sandbox.ownership.type: redis`; o E2B usa os leases durante a inicialização em background e a reconciliação periódica para que a limpeza de duplicados/órfãos não encerre o sandbox de um peer ativo.

Veja o [CONTRIBUTING.md](CONTRIBUTING.md) para o guia detalhado de desenvolvimento com Docker.

#### Atualizando um checkout existente

Mantenha `config.yaml`, `.env` e `extensions_config.json`. Pare os serviços que você usa hoje, rode `git pull --ff-only` e inicie o mesmo modo de novo. Não rode `make config` nem `make docker-init` outra vez em uma atualização de código de rotina. Se a nova versão exigir mudanças de configuração, rode `make config-upgrade` antes de reiniciar. Veja em [Operations and Troubleshooting](frontend/src/content/en/application/operations-and-troubleshooting.mdx#upgrading-an-existing-checkout) os comandos de cada modo.

#### Opção 2: desenvolvimento local

Se você prefere rodar os serviços localmente:

Pré-requisito: conclua antes os passos de "Configuração" acima (`make setup`). O `make dev` exige um `config.yaml` válido na raiz do projeto. Defina `DEER_FLOW_PROJECT_ROOT` para indicar essa raiz explicitamente, ou `DEER_FLOW_CONFIG_PATH` para apontar para um arquivo de configuração específico. O estado de runtime fica por padrão em `.deer-flow`, dentro da raiz do projeto, e pode ser movido com `DEER_FLOW_HOME`; as skills ficam por padrão em `skills/`, dentro da raiz do projeto, e podem ser movidas com `DEER_FLOW_SKILLS_PATH`. Rode `make doctor` para verificar sua configuração antes de começar.
No Windows, rode o fluxo de desenvolvimento local pelo Git Bash. Os shells nativos `cmd.exe` e PowerShell não são suportados pelos scripts de serviço baseados em bash, e o WSL não é garantido porque alguns scripts dependem de utilitários do Git for Windows, como o `cygpath`.

Os comandos `make` documentados na raiz invocam os arquivos `.sh` do repositório explicitamente pelo Bash. Assim eles continuam funcionando a partir de arquivos de código-fonte compactados ou de sistemas de arquivos que não preservam os bits de execução POSIX. Para chamar um script diretamente em um checkout desses, use `bash ./scripts/<name>.sh ...`.

1. **Verifique os pré-requisitos**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

   Os pontos de entrada locais `make check`, `make install`, `make dev` e `make start` usam um executável `pnpm` direto quando disponível e, caso contrário, recorrem a `corepack pnpm`. Com o Python nativo do Windows, o runner compartilhado verifica `pnpm.cmd` antes da busca genérica por `pnpm`, que segue `PATH`/`PATHEXT` e pode escolher um `.exe` ou `.bat` no mesmo diretório do PATH ou em um anterior. O fallback do Corepack, da mesma forma, verifica `corepack.cmd` antes de `corepack`. O Python POSIX mantém os nomes genéricos em primeiro lugar, inclusive rodando sob MSYS/Cygwin. O runner e os diagnósticos resolvem os caminhos do repositório de forma absoluta, então essas verificações funcionam independentemente do diretório atual de quem chama. O Corepack roda a partir de `frontend/`, portanto respeita a versão do `packageManager` fixada em `frontend/package.json`; não é preciso habilitar um shim global do pnpm.

2. **Instale as dependências**:
   ```bash
   make install  # Install backend + frontend dependencies + pre-commit hooks
   ```

   A configuração dos hooks chama o pre-commit pelo uv, então o diretório de ferramentas do uv não precisa estar no `PATH`.

3. **(Opcional) Baixe antes a imagem do sandbox**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```
   Lê a imagem de sandbox configurada no `config.yaml` em UTF-8, com ou sem BOM inicial, com quebras de linha LF ou CRLF.
   No macOS, um pull bem-sucedido do Apple Container conclui esta etapa mesmo sem o Docker instalado. Se o Docker estiver disponível, a imagem dele também é baixada.

4. **Inicie os serviços**:
   ```bash
   make dev
   ```

5. **Acesse**: http://localhost:2026

6. **(Opcional) Carregue dados de memória de exemplo para revisão local**: abra `Settings > Memory`, clique em **Import memory** e selecione `backend/docs/memory-settings-sample.json`. O navegador importa para a memória do usuário logado.

   Para substituir a memória de todos os usuários registrados em um ambiente de revisão descartável:

   ```bash
   cd backend
   uv run python ../scripts/load_memory_sample.py --all-users
   ```

   O modo em massa suporta registros de usuários em SQLite/PostgreSQL, cria backups com timestamp em `.deer-flow/memory-sample-backups/` e rejeita o modo não persistente `database.backend: memory`. Veja o fluxo completo de revisão em [backend/docs/MEMORY_SETTINGS_REVIEW.md](backend/docs/MEMORY_SETTINGS_REVIEW.md).

Os serviços locais sempre usam as portas internas (`8001`, `3000` e `2026`). A variável `PORT` do `.env` da raiz configura apenas o ingress publicado do Docker; ela não muda a porta do Next.js usada pelo `make dev`.

#### Modos de inicialização

O DeerFlow roda o runtime do agente dentro da API do Gateway. O modo de desenvolvimento ativa o hot-reload; o modo de produção usa um frontend já construído.

| | **Local em foreground** | **Local como daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |

| Ação | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Parar** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Reiniciar** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

O `make start` e o `make start-daemon` reconstroem o frontend com `next build` a cada execução. Para reaproveitar o último build, passe `SKIP_FRONTEND_BUILD=1` (ou acrescente `--skip-frontend-build` ao chamar `./scripts/serve.sh --prod` diretamente). Isso é opt-in: a execução falha logo de início quando `frontend/.next` não tem um build concluído.

O Gateway é dono de `/api/langgraph/*` e traduz esses caminhos públicos compatíveis com LangGraph para seus routers nativos em `/api/*`, atrás do nginx.

Para uma demo somente leitura sem o Gateway, rode `make build-static` a partir de `frontend/` e depois `HOSTNAME=127.0.0.1 PORT=3000 node --env-file=.env .next/standalone/server.js` no mesmo diretório. O build inclui os assets públicos da demo e resolve localmente as leituras de API suportadas por ela; escritas não ficam disponíveis. Para mostrar a contagem de estrelas do GitHub na página inicial, defina `GITHUB_OAUTH_TOKEN` em `frontend/.env` antes de iniciar o Node. O token fica no servidor; se faltarem credenciais ou o GitHub falhar, a contagem é ocultada. Reinicie o Node depois de trocar o token; não é preciso reconstruir.

#### LangGraph Studio (opcional)

A topologia padrão do `make dev` usa o runtime do DeerFlow embutido no Gateway e não exige o LangGraph Studio. Para inspecionar e testar o grafo registrado do lead agent com o servidor de desenvolvimento standalone, rode o comando a partir de `backend/` para que a CLI encontre o `langgraph.json`:

```bash
cd backend
uv run langgraph dev --allow-blocking
```

O comando mostra as URLs da API local e da interface do Studio. Esse servidor em memória serve apenas para desenvolvimento e testes. A flag permite a configuração síncrona do DeerFlow e a montagem da graph factory durante requisições locais do Studio; ela não deve ser tratada como configuração de servidor de produção. A autenticação local do Studio é feita automaticamente, então a conexão não exige cabeçalhos personalizados. Para cargas de produção, use os modos de inicialização de produção documentados do DeerFlow ou uma implantação LangSmith suportada. Nesse modo standalone, a posse e a proveniência dos assistants pertencem ao servidor: o Studio consegue descobrir os grafos registrados e os assistants que ele mesmo cria, e a seleção normal de versão de assistant continua disponível. Antes de o runtime local travado carregar o store de desenvolvimento persistido, o DeerFlow repara linhas de assistant e históricos de versão legados, para que metadados antigos de cliente não restaurem privilégios de servidor nem sejam descartados pela limpeza de inicialização do runtime. Mantenha as dependências do backend sincronizadas com `uv sync`; esse caminho de compatibilidade exige as versões declaradas do runtime LangGraph e registra um aviso se o contrato do store persistido deixar de corresponder ao esperado. O comando documentado usa o loader de custom app baseado em arquivo do LangGraph, que também é coberto diretamente pelos testes de regressão do DeerFlow.

Runs standalone que usam `if_not_exists="create"` mantêm a configuração e os metadados do run na thread recém-criada, incluindo tags pesquisáveis; os metadados do run têm precedência em chaves duplicadas. A posse da thread e a encarnação do MCP continuam pertencendo ao servidor, e runs posteriores não substituem os metadados de criação da thread.

Em fluxos que invocam `backend/langgraph.json` pelo LangGraph Studio ou por um LangGraph Server direto, o DeerFlow consome a identidade autenticada publicada por esse runtime e a usa para a configuração/SOUL de agentes personalizados, skills de usuário e política de skills, uploads, dados de thread e leituras/escritas de memória. Isso mantém os runs autenticados fora do bucket de sistema de arquivos compartilhado `default`, e a identidade pertencente ao servidor tem precedência sobre valores comuns de `user_id` enviados pelo cliente. Identidades externas, como endereços de e-mail, são mapeadas para IDs de usuário estáveis, resistentes a colisão e seguros para nomes de diretório antes de acessar o armazenamento do DeerFlow. A topologia de serviço padrão do DeerFlow continua sendo o runtime embutido no Gateway descrito acima.

Os runs do Gateway aplicam automaticamente a entrega nativa para artifacts criados ou modificados em `/mnt/user-data/outputs`: o `present_files` precisa apresentar ao menos uma saída produzida pelo run atual, e o recibo terminal `run.delivery` precisa ficar registrado de forma durável. Os caminhos virtuais de artifact são resolvidos dentro do mesmo escopo autenticado de usuário e thread que produziu a saída, antes de o limite do diretório de saída ser validado. Runs que não produzem artifacts de saída mantêm o comportamento normal de conversa.

Chamadas `runs.wait()` com escopo de thread que terminam com `status: error` reportam o erro do run atual, e não uma resposta anterior. O SDK Python assíncrono do LangGraph lança exceção por padrão; passe `raise_error=False` para inspecionar o status e o erro retornados.

Os eventos customizados nativos do DeerFlow estão disponíveis pelas duas interfaces de streaming do LangGraph: clientes nativos podem continuar assinando `stream_mode="custom"`, enquanto integrações baseadas em callback podem consumir os mesmos payloads como registros `on_custom_event` de `astream_events(version="v2")`. O nome do evento no callback corresponde ao campo `type` do payload.

#### Implantação em produção com Docker

O `./scripts/deploy.sh` permite construir e iniciar em etapas separadas:

```bash
# One-step (build + start)
./scripts/deploy.sh

# Two-step (build once, start later)
./scripts/deploy.sh build       # build all images
./scripts/deploy.sh start       # start pre-built images

# Stop
./scripts/deploy.sh down
```

### Avançado
#### Modo de sandbox

O DeerFlow suporta vários modos de execução de sandbox:
- **Execução local** (roda o código do sandbox diretamente na máquina host)
- **Execução em Docker** (roda o código do sandbox em containers Docker isolados)
- **Execução em Docker com Kubernetes** (roda o código do sandbox em pods do Kubernetes por meio do serviço provisioner)

As referências a sandbox no estado da conversa pertencem ao servidor. As APIs externas de run e de estado de thread rejeitam valores de `sandbox` enviados por quem chama; ao restaurar um checkpoint, o runtime resolve a referência contra o usuário autenticado e a thread antes que uma ferramenta possa reutilizá-la. A ausência do ID de thread do runtime gera erro mesmo quando o sandbox referenciado está em cache.

Quando o Bash do host está habilitado na execução local, o DeerFlow começa a detecção do sistema operacional com `uname -s` e depois usa `sw_vers` no Darwin. No Linux, ele lê arquivos de sistema do host, como `/etc/os-release`, apenas quando a política de sandbox ativa permite. As verificações de caminho do sistema de arquivos do host continuam valendo; depois de um caminho bloqueado, o agente é orientado a usar um probe permitido, só com comando, ou um caminho virtual, em vez de repetir o comando rejeitado.

No desenvolvimento com Docker, a inicialização dos serviços segue o modo de sandbox do `config.yaml`. Nos modos Local/Docker, o `provisioner` não é iniciado.

Veja o [Guia de configuração do sandbox](backend/docs/CONFIGURATION.md#sandbox) para configurar o modo de sua preferência.

As listagens de diretórios remotos reportam falhas de travessia (por exemplo, diretórios ilegíveis) como resultados incompletos, mesmo quando nenhuma entrada foi retornada. Um caminho inicial inexistente é reportado à parte como "Directory not found."

O [provedor opcional de sandbox em nuvem Tenki](backend/packages/harness/deerflow/community/tenki/README.md) usa o Tenki SDK 1.4.0 ou mais recente. Comandos que estouram o timeout preservam a saída parcial e reportam `Exit Code: 124`; health checks malsucedidos não conseguem reaproveitar um sandbox aquecido. Os health probes toleram saída do login shell em volta da linha `ok`, e as falhas registram em log o ID do sandbox e a saída do probe antes de substituir o sandbox.

#### Servidor MCP

Na interface do chat, ative **Token Usage → Debug** para inspecionar chamadas de ferramentas genéricas/MCP. Cada painel **Tool details** começa recolhido e mostra o nome da ferramenta, o ID da chamada, a entrada e o resultado recebido ou o erro explícito. Pré-visualizações grandes são truncadas; campos cujos nomes ultrapassam o orçamento restante da pré-visualização são omitidos em vez de renomeados.
As pré-visualizações estruturadas mantêm a sintaxe JSON completa, incluindo strings escapadas e delimitadores de fechamento.
As pré-visualizações de arrays param quando o orçamento de texto não comporta mais um elemento; valores literais de reticências são preservados.
Marcadores gerados consecutivos no fim de um array compartilham uma única reticência que indica um sufixo omitido; marcadores antes de valores posteriores mantêm suas posições.
Os resultados em texto mantêm a representação original, incluindo IDs numéricos grandes e chaves JSON duplicadas, sem novo parsing. Texto acima do limite é mostrado como prefixo, com um aviso de truncamento; objetos e arrays estruturados são formatados separadamente.
As ações de copiar copiam apenas a pré-visualização exibida. Trata-se de uma visão, no frontend, de dados que o navegador já recebeu, sem uma camada adicional de remoção de segredos.

Caminhos e URLs produzidos por ferramentas podem ser mantidos como handles curtos de artifact ao longo da compactação de contexto (`tool_artifacts` no `config.yaml`). Os handles distinguem ocorrências separadas de resultados de ferramenta, mesmo quando um provedor reutiliza IDs de chamada. URLs de arquivo detectadas preservam suas query strings e fragmentos. Quando a remoção de PII está ativada, os rótulos de artifact visíveis ao modelo seguem essa política; as referências internas ficam intactas para a resolução de argumentos de ferramentas. O limite configurado do registro mantém os artifacts mais recentes, enquanto identidades de processamento salvas em checkpoint impedem que resultados descartados sejam recapturados depois de um reinício. A resolução roda antes das verificações de autorização e de segurança de escrita; handles desconhecidos ou expirados retornam erro sem executar a ferramenta. Resultados estruturados pequenos e desconhecidos podem ser mantidos como JSON completo de até 4096 bytes UTF-8; payloads vazios ou grandes demais são ignorados. Os handles são locais ao agente: os argumentos de task resolvem handles do pai em referências concretas, e os relatórios delegados precisam devolver referências concretas, e não handles locais do filho. Uma projeção truncada para o modelo informa quantos handles foram omitidos.

O DeerFlow suporta servidores MCP e skills configuráveis para ampliar suas capacidades.
Para servidores MCP HTTP/SSE, há suporte a fluxos de token OAuth (`client_credentials`, `refresh_token`).
As chamadas duráveis de status e cancelamento de task em HTTP/SSE selecionam as credenciais `user_auth` configuradas usando o dono persistido da task, inclusive depois de um reinício; segredos por requisição não são retidos para chamadas em background. Se uma credencial com escopo de requisição sobrescreve a autenticação do submit, as duas credenciais precisam autorizar o acesso à mesma task remota.
Para servidores MCP stdio, os timeouts por chamada de ferramenta podem ser configurados com `tool_call_timeout`; as chamadas duráveis de task em background respeitam a mesma configuração também em servidores HTTP/SSE.
Em saídas de arquivo via stdio, um nome de arquivo sem caminho é vinculado a um arquivo criado ou alterado por aquela chamada, desde que a correspondência seja única. Nomes de arquivo embutidos em caminhos não relacionados, incluindo caminhos Windows com barra invertida, ficam intactos.
Em chamadas de task em background via HTTP/SSE, o `session_init_timeout` limita separadamente o conjunto formado pelo estabelecimento da conexão (incluindo o evento de endpoint SSE) e pela inicialização do MCP; ele deixa de valer assim que a chamada da ferramenta começa. Os erros de prazo de inicialização identificam o servidor e o limite de tempo configurado.
Subagents comuns de `task` mantêm, para chamadas MCP, a encarnação de thread capturada pelo run pai, inclusive em threads legadas, de modo que a delegação preserva o mesmo escopo de ciclo de vida.
Os nomes de ferramentas MCP recebem o prefixo `<server_name>_` por padrão, para evitar colisões entre servidores. Se um servidor já usa namespace nas próprias ferramentas, defina `tool_name_prefix: false` para esse servidor no `extensions_config.json` e os nomes originais serão mantidos. Desative o prefixo só quando os nomes resultantes continuarem únicos entre todos os servidores habilitados.
Para usuários logados, o toggle de notificações, o modelo padrão, o modo de conversa e o reasoning effort são salvos na conta e restaurados em outros navegadores ou depois de limpar o armazenamento do navegador. A permissão de notificação do navegador ainda precisa ser concedida em cada dispositivo. As alterações são reenviadas depois de falhas de rede; alterações não enviadas sobrevivem a um reload na mesma aba. Edições concorrentes em campos diferentes são preservadas; no mesmo campo, vence a última escrita no servidor. Preferências de navegador já existentes e sem escopo não são enviadas automaticamente, porque não têm uma conta dona; selecione essas configurações de novo uma vez depois de atualizar. Demos estáticas e ambientes de desenvolvimento com autenticação desativada mantêm as configurações locais do navegador. Overrides de modelo por thread e outras preferências de exibição continuam locais.

Em um novo chat, a pergunta enviada fica acima do reasoning em streaming e dos passos de ferramentas enquanto o servidor cria a conversa e confirma a mensagem.

O Capability Center agrupa os plugins em colaboração de escritório, documentos e conhecimento, busca e pesquisa, negócios e dados, e desenvolvimento e operações. O diretório inclui referências de configuração ao lado das configurações MCP existentes e do Lark. Integrações recomendadas e suporte nativo não significam que exista uma conexão instalada ou verificada; o filtro Installed mostra apenas as entradas MCP configuradas e o Lark instalado.

As conexões MCP pessoais configuradas na interface web são persistidas por usuário.
As ferramentas da implantação continuam compartilhadas. Administradores podem adicionar, editar, habilitar, desabilitar e excluir servidores MCP compartilhados em **Platform provided**; usuários comuns veem o status deles, sem controles. Os switches de plugins pessoais afetam apenas as conexões do usuário logado. Veja [connection ownership](docs/capability-center.md#personal-and-deployment-mcp-configuration).

Para manifests de plugins, registro de adaptadores e seleção de capacidades do Agent, veja o [contrato de integração do Capability Center](docs/capability-center.md).

As notificações em grupo do DingTalk e do WeCom e o HubSpot CRM são plugins configuráveis que já acompanham o projeto. Os administradores fornecem as credenciais do robô ou um token de private app do HubSpot; a partir daí os Agents podem enviar as notificações em grupo solicitadas, listar empresas ou criar contatos. Salvar a configuração não faz nenhuma escrita externa. Esses plugins reutilizam o ciclo de vida MCP existente e não exigem um serviço de plugins separado. Veja no contrato de integração acima os campos obrigatórios, os escopos e os limites de cada recurso.

Os ícones de marca dos plugins vêm empacotados localmente. Ao adicionar ou editar um plugin MCP pessoal, o usuário pode enviar uma imagem PNG, JPG ou WebP (de até 2 MB), pré-visualizá-la ou restaurar o ícone padrão. As mudanças só valem depois de Save; os ícones personalizados persistem entre navegadores como um PNG normalizado de 128px no metadado `presentation.icon` da entrada do servidor, que é apenas de exibição. Eles não são enviados ao transporte MCP.

Em Capability Center > Plugins, a adição, a substituição e a exclusão acontecem um servidor MCP por vez, por meio de mutações direcionadas que preservam alterações concorrentes em servidores vizinhos; as exclusões usam uma requisição sem corpo, endereçada por URL. Um comando stdio inválido em um servidor não bloqueia mais a alternância de outro, enquanto habilitar esse servidor inválido continua protegido pela allowlist de comandos e mostra na interface a mensagem de validação do backend.
As atualizações direcionadas aceitam tanto o campo `type` do DeerFlow quanto o campo `transport` da especificação MCP para servidores SSE/HTTP.
As atualizações de MCP e de skills em runtime substituem o `extensions_config.json` de forma atômica, então uma escrita interrompida não deixa a configuração compartilhada truncada ou escrita pela metade.
O reset do cache MCP feito pelo admin avança um marcador de geração durável no diretório de configuração gravável. Cada worker do Gateway que monta esse mesmo diretório aposenta suas próprias ferramentas em cache e sessões em pool antes da próxima consulta; réplicas com sistemas de arquivos independentes não ficam cobertas implicitamente. Se não houver um caminho de configuração disponível, a API reporta um reset local ao processo.
O `extensions_config.json` aceita UTF-8 com ou sem byte-order mark (BOM) inicial, inclusive arquivos salvos por um editor como UTF-8 com BOM.
As dicas de roteamento MCP também podem preferir uma ferramenta MCP específica para requisições correspondentes, sem proibir outras ferramentas. Quando o `tool_search` adia os schemas MCP, os metadados de roteamento correspondentes podem promover automaticamente até `tool_search.auto_promote_top_k` schemas adiados antes da chamada ao modelo.

Usuários do OpenViking podem registrar o endpoint oficial Streamable HTTP em `/mcp` com uma chave de API USER vinculada ao dono. A ferramenta nativa `forget` é exposta por paridade de capacidades; a exclusão é irreversível, então ela só deve ser chamada depois de uma confirmação explícita do usuário. O DeerFlow não impõe essa confirmação. Esse caminho de ferramenta MCP explícito, escolhido pelo modelo, pode rodar ao lado do backend automático de memória do OpenViking, que é separado; ele não substitui a captura nem o recall automáticos de turnos. Veja a [configuração das ferramentas MCP do OpenViking](backend/docs/MCP_SERVER.md#openviking-mcp-tools).

O Gateway consegue adaptar as ferramentas comuns `submit` / `status` / `cancel` de um servidor MCP em tasks duráveis em background. O Agent enxerga apenas a ferramenta de submit configurada e um ID de task local do DeerFlow; os IDs remotos são persistidos antes de a chamada de submit retornar, enquanto status e cancel ficam internos ao runtime. O polling usa leases entre workers, backoff exponencial nas novas tentativas, sessões MCP com escopo, armazenamento limitado de resultados e recuperação após reinício. Um `isError` da ferramenta de status é mantido como diagnóstico limitado e tentado de novo; os servidores reportam um desfecho permanente da task remota por meio de um resultado estruturado normal com `status: "failed"`. As dicas remotas de polling são números positivos finitos limitados a 24 horas, o JSON de referência de artifact é limitado a 64 KiB, e os identificadores de task/servidor são validados contra os limites das colunas SQL duráveis antes da persistência. Atualizações de input necessário e terminais acordam o chat atual por meio de runs idempotentes do Agent, enquanto `list_background_tasks` e `cancel_background_task` permitem que o Agent gerencie as tasks sem pedir handles remotos ao usuário. As tasks da thread atual ficam disponíveis em `GET /api/threads/{thread_id}/mcp-tasks`, no endpoint de detalhe e em `POST /api/threads/{thread_id}/mcp-tasks/{task_id}/cancel`; quando o runtime de tasks realmente inicia, a Web UI expõe a mesma visão local segura a partir do cabeçalho do chat, com atualização de status ao vivo, cancelamento e detalhes sob demanda de resultado, artifact, pedido de input, erro de status e nova tentativa de cancelamento. Implantações em que o recurso está desativado por padrão ou que usam o backend de memória escondem essa interface e não fazem polling dos endpoints de task. Um cancelamento remoto que falhou continua na fila com backoff, e o erro limitado mais recente e a contagem de tentativas ficam visíveis no card expandido da task. Habilite `mcp_tasks` no `config.yaml`, configure `task_toolsets` com os nomes brutos exatos das ferramentas no `extensions_config.json` e use um backend de banco SQL (`sqlite` ou `postgres`). Mudanças de conexão, autenticação, interceptor, timeout ou binding em servidores com tasks habilitadas exigem reiniciar o Gateway, para que a descoberta de ferramentas do Agent e as chamadas em background não usem versões diferentes da configuração. Por enquanto, `input_required` serve só para notificação: o DeerFlow consegue exibir o pedido, mas ainda não consegue enviar a resposta do usuário de volta para a task remota.

O disparo de notificações e as entregas de runs do Agent que falharam usam backoff exponencial com teto e contagem de tentativas visível, e param depois de cinco tentativas malsucedidas. Quando uma liberação comum com limite ultrapassa o prazo de drenagem, o serviço mantém a posse até ela se resolver. Um destino rejeitado de forma permanente, como um chat excluído, vai imediatamente para dead-letter em vez de ser tentado para sempre ou recriado. Os endpoints de cancelamento retornam depois de registrar o pedido de forma durável; o serviço em background é dono da chamada MCP remota, que pode ser lenta, e do cronograma de novas tentativas.

Os runs de notificação mantêm a instrução de entrega confiável separada do payload de evento remoto, que é não confiável e vem emoldurado. É o runtime de tasks iniciado com o processo, e não uma leitura a quente da configuração, que controla se as ferramentas de gerenciamento de tasks ficam expostas, então mudar `mcp_tasks` exige reiniciar o Gateway. Quando a política `allowed-tools` de uma skill está ativa, `list_background_tasks` e `cancel_background_task` precisam ser declaradas explicitamente, como as outras ferramentas de negócio.
Veja o [Guia do servidor MCP](backend/docs/MCP_SERVER.md) para instruções detalhadas.

Segurança: passe credenciais MCP por requisição apenas por `config.context.secrets`; as credenciais nunca devem ser colocadas em nenhuma das superfícies de metadados do run (`metadata.auth_token` ou `config.metadata.auth_token`). Veja em [MCP credential migration and cleanup](backend/docs/MCP_SERVER.md#migrating-legacy-mcp-credentials) o fluxo de interceptor suportado e a rotação e limpeza de cópias retidas exigidas ao migrar de credenciais legadas em metadados.

#### Canais de IM

O DeerFlow aceita receber tarefas de aplicativos de mensagem. Os canais iniciam sozinhos quando configurados, e nenhum deles exige IP público.

O DeerFlow também pode expor, na interface do workspace, conexões de canais de IM que pertencem ao usuário. Com `channel_connections` habilitado, usuários logados podem vincular Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, WeCom, QQ ou Buzz pela barra lateral / Settings > Channels. Isso reutiliza os transportes de saída `channels.*` existentes, então não é preciso IP público nem URL de callback do provedor. As mensagens de IM recebidas passam a rodar sob a conta de usuário do DeerFlow conectada. Veja [IM Channel Connections](backend/docs/IM_CHANNEL_CONNECTIONS.md) para a configuração e as notas de segurança.

| Canal | Transporte | Dificuldade |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Fácil |
| Slack | Socket Mode | Moderada |
| Feishu / Lark | WebSocket | Moderada |
| WeChat | Tencent iLink (long-polling) | Moderada |
| WeCom | WebSocket | Moderada |
| QQ | WebSocket (C2C somente texto e @menções em grupo; quatro/cinco respostas passivas por origem) | Moderada |
| DingTalk | Stream Push (WebSocket) | Moderada |
| Buzz | Nostr relay (WebSocket, NIP-42) | Moderada |

**Configuração no `config.yaml`:**

```yaml
channels:
  # LangGraph-compatible Gateway API base URL (default: http://localhost:8001/api)
  langgraph_url: http://localhost:8001/api
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

  # Maximum queued or provider-reserved inbound messages (default: 1000)
  inbound_queue_maxsize: 1000
  # Fixed number of long-lived inbound handler workers (default: 5)
  max_concurrency: 5
  # Seconds to drain accepted work before cancelling active handlers (default: 3)
  shutdown_grace_period_seconds: 3

  # Optional: global session defaults for all mobile channels
  session:
    assistant_id: lead_agent  # or a custom agent name; custom agents are routed via lead_agent + agent_name
    config:
      recursion_limit: 100
    context:
      thinking_enabled: true
      is_plan_mode: false
      subagent_enabled: false

  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    # domain: https://open.feishu.cn       # China (default)
    # domain: https://open.larksuite.com   # International

  qq:
    enabled: true
    app_id: $QQ_APP_ID
    client_secret: $QQ_CLIENT_SECRET
    allowed_users: []  # QQ OpenIDs, not QQ account numbers

  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
    # Optional: extra host suffixes inbound media downloads may come from, in
    # addition to the built-in qq.com family and WeCom's official COS media
    # host (ww-aibot-img-1258476243.<region>.myqcloud.com); add one here if
    # WeCom rotates to a new COS account or media goes through a proxy
    allowed_media_hosts: []

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    # Optional: render final Markdown replies as Telegram Rich Messages.
    rich_messages: false
    allowed_users: []               # numeric user IDs, not @usernames; empty = allow all

  wechat:
    enabled: false
    bot_token: $WECHAT_BOT_TOKEN
    ilink_bot_id: $WECHAT_ILINK_BOT_ID
    qrcode_login_enabled: true      # optional: allow first-time QR bootstrap when bot_token is absent
    allowed_users: []               # empty = allow all
    polling_timeout: 35             # timing values must be positive finite seconds
    polling_retry_delay: 5
    qrcode_poll_interval: 2
    qrcode_poll_timeout: 180
    state_dir: ./.deer-flow/wechat/state
    max_inbound_image_bytes: 20971520
    max_outbound_image_bytes: 20971520
    max_inbound_file_bytes: 52428800
    max_outbound_file_bytes: 52428800
    # Inbound media downloads stream with the caps above and are restricted to
    # these host suffixes (plus *.qq.com and the cdn_base_url host by default)
    allowed_media_hosts: []

    # Optional: per-channel / per-user session settings
    session:
      assistant_id: mobile-agent  # custom agent names are also supported here
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip-agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true

  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID             # Client ID of your DingTalk application
    client_secret: $DINGTALK_CLIENT_SECRET     # Client Secret of your DingTalk application
    allowed_users: []                          # empty = allow all
    card_template_id: ""                       # Optional: AI Card template ID for streaming typewriter effect
```

Notas:
- `assistant_id: lead_agent` chama diretamente o assistant padrão do LangGraph.
- Se `assistant_id` for definido com o nome de um agente personalizado, o DeerFlow continua roteando por `lead_agent` e injeta esse valor como `agent_name`, de modo que o SOUL/config do agente personalizado passa a valer nos canais de IM.
- Os workers dos canais de IM chamam internamente a API compatível com LangGraph do Gateway e anexam automaticamente a autenticação interna local ao processo e o par cookie/cabeçalho de CSRF exigido para criar threads e runs.
- O trabalho de entrada é limitado a `inbound_queue_maxsize` mensagens pendentes mais `max_concurrency` workers ativos. Quando a capacidade se esgota, os provedores de socket/polling descartam novas mensagens antes de enviar a confirmação de "trabalhando" do DeerFlow e emitem um aviso com limite de frequência. O Buzz deixa o cursor de replay como está e reconecta para o replay do relay; os webhooks do GitHub retornam `503`, marcando a entrega como falha para reenvio manual ou via API. O shutdown fecha a admissão imediatamente, mantém os transportes dos canais disponíveis enquanto as mensagens aceitas são drenadas por até `shutdown_grace_period_seconds`, depois cancela e aguarda os handlers ativos antes de fechar os recursos do provedor; o timeout externo do Gateway pode cancelar um shutdown incompleto sem desanexar esses recursos.
- O Feishu/Lark agora enfileira mensagens de acompanhamento rápidas por `thread_id` mapeado do DeerFlow, em vez de mostrar na hora a resposta genérica de ocupado, e as respostas em tópico mantêm um card por mensagem com uma pré-visualização compacta da mensagem de origem ao longo dos patches de enfileirado/em execução/final.

Defina as chaves de API correspondentes no seu arquivo `.env`:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret

# WeChat iLink
WECHAT_BOT_TOKEN=your_ilink_bot_token
WECHAT_ILINK_BOT_ID=your_ilink_bot_id

# WeCom
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret

# DingTalk
DINGTALK_CLIENT_ID=your_client_id
DINGTALK_CLIENT_SECRET=your_client_secret
```

**Configuração do Telegram**

1. Converse com o [@BotFather](https://t.me/BotFather), envie `/newbot` e copie o token da HTTP API.
2. Defina `TELEGRAM_BOT_TOKEN` no `.env` e habilite o canal no `config.yaml`.
3. O bot aceita texto, fotos e documentos recebidos (com ou sem legenda). Os downloads pela Bot API hospedada são limitados a 20 MB por anexo.

**Configuração do Slack**

1. Crie um Slack App em [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.
2. Em **OAuth & Permissions**, adicione os Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Habilite o **Socket Mode** → gere um App-Level Token (`xapp-…`) com o scope `connections:write`.
4. Em **Event Subscriptions**, assine os eventos de bot: `app_mention`, `message.im`.
5. Defina `SLACK_BOT_TOKEN` e `SLACK_APP_TOKEN` no `.env` e habilite o canal no `config.yaml`.

**Configuração do Feishu / Lark**

1. Crie um app na [Feishu Open Platform](https://open.feishu.cn/) → habilite a capacidade **Bot**.
2. Adicione as permissões: `im:message`, `im:message.p2p_msg:readonly`, `im:resource`.
3. Em **Events**, assine `im.message.receive_v1` e selecione o modo **Long Connection**.
4. Copie o App ID e o App Secret. Defina `FEISHU_APP_ID` e `FEISHU_APP_SECRET` no `.env` e habilite o canal no `config.yaml`.
5. O bot suporta mensagens recebidas de texto, imagem e arquivo. Os downloads de anexos recebidos são limitados a 20 MB por anexo.

**Configuração do WeChat**

1. Habilite o canal `wechat` no `config.yaml`.
2. Defina `WECHAT_BOT_TOKEN` no `.env`, ou então `qrcode_login_enabled: true` para o bootstrap por QR code no primeiro uso.
3. Quando `bot_token` está ausente e o bootstrap por QR está habilitado, acompanhe nos logs do backend o conteúdo do QR retornado pelo iLink e conclua o fluxo de vinculação.
4. Depois que o fluxo de QR dá certo, o DeerFlow persiste o token obtido em `state_dir` para os reinícios seguintes.
5. Em implantações com Docker Compose, mantenha o `state_dir` em um volume persistente para que o cursor `get_updates_buf` e o estado de autenticação salvo sobrevivam aos reinícios.

**Configuração do WeCom**

1. Crie um bot na plataforma WeCom AI Bot e obtenha o `bot_id` e o `bot_secret`.
2. Habilite `channels.wecom` no `config.yaml` e preencha `bot_id` / `bot_secret`.
3. Defina `WECOM_BOT_ID` e `WECOM_BOT_SECRET` no `.env`.
4. Confira se as dependências do backend incluem `wecom-aibot-python-sdk`. O canal usa uma conexão longa por WebSocket e não exige URL pública de callback.
5. A integração atual suporta mensagens recebidas de texto, imagem e arquivo. Imagens e arquivos finais gerados pelo agente também são enviados de volta para a conversa do WeCom.

**Configuração do DingTalk**

1. Crie uma aplicação DingTalk no [DingTalk Developer Console](https://open.dingtalk.com/) e habilite a capacidade **Robot**.
2. Na página de configuração do robô, defina o modo de recebimento de mensagens como **Stream Mode**.
3. Copie o `Client ID` e o `Client Secret`, defina `DINGTALK_CLIENT_ID` e `DINGTALK_CLIENT_SECRET` no `.env` e habilite o canal no `config.yaml`.
4. *(Opcional)* Para habilitar respostas em AI Card com streaming (efeito de máquina de escrever), crie um template de **AI Card** na [DingTalk Card Platform](https://open.dingtalk.com/document/dingstart/typewriter-effect-streaming-ai-card) e defina `card_template_id` no `config.yaml` com o ID do template. Você também precisa solicitar as permissões `Card.Streaming.Write` e `Card.Instance.Write`.


Quando o DeerFlow roda no Docker Compose, os canais de IM executam dentro do container `gateway`. Nesse caso, não aponte `channels.langgraph_url` nem `channels.gateway_url` para `localhost`; use nomes de serviço de container, como `http://gateway:8001/api` e `http://gateway:8001`, ou defina `DEER_FLOW_CHANNELS_LANGGRAPH_URL` e `DEER_FLOW_CHANNELS_GATEWAY_URL`.

**Comandos**

Com um canal conectado, você pode interagir com o DeerFlow direto pelo chat:

| Comando | Descrição |
|---------|-------------|
| `/new` | Inicia uma nova conversa |
| `/status` | Mostra informações da thread atual |
| `/models` | Lista os modelos disponíveis |
| `/memory` | Mostra a memória |
| `/agent list` | Lista seus Custom Agents |
| `/agent use <name>` | Inicia uma nova conversa com um Custom Agent |
| `/help` | Mostra a ajuda |

> Mensagens sem prefixo de comando são tratadas como chat normal: o DeerFlow cria uma thread e responde em forma de conversa.

A seleção de agente tem escopo de conversa: `/agent use <name>` inicia uma conversa nova e fixa esse Custom Agent nos metadados da thread. Conversas existentes nunca trocam de agente no meio do caminho, a seleção sobrevive a um reinício do Gateway, e abrir na Web UI a thread criada pelo IM continua com o mesmo Custom Agent.
Use `/agent use lead_agent` para voltar ao agente padrão em uma nova conversa.

#### Correlação de trace de requisições

Toda resposta HTTP do Gateway traz um cabeçalho `X-Trace-Id`. O id é herdado de um `X-Trace-Id` recebido, quando quem chama envia um, e gerado caso contrário, de modo que um proxy ou serviço upstream consegue fixar um mesmo id entre serviços. Não precisa de configuração e não pode ser desligado.

O mesmo id continua ligado ao trabalho que dura mais que a resposta HTTP: a task de run desacoplada, os subagents para os quais ela delega e as threads de atualização de memória em background. Ele é registrado como `deerflow_trace_id` no registro do run (visível na API de runs), nos metadados de checkpoint da thread e nos traces do Langfuse. Tarefas agendadas, runs de notificação de tasks MCP e mensagens de canais de IM começam fora do HTTP e geram o próprio id a cada ocorrência.

Os registros de log só trazem esse id quando o logging aprimorado está ligado:

```yaml
logging:
  enhance:
    enabled: true   # print trace_id into log records
    format: text    # or json
```

Isso vem desligado por padrão porque ligar muda o formato do log. O `logging` exige reinício, então edite o `config.yaml` e reinicie o Gateway. A configuração afeta apenas a saída de log; o id, o cabeçalho de resposta e os metadados do run não mudam.

O `deerflow_trace_id` é um id de correlação do DeerFlow: não é um id de run e não é o id de trace nativo de um provedor. Também não é uma chave de busca, nada resolve uma thread ou um run a partir dele; use-o para correlacionar linhas de log. Um `deerflow_trace_id` enviado no `metadata` ou no `config.context` de uma requisição de run é ignorado e sobrescrito, de modo que o cabeçalho de resposta, os logs e o run persistido nunca divergem. Para fixar um id de correlação, envie o cabeçalho `X-Trace-Id`.

O histórico de runs do Gateway também registra um recibo terminal `run.delivery` por run, incluindo runs sem saída e runs recuperados de crash. Na execução normal, o recibo é persistido antes do status terminal durável do run. A recuperação de órfãos primeiro faz o claim atômico de um lease expirado e depois preenche o recibo de forma idempotente, para que uma varredura de recuperação defasada não sobrescreva os dados detalhados de entrega de um run ativo. A persistência do recibo continua sendo best-effort durante uma indisponibilidade do event store. Runs que falham no preflight de checkpoint (ou são cancelados enquanto aguardam uma finalização anterior) mantêm o comportamento atual dos dados de conclusão: recebem o recibo de entrega zero, mas não sobrescrevem os campos de conclusão do RunStore com um snapshot vazio.

Quando `tool_progress.enabled` é true, o mesmo histórico de eventos de run também registra as mudanças de fase do guard de qualidade de resultado. Ele registra decisões de detecção de loop e promoções de ferramentas MCP adiadas, tanto para o lead agent quanto para os subagents comuns de task. Os eventos de promoção identificam os nomes das ferramentas adiadas recém-promovidas e se foram os metadados de roteamento ou o `tool_search` que as selecionaram, sem copiar para o próprio evento a consulta de busca, as palavras-chave de roteamento, os schemas, os argumentos, os resultados ou o hash do catálogo.

#### Tracing com LangSmith

O DeerFlow tem integração nativa com o [LangSmith](https://smith.langchain.com) para observabilidade. Quando habilitada, todas as chamadas de LLM, os runs de agente e as execuções de ferramentas são rastreados e ficam visíveis no dashboard do LangSmith.

Adicione o seguinte ao seu arquivo `.env`:

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

#### Tracing com Langfuse

O DeerFlow também suporta observabilidade com o [Langfuse](https://langfuse.com) para runs compatíveis com LangChain.

Adicione o seguinte ao seu arquivo `.env`:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Se você usa uma instância self-hosted do Langfuse, defina `LANGFUSE_BASE_URL` com a URL da sua implantação.

**Campos de correlação de trace.** Todo run de agente é anotado com os atributos de trace reservados do Langfuse, então as páginas Sessions e Users são preenchidas automaticamente:

- `session_id` = `thread_id` do LangGraph, que agrupa todos os traces da mesma conversa
- `user_id` = usuário efetivo de `get_effective_user_id()` (cai para `default` no modo sem autenticação)
- `trace_name` = id do assistant (por padrão `lead-agent`)
- `tags` = `[env:<DEER_FLOW_ENV>, model:<model_name>]` (os runs nativos do lead-agent no Gateway e do cliente embutido marcam o modelo selecionado depois da resolução de padrão ou de fallback; graph factories personalizadas podem informar apenas o modelo solicitado; a tag de ambiente é omitida quando não definida)
- `metadata.deerflow_trace_id` = id de correlação de requisição do DeerFlow, igual ao `X-Trace-Id` quando a correlação de trace de requisições está habilitada

Eles são injetados em `RunnableConfig.metadata` na raiz da invocação do grafo, tanto no caminho do gateway (`runtime/runs/worker.py::run_agent`) quanto no caminho embutido (`client.py::DeerFlowClient.stream`), então qualquer callback compatível com LangChain consegue lê-los. Defina `DEER_FLOW_ENV` (ou `ENVIRONMENT`) para marcar os traces por ambiente de implantação.

#### Tracing com Monocle

O DeerFlow também suporta o [Monocle](https://github.com/monocle2ai/monocle), um tracer baseado em OpenTelemetry para aplicações agênticas. Ele registra cada run de ponta a ponta: chamadas de LLM, passos do agente e invocações de ferramentas e de MCP, com entradas, saídas, tempos e contagens de tokens.

Adicione o seguinte ao seu arquivo `.env`:

```bash
MONOCLE_TRACING=true
MONOCLE_EXPORTERS=file          # file, console, okahu, s3, blob, gcs (default: file)
OKAHU_API_KEY=okh_xxxxxxxx      # required only for the `okahu` exporter
```

Cada run grava um arquivo de trace em `.monocle/`; abra-o na [extensão Monocle para VS Code](https://marketplace.visualstudio.com/items?itemName=OkahuAI.monocle-apptrace) para inspecionar a linha do tempo de spans e as contagens de tokens. Conecte ao [Okahu](https://www.okahu.ai), uma plataforma de observabilidade de agentes, para analisar traces entre runs e rodar avaliações agênticas e baseadas em traces (via exporter `okahu`).

Os traces capturam as entradas e saídas dos spans literalmente (prompts, argumentos de ferramentas e respostas do modelo), além do uso de tokens e dos tempos. O exporter `file` os mantém no disco local e nunca faz rotação nem limpeza, então limpe `.monocle/` de tempos em tempos; os exporters remotos (`okahu`, `s3`, `blob`, `gcs`) enviam esses mesmos dados para fora da máquina, então habilite apenas destinos em que você confia. O Monocle é inicializado uma única vez na subida do Gateway: um erro de configuração (exporter desconhecido, `OKAHU_API_KEY` ausente) é registrado em log nesse momento, e o tracing fica desligado até o Gateway reiniciar.

#### Usando vários provedores

LangSmith e Langfuse se conectam como callbacks do LangChain, então você pode habilitar os dois e o DeerFlow reporta cada run a ambos. Se um provedor habilitado estiver sem as credenciais obrigatórias ou falhar na inicialização, o DeerFlow falha logo de início e diz qual é. O Monocle usa um provider global do OpenTelemetry em vez de um callback; o Langfuse compartilha esse provider, então os três podem rodar juntos. Como os dois span processors ficam no mesmo provider compartilhado, os exporters do Monocle também enxergam os spans do Langfuse quando ambos estão habilitados.

Em implantações Docker, o tracing vem desabilitado por padrão. Defina `LANGSMITH_TRACING=true` e `LANGSMITH_API_KEY` no seu `.env` para habilitar.

#### Ações de stream em runs existentes

Entrar via SSE em um run existente é só observação no `GET`: enviar `action=interrupt|rollback` retorna `405`. O cancelamento nessa rota de stream é exclusivo de `POST` e exige a permissão `runs:cancel`. Por isso o contrato OpenAPI expõe `action` e `wait` apenas no `POST`; a operação `GET` expõe só os parâmetros de caminho.

#### Tokens de acesso pessoal

Clientes não interativos (pipelines de CI, scripts, integrações servidor a servidor) podem chamar a API do Gateway com um **personal access token (PAT)** em vez de uma sessão de navegador. Crie um, estando logado, via `POST /api/v1/auth/pats` (o valor bruto `dfp_...` é mostrado uma única vez; só o digest SHA-256 é armazenado) e envie-o como credencial Bearer:

```http
POST /api/threads/search
Authorization: Bearer dfp_...
Content-Type: application/json

{}
```

Cada token roda com a identidade do usuário dono (o filtro por dono e a memória por usuário continuam funcionando), carrega um conjunto de scopes que só pode restringir as permissões desse usuário e é admitido apenas nas rotas do ciclo de vida de threads/runs. Qualquer outra rota responde `403` a chamadas com PAT, e um PAT nunca carrega capacidade de admin. Os tokens podem ser listados e revogados a qualquer momento; a revogação é imediata. PATs exigem um backend de banco de dados (SQLite/PostgreSQL). Referência completa: [API Reference: Personal Access Tokens](backend/docs/API.md#personal-access-tokens).

## De Deep Research a super agent harness

O DeerFlow começou como um framework de Deep Research, e a comunidade foi além. Desde o lançamento, os desenvolvedores o levaram para muito longe da pesquisa: montaram pipelines de dados, geraram apresentações, subiram dashboards, automatizaram fluxos de conteúdo. Coisas que a gente nunca tinha previsto.

Isso nos mostrou uma coisa importante: o DeerFlow não era só uma ferramenta de pesquisa. Era um **harness**, um runtime que dá aos agentes a infraestrutura para fazer o trabalho de fato.

Então reconstruímos tudo do zero.

O DeerFlow 2.0 deixou de ser um framework que você monta peça por peça. É um super agent harness que já vem completo e pode ser estendido por inteiro. Construído sobre LangGraph e LangChain, ele traz de fábrica tudo de que um agente precisa: um sistema de arquivos, memória, skills, execução ciente de sandbox e a capacidade de planejar e criar sub-agents para tarefas complexas, de vários passos.

Use como está. Ou desmonte e faça do seu jeito.

## Principais recursos

### Skills e ferramentas

Abra o **Capability Center** pela barra lateral do workspace para gerenciar **Plugins** (servidores MCP e a integração com Lark/Feishu) e **Skills**. Os dois catálogos têm busca; os cards de skill mostram descrições curtas, com a descrição completa em uma visão de detalhe. As skills nativas e as criadas/importadas pelo usuário são listadas separadamente. A aba Community permite importar arquivos `.skill` para My skills. As preferências gerais continuam em Settings.

São as skills que fazem o DeerFlow dar conta de *quase qualquer coisa*.

Uma Agent Skill padrão é um módulo de capacidade estruturado: um arquivo Markdown que define um fluxo de trabalho, boas práticas e referências a recursos de apoio. O DeerFlow já vem com skills nativas para pesquisa, geração de relatórios, criação de slides, páginas web, geração de imagem e vídeo, entre outras. Mas o forte mesmo é a extensibilidade: adicione suas próprias skills, substitua as nativas ou combine várias em fluxos compostos.

As skills são carregadas de forma progressiva, só quando a tarefa precisa delas, e não todas de uma vez. Isso mantém a janela de contexto enxuta e faz o DeerFlow funcionar bem mesmo com modelos sensíveis a tokens.

Quando a descoberta adiada de skills está habilitada, o `describe_skill` ranqueia as skills instaladas pela cobertura limitada, com normalização Unicode, dos termos de intenção nos nomes e nas descrições. Assim, pedidos naturais com vários termos encontram uma skill relevante sem exigir uma frase exata, enquanto as buscas exatas com `select:` e as de nome obrigatório com `+prefix` continuam disponíveis. As buscas ranqueadas usam até 256 caracteres e retornam até cinco resultados; listas exatas com `select:` não são truncadas e retornam todas as correspondências pedidas no catálogo.

Um diretório de skill é uma fronteira de pacote: depois que o DeerFlow encontra o `SKILL.md` dele, arquivos `SKILL.md` aninhados dentro desse pacote (por exemplo, fixtures de avaliação) continuam sendo dados de apoio e não são registrados como skills de runtime. Isso vale para os pacotes de integração gerenciados e também para as skills públicas e personalizadas. Diretórios de namespace sem um `SKILL.md` próprio ainda podem agrupar skills aninhadas.

A descoberta segue symlinks de diretório gerenciados pelo operador, mas pula links que voltam para um diretório ancestral, para que um namespace cíclico não revarra a mesma árvore repetidas vezes. Links independentes para a mesma árvore externa de skills continuam suportados.

O Markdown das skills e os recursos de texto empacotados usam UTF-8. A CLI do skill-creator e os utilitários de revisão leem e escrevem texto explicitamente como UTF-8, para que skills localizadas se comportem igual em todos os sistemas operacionais.

O usuário pode ativar explicitamente uma skill habilitada por um único turno começando o pedido com `/skill-name`, por exemplo `/data-analysis analyze uploads/foo.csv`. O DeerFlow carrega o `SKILL.md` dessa skill como contexto oculto do turno atual e mantém o prompt base limitado aos metadados das skills. A ativação por barra respeita skills desabilitadas, as whitelists de skills de agentes personalizados e os comandos de canal existentes, como `/new` e `/help`.

Depois que uma resposta carrega skills, a barra de ferramentas dela passa a incluir **Skills used**. Passe o mouse ou clique no ícone para ver as skills e suas origens; passar o mouse sobre o nome de uma skill o sublinha. Selecione uma skill para inspecionar o `SKILL.md` no painel lateral redimensionável (uma gaveta no celular). A visão usa snapshots capturados durante carregamentos bem-sucedidos pela ferramenta de leitura configurada ou durante a ativação explícita por barra, então edições posteriores ou a remoção de uma skill não reescrevem esse histórico. Carregamentos repetidos aparecem uma vez por run, na ordem do primeiro carregamento. Leituras por intervalo e snapshots limitados são rotulados como parciais; conversas antigas sem evidência capturada não mostram esse menu. Copiar devolve o Markdown capturado, incluindo o frontmatter YAML. Links e imagens relativos ao pacote continuam como referências legíveis, em vez de navegar para fora da conversa. Carregamentos de skill feitos por outras ferramentas, como comandos de shell, não são inferidos a partir do texto da resposta.

A política `allowed-tools` de uma skill habilitada só se aplica depois que essa skill é ativada explicitamente por barra ou capturada no contexto de skills ativas do agente após um carregamento via `read_file`. Apenas habilitar, anunciar ou listar uma skill na allowlist `skills` de um agente personalizado ou subagent não reduz o conjunto normal de ferramentas desse agente; os subagents usam a mesma política de descoberta e ativação progressivas do lead agent. Durante um run ativado por barra, a política dessa skill explícita é a que manda: ler outro `SKILL.md` pode fornecer instruções, mas não amplia as ferramentas da skill da barra. Sem ativação por barra, as políticas das skills realmente carregadas no contexto ativo mantêm a semântica de união. Uma vez ativa, a política filtra tanto os schemas de ferramentas visíveis ao modelo quanto a execução de ferramentas. As ferramentas de descoberta do framework (`tool_search` e `describe_skill`) continuam disponíveis para que uma ferramenta adiada permitida ou uma skill instalada ainda possam ser descobertas, mas descoberta e promoção nunca concedem permissão para executar uma ferramenta de negócio que não esteja em `allowed-tools`. `task` não é isenta pelo framework; uma skill restritiva precisa listá-la explicitamente para delegar a um subagent. As decisões de política por passo são contexto interno do runtime e são removidas das cópias de contexto observáveis ou persistidas. Falhas do registro e um conjunto ativo sem nenhuma skill válida restante fecham em modo seguro, restrito às ferramentas seguras do framework; caminhos obsoletos individuais só são ignorados quando resta outra skill ativa válida. Trata-se de um escopo comportamental best-effort, não de uma fronteira de segurança rígida: carregar instruções de skill por outra ferramenta não é capturado, e entradas de skills ativas podem ser removidas de um contexto limitado.

Ao instalar arquivos `.skill` pelo Gateway, o DeerFlow aceita o `allowed-tools` padrão separado por espaços, metadados opcionais de frontmatter e o campo `argument-hint` compatível com o Claude, em vez de rejeitar skills externas que de resto são válidas. Listas YAML continuam suportadas em `allowed-tools` e preservam os nomes exatos de runtime. Grafias portáteis exatas como `WebFetch`, `WebSearch`, `Glob`, `Grep` e `Read` são mapeadas para as ferramentas `web_fetch`, `web_search`, `glob`, `grep` e `read_file` do DeerFlow; nomes escalares em minúsculas ou desconhecidos ficam como estão, para que ferramentas personalizadas e MCP mantenham a grafia exata de runtime. Entradas entre parênteses como `Bash(tvly *)` são tokenizadas como uma única entrada literal, incluindo espaços, texto entre aspas e parênteses escapados, mas ficam inativas porque o DeerFlow não inspeciona argumentos de ferramentas; declare `bash` apenas quando a skill puder usar a ferramenta Bash completa.

Desabilitar uma skill também a remove da visão de sistema de arquivos do sandbox, de modo que comandos de shell e ferramentas estruturadas de arquivo seguem o mesmo estado de habilitação. Os sandboxes Local, Docker/AIO, provisioner com hostPath e os E2B recém-criados montam `/mnt/skills` a partir de projeções que contêm só as skills habilitadas, atualizadas quando skills públicas, personalizadas, legadas ou de integração gerenciada são alternadas, editadas, criadas, excluídas ou instaladas. As chamadas estruturadas de `read_file` (incluindo intervalos de linhas e verificações de leitura antes da escrita) usam o mapeamento de mounts do provedor de sandbox, então a identidade de usuário capturada na aquisição do sandbox continua sendo a que vale. Os pacotes de integração gerenciados continuam compartilhados, enquanto a visibilidade projetada deles no sistema de arquivos segue o estado de habilitação de cada usuário. Gateways com vários workers releem o estado de habilitação em disco ao reconstruir as projeções do usuário, então um toggle tratado por um worker é respeitado na próxima aquisição de sandbox por outro worker. Sandboxes E2B existentes mantêm o snapshot do momento da criação até serem recriados. As skills de provisioner baseadas em PVC mantêm por enquanto o snapshot/layout de PVC configurado; a materialização dinâmica de PVC é acompanhada à parte.

```
# Paths inside the sandbox container
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← yours

/mnt/skills/integrations
└── lark-cli/lark-doc/SKILL.md      ← managed, read-only
```

A skill nativa `image-generation` suporta as APIs de imagens do Gemini, da MiniMax e as compatíveis com OpenAI. Selecione esta última com `IMAGE_GENERATION_PROVIDER=openai` e configure `IMAGE_GENERATION_API_KEY`, `IMAGE_GENERATION_BASE_URL` e `IMAGE_GENERATION_MODEL`. Em um sandbox em container, exponha essas variáveis por `sandbox.environment`; os comandos do sandbox propositalmente não herdam chaves de API do processo do Gateway.

No `LocalSandboxProvider`, isso é uma fronteira gerenciada de caminhos de ferramenta, e não um isolamento do sistema de arquivos do host. Políticas explícitas de skill por Agent só são aceitas enquanto o bash do host está desabilitado (o padrão), porque um subprocesso do host consegue endereçar caminhos canônicos sem usar os mapeamentos de caminhos virtuais do provedor. Use Docker/AIO, o provisioner do Kubernetes ou o E2B quando a fronteira de sistema de arquivos precisar continuar valendo junto com acesso ao shell.

As integrações gerenciadas instalam pacotes de skills compartilhados e somente leitura, sem misturá-los às skills personalizadas. A integração com a CLI do Lark/Feishu fica em `Capability Center → Plugins → Lark / Feishu`; um administrador instala ou atualiza uma vez o pacote oficial `lark-*` em `{DEER_FLOW_HOME}/integrations/skills/lark-cli`, e todos os usuários descobrem esse mesmo pacote, cada um com seu próprio estado de habilitação. A configuração do app e os dados de OAuth de cada usuário ficam isolados em `{DEER_FLOW_HOME}/users/{user_id}/integrations/lark-cli/{config,data}`. Esses diretórios de segredos são restritos a `0700`, os arquivos comuns de credenciais a `0600`, e symlinks são rejeitados.

Depois da instalação, o usuário pode clicar em **Connect Lark** para abrir um link de autorização no navegador; não é preciso autorizar pelo terminal. A mesma interface permite pedir domínios de permissão adicionais, como Calendar, Docs ou Drive, ou um scope OAuth específico reportado pelo `lark-cli`. Uma atualização barata de status só inspeciona a árvore local de credenciais, então a interface mostra **Credentials configured (not live-verified)** até que uma conclusão explícita pelo navegador faça a verificação do token ao vivo. Depois disso a ação continua como **Reconnect Lark**, para que o usuário possa substituir ou ampliar a autorização. Se um agente esbarra em falta de autorização do Lark durante uma conversa, a orientação gerenciada `lark-shared` leva o usuário de volta à mesma configuração do plugin, com `/workspace/capabilities?tab=plugins&plugin=lark`.

Uma vez configurado, **Change Lark app** permite que o usuário aponte sua conta DeerFlow para outro app Lark/Feishu sem reinstalar, seja colando o App ID / App Secret de um app existente, seja registrando um app de novo pelo navegador. A troca é por usuário (nunca toca nas credenciais de outro usuário), valida as novas credenciais com o probe de tenant-token ao vivo da CLI oficial antes de substituir o app ativo, e revoga/remove os tokens OAuth do app anterior. Uma mudança de credencial rejeitada não se sobrepõe a um fluxo de configuração ou de autorização em andamento. Os dados de OAuth anteriores são limpos antes de a CLI armazenar o app substituto, de modo que o novo segredo de keychain baseado em arquivo continua disponível durante a reconexão. Em seguida o DeerFlow abre imediatamente a autorização no navegador para o app recém-vinculado, para que a troca termine em uma conexão utilizável.

A instalação do pacote de skills do Lark resolve a release oficial mais recente de `larksuite/cli` no GitHub e baixa as skills dessa versão no momento da instalação, então o Gateway precisa de acesso de saída à internet nessa etapa (se a consulta à release falhar, ele recorre a uma versão mínima fixada). A página de configurações mostra a versão instalada e, quando disponível, a mais nova publicada, para que um admin possa reinstalar e atualizar. Implantações air-gapped podem deixar o arquivo preparado de antemão e apontar `DEER_FLOW_LARK_CLI_SKILLS_ARCHIVE` para o arquivo local. A integridade não depende de um hash fixado dos bytes do arquivo (o GitHub não garante bytes estáveis nos arquivos de código-fonte); em vez disso, o download é restrito ao host oficial do GitHub, cada membro do arquivo passa por verificações de segurança estrutural, e um hash de conteúdo da árvore de skills efetivamente instalada (incluindo a orientação compartilhada injetada pelo DeerFlow) é registrado, para que mudanças de conteúdo sejam auditáveis entre reinstalações.

Quando `sandbox.use` seleciona o provedor AIO, a mesma instalação também baixa os arquivos de release oficiais da CLI para Linux amd64 e arm64, verifica os checksums SHA-256 publicados, extrai com segurança um executável por arquitetura e monta o runtime resultante como somente leitura em `/mnt/integrations/lark-cli/runtime`. Um launcher nesse mount, que escolhe a arquitetura, deixa o `lark-cli` disponível no `PATH` do sandbox. Implantações AIO air-gapped podem preparar de antemão uma árvore de runtime sem symlinks contendo `bin/lark-cli` mais os dois arquivos `linux-{amd64,arm64}/lark-cli`, e definir `DEER_FLOW_LARK_CLI_SANDBOX_RUNTIME_DIR` com esse diretório.

> **Fronteira de confiança do sandbox:** o navegador nunca recebe o app secret do Lark, mas as conversas de agente rodam o `lark-cli` dentro do sandbox, então os diretórios de credenciais por usuário são montados nele: `config` (que guarda o `appSecret` de longa duração) é montado como **somente leitura**, seu subdiretório `config/locks`, de resto vazio, é montado por cima como gravável para os arquivos de coordenação do `lark-cli`, e `data` (tokens OAuth renováveis) é gravável. Os mounts de config e de data, que carregam credenciais, continuam *legíveis* por qualquer processo que o agente rode ali, então um código alcançado por prompt injection em um resultado de ferramenta poderia lê-los. Trate o sandbox como parte da fronteira de confiança das credenciais do Lark até que o trabalho futuro do sidecar credential-broker remova esses mounts da execução no sandbox.

Em implantações remotas/Kubernetes (o backend provisioner), o runtime do `lark-cli` no sandbox pode ser fornecido por um init container opcional que copia os binários para um `emptyDir` compartilhado, sem download do GitHub na instalação e sem mount de runtime por hostPath/PVC. Publique a imagem em [`docker/lark-cli-init`](docker/lark-cli-init/README.md) e defina `LARK_CLI_INIT_IMAGE` no provisioner (com o Helm chart, `provisioner.larkCliInitImage` / `provisioner.larkCliBrokerImage`); quando não definido, fica desligado (comportamento legado). O status da integração com o Lark (`GET /api/integrations/lark/status`) reporta `sandbox_runtime_mode`, `sandbox_runtime_probed` e `sandbox_runtime_ready`. O `sandbox_runtime_probed` indica se a prontidão do runtime foi de fato avaliada; respostas de backends antigos podem omitir a flag e, nesse caso, o cache de mutações de Settings mantém os últimos campos de runtime verificados em vez de sobrescrevê-los com um fallback não avaliado. Assim a interface de Settings mostra se o `lark-cli` vai mesmo estar presente no sandbox na hora do chat, em vez de um status verde que esconde um `command not found` mais adiante.

No modo broker do Lark, as execuções novas de Bash do AIO fecham o stdin herdado por pipe. Comandos de terminal persistente mantêm a entrada; o shim ignora o stdin do terminal. Pipelines explícitos, heredocs e redirecionamentos de arquivo continuam fornecendo entrada normalmente, e o shim só repassa essa entrada depois do EOF. Um timeout de inatividade do stdin aborta sem executar o comando, e os logs de execução do broker omitem os valores dos argumentos. Veja no [guia da imagem do broker](docker/lark-cli-broker/README.md) as configurações de timeout e os requisitos de rebuild da imagem.

Se um operador confiável gerencia o diretório de skills configurado por um mount externo, como MinIO, NFS ou CSI, um administrador pode chamar `POST /api/skills/reload` depois de alterar os arquivos. Isso invalida os caches de prompt de skills do processo atual do Gateway e espera até o timeout limitado de atualização, para que os runs seguintes revarram os arquivos mais recentes; as tasks em execução não mudam. Uma falha de sistema de arquivos no nível do loader retorna um erro genérico de servidor e preserva o último cache de processo carregado com sucesso, em vez de publicar um catálogo vazio. Os workers do Uvicorn e os Pods do Kubernetes precisam ser acionados um a um. Escritas diretas no mount passam por fora da validação, do SkillScan e do histórico aplicados pelas APIs de instalação/edição do DeerFlow, então só sistemas controlados pelo operador devem ter acesso de escrita.

As instalações de skill e as edições de skill gerenciadas por agente passam pelo **SkillScan**, um scanner de segurança nativo e determinístico que roda antes do scanner de skills baseado em LLM. A fase 1 roda offline, sem dependência de Semgrep/OpenGrep, bloqueia achados `CRITICAL` de alta confiança, como chaves privadas ou execução de shell, e passa os achados de aviso ao scanner LLM para revisão contextual. Arquivos de código (qualquer coisa em `scripts/`, um sufixo de script como `.py`, `.sh` ou `.js`, ou um arquivo sem extensão que começa com `#!`) que não sejam texto UTF-8 sem NUL geram um aviso e ainda assim são analisados sobre uma decodificação com perdas, de modo que um único byte perdido não consegue escondê-los das verificações `CRITICAL`. O adaptador de moderação normaliza tanto as respostas de modelo em texto puro quanto os blocos de texto da Responses API do LangChain antes de fazer o parsing da decisão JSON exigida. As verificações de exfiltração por cliente de instância em Python seguem uma cadeia mínima de evidências no mesmo escopo: um nome simples vinculado a um construtor de cliente conhecido, aliases opcionais de nome para nome e um uso real de método de saída ou de context manager suportado por esse construtor. As raízes dos construtores precisam ser imports comprovados; nomes soltos que apenas parecem canônicos não são inferidos como módulos. Escopos aninhados não herdam handles de cliente e herdam apenas aliases de import de construtor que nunca são reatribuídos no escopo externo. Comprehensions, statements com walrus, anotações, alvos de binding complexos, operações não suportadas e fluxos de branch ambíguos não produzem achado por esse sinal; as construções puladas invalidam, de forma conservadora, todo nome que possam vincular, para que um estado de cliente obsoleto não gere um achado. Um orçamento determinístico de trabalho ou um limite de recursão atingido por essa análise best-effort não descarta os achados já coletados para o arquivo. Defina `skill_scan.enabled: false` no `config.yaml` para desabilitar apenas os analisadores determinísticos; a extração segura de arquivos e o scanner LLM continuam rodando.

Em mappings de credenciais em Python, o SkillScan verifica os valores literais e trata as chaves comuns de dicionário como rótulos. Um mapping como `tokens = {"access_token": os.getenv("ACCESS_TOKEN")}` não reporta uma credencial hardcoded. Chaves que correspondem a um formato reconhecido de token de nuvem ou de API continuam sendo verificadas como credenciais embutidas.

O DeerFlow também traz o **skill-reviewer**, uma skill pública para revisão somente leitura da qualidade de skills. Ele usa a ferramenta nativa `review_skill_package` para inspecionar skills instaladas, pacotes locais, arquivos compactados ou conteúdo de `SKILL.md` colado, sem ativar a skill alvo, vincular os segredos dela, executar seus scripts ou instalá-la. A ferramenta devolve ao contexto do modelo um payload JSON compacto, com as tags neutralizadas, e mantém o payload bruto completo da revisão no artifact da ferramenta, para consumidores programáticos. O núcleo determinístico de revisão reutiliza o parsing do DeerFlow e os fatos do SkillScan, emite contratos JSON versionados em `contracts/skill_review/` e pode ser rodado pela CLI do backend:

```bash
cd backend
uv run python -m deerflow.skills.review.cli ../skills/public/data-analysis --format text --fail-on error --fail-on-incomplete
```

Os waivers de CI das skills públicas são exceções exatas e com validade em `.github/skill-review-waivers.v1.json`. Como só o manifest base confiável pode suprimir um achado, um pull request que altera arquivos pode ser pré-autorizado com segurança: primeiro se faz o merge de uma mudança só no manifest, listando em `preapproved_file_sha256s` o SHA-256 futuro, já revisado, do arquivo inteiro; a mudança no arquivo pode então entrar em um pull request posterior.

As ferramentas seguem a mesma filosofia. O DeerFlow vem com um conjunto básico de ferramentas (busca na web, fetch de páginas, captura de páginas renderizadas, operações de arquivo, execução de bash) e suporta ferramentas personalizadas via servidores MCP e funções Python. Os provedores de busca DDG, Brave, Tavily, SearXNG e Serper, que acompanham o projeto, aceitam um `time_range` opcional de `day`, `week`, `month` ou `year`; omiti-lo preserva o comportamento atual da busca. Em buscas por recência no DDG, o DeerFlow exclui os backends do DDGS que ignoram limites de tempo. Troque o que quiser. Adicione o que quiser.

Na busca na web e na busca de imagens do DDG, o `max_results` no `config.yaml` pode ser um inteiro positivo ou uma referência a variável de ambiente, como `max_results: $DDG_MAX_RESULTS` com `DDG_MAX_RESULTS=5`. O valor configurado tem precedência sobre o argumento `max_results` da chamada da ferramenta. Valores inválidos (por exemplo `abc`, uma string vazia ou `3.5`), zero e contagens negativas geram um aviso e voltam ao padrão de 5 resultados.

Servidores MCP stdio podem definir `cwd` no `extensions_config.json` quando o entrypoint ou os arquivos de dados deles dependem de um diretório de trabalho específico. A configuração vale tanto para a descoberta quanto para as chamadas de ferramenta; veja [MCP configuration](backend/docs/MCP_SERVER.md#stdio-working-directory). Valores omitidos, `null` ou vazios mantêm os diretórios de trabalho padrão.

O `web_search` do Tavily também aceita listas opcionais `include_domains` e `exclude_domains` na entrada da ferramenta no `config.yaml`, para controlar as fontes de busca. Um `include_domains` não vazio usa o modo `filter` do Tavily para restringir os resultados a esses domínios. São configurações da implantação; o modelo continua informando apenas `query` e o `time_range` opcional. Filtros omitidos preservam a requisição atual do SDK; uma lista vazia explícita é repassada e não impõe nenhuma restrição desse tipo. Veja o [exemplo de configuração de ferramentas](backend/docs/CONFIGURATION.md#tools).

O `web_search` do Serper também suporta `include_domains` e `exclude_domains` no nível da implantação. Ele verifica os hosts das URLs retornadas (incluindo subdomínios), e a exclusão tem precedência. Os filtros podem devolver menos resultados, inclusive zero; não há requisições para completar a lista. Isso seleciona fontes, não garante exatidão factual nem define uma política global de acesso a URLs. Os argumentos do modelo e a busca de imagens não mudam. Veja em [Serper configuration](backend/docs/CONFIGURATION.md#serper-source-filters) a validação e os limites de tamanho de consulta.

Ao usar o Tavily para `web_fetch`, páginas extraídas sem título usam a própria URL como cabeçalho; o conteúdo delas continua disponível para o agente. Os títulos dos passos de ferramenta no chat aceitam linhas em branco iniciais e até três espaços antes do primeiro cabeçalho H1 da página. Código indentado, inclusive com mistura de espaços e tabs, não é usado como título; o passo de ferramenta recorre à URL. A busca e o fetch do Tavily leem `api_key` cada um da sua própria entrada de ferramenta no `config.yaml`, recorrendo a `TAVILY_API_KEY` quando ela é omitida. O fetch não reutiliza a chave da entrada de busca, então a busca pode usar outro provedor. Se antes você configurava uma chave Tavily compartilhada só em `web_search`, defina-a também em `web_fetch` ou use `TAVILY_API_KEY` para os dois.

#### Exportando skills personalizadas

Administradores podem exportar suas próprias skills personalizadas em **Capability Center → Skills → My skills → View details → Export**. Revise a lista de arquivos e os requisitos de ambiente declarados e depois escolha **Download .skill**. O arquivo contém a skill como está salva no momento, incluindo arquivos de apoio e diretórios vazios; skills desabilitadas também podem ser exportadas. Se a skill mudar depois da pré-visualização, atualize a lista de arquivos antes de baixar. Importe o arquivo em outra instância do DeerFlow com **Install .skill**; conflitos com nomes existentes e as verificações normais de segurança da instalação continuam valendo.

Configurações de conta, conversas e histórico fora da pasta da skill ficam de fora. Os arquivos dentro da pasta são preservados sem alteração, inclusive credenciais que o autor tenha colocado ali; os avisos sobre nomes de arquivo são apenas informativos. Configure dependências e credenciais no destino. Pastas/arquivos vinculados, hard links, binários executáveis não suportados, arquivos `SKILL.md` aninhados e caminhos não portáteis não podem ser exportados. A exportação funciona em hosts com APIs de sistema de arquivos no-follow relativas a descritor (Linux/macOS); hosts não suportados falham de forma explícita. Limites: 4096 entradas no ZIP, 64 MiB por arquivo, 100 MiB de conteúdo/arquivo no total e 1 MiB de frontmatter. Aliases YAML e declarações excessivamente complexas não são suportados. A semântica comum de executável dos scripts é preservada na importação em POSIX, sem restaurar permissões especiais. Veja [o contrato da API de exportação](backend/docs/API.md#export-a-custom-skill).

#### Integração com o Claude Code

A skill `claude-to-deerflow` permite interagir com uma instância do DeerFlow em execução direto pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Envie tarefas de pesquisa, confira o status, gerencie threads, tudo sem sair do terminal.

**Instale a skill**:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Depois, confira se o DeerFlow está rodando (por padrão em `http://localhost:2026`) e use o comando `/claude-to-deerflow` no Claude Code.

**O que dá para fazer**:
- Enviar mensagens ao DeerFlow e receber respostas em streaming
- Escolher modos de execução: flash (rápido), standard, pro (planejamento), ultra (sub-agents)
- Verificar a saúde do DeerFlow, listar modelos/skills/agentes
- Gerenciar threads e o histórico de conversas
- Enviar arquivos para análise

**Variáveis de ambiente** (opcionais, para endpoints personalizados):

```bash
DEERFLOW_URL=http://localhost:2026            # Unified proxy base URL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

Veja a referência completa da API em [`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md).

### Recuperação de conhecimento privado (RAGFlow)

As respostas podem citar evidências recuperadas do RAGFlow com citações de conhecimento clicáveis. Clique em uma citação, ou em uma entrada da lista de fontes de conhecimento da resposta, para ver o trecho original recuperado, os nomes do dataset e do documento e os números de página, quando o RAGFlow os fornece. São snapshots do momento da recuperação, guardados junto com a conversa, incluindo fontes repassadas por subagents comuns de `task`; eles continuam inspecionáveis depois de recarregar a conversa. Um trecho não é uma cópia viva do documento inteiro: mudanças no RAGFlow não reescrevem evidências passadas. Registros de fonte ausentes aparecem como indisponíveis, em vez de virarem links adivinhados. Os snapshots de fonte não adicionam uma página de gestão de conhecimento nem expõem a chave de API do RAGFlow. Exportações duráveis em lote e arquivos Markdown avulsos não carregam esses registros interativos de fonte da conversa. Links comuns com título de documento em uma seção Sources abrem a mesma evidência das citações inline. Quando há um orçamento de saída de ferramenta, só continuam citáveis as entradas de evidência completas que cabem nele; as fontes omitidas são reportadas, em vez de se manter um registro de fonte para um trecho cortado.

O DeerFlow pode, opcionalmente, se conectar a uma implantação RAGFlow com escopo de tenant. A ferramenta de Agent `knowledge_search` resolve o escopo de datasets configurado, agrupa os datasets por modelo de embedding e faz a recuperação desses grupos em paralelo, para que modelos de embedding misturados não causem erro no provedor. IDs de dataset e chaves de API nunca são expostos ao modelo. A ferramenta opcional `list_knowledge_bases` retorna apenas nomes.

Os chats principal e de agentes personalizados podem expor, opcionalmente, um seletor **Knowledge** local à página, só com ícone, ao lado do controle de modo. O destaque persistente indica que a recuperação de conhecimento está ativa; o estado neutro significa que está desligada. Defina `knowledge_base.scope_selection_enabled: true` no `config.yaml`, usando o provedor nativo `knowledge_search` do RAGFlow, para permitir todos os datasets autorizados, datasets/arquivos selecionados ou nenhuma recuperação em um turno. A mesma flag de configuração controla os dois tipos de chat; quando desabilitada, nenhum dos composers mostra o seletor nem envia um escopo. A escolha volta para o padrão salvo do agente personalizado (ou para todos, quando não há vínculo) ao atualizar a página ou abrir outra conversa; cada mensagem humana enviada guarda um snapshot imutável do escopo para replay e histórico. O Gateway valida cada snapshot, faz a interseção com a allowlist de datasets do operador, propaga o escopo, que é só de execução, para subagents nativos e duráveis, e o remove das entradas do modelo e dos traces externos. Controles internos de runtime e credenciais enviados pelo cliente também são retirados do contexto do run antes da execução ou da persistência em checkpoint. Novas tentativas idempotentes aceitam tanto snapshots canônicos quanto entradas brutas legadas de run, preservando a compatibilidade de retry entre atualizações.
Agentes personalizados podem salvar uma seleção de **Default knowledge** em **Agents → Agent settings**, incluindo filtros opcionais de arquivo ou recuperação desligada. Selecionar todas as bases de conhecimento limpa o vínculo. O mesmo campo `knowledge_scope` está disponível nas APIs de criação/atualização de agentes e na configuração armazenada do agente; atualizações que o omitem o preservam, e `null` o limpa. É um padrão, não uma fronteira de autorização: uma seleção explícita por mensagem o sobrescreve, e a allowlist do operador continua valendo no momento da recuperação. Runs do Gateway sem escopo de mensagem (incluindo turnos agendados e de canais) usam o padrão salvo e fazem snapshot dele, mesmo quando o seletor do composer está oculto. Regenerar/retomar mantém o escopo do turno original, inclusive em turnos legados sem escopo, em vez de pegar mudanças posteriores de configuração. Seleções desconhecidas ou indisponíveis nunca ampliam a recuperação. Novas tentativas idempotentes mantêm o run e o escopo originais quando um padrão é adicionado, alterado ou limpo, incluindo runs sem escopo aceitos antes deste recurso. Esse padrão se aplica a turnos de agentes personalizados hospedados no Gateway; integrações diretas de harness/cliente continuam fornecendo o próprio escopo de execução.

O bloco `knowledge_base` é neutro em relação ao provedor e só controla se a capacidade de conhecimento e o seletor ficam habilitados. A conexão com o RAGFlow, a allowlist de datasets e os parâmetros de recuperação (`base_url`, `api_key`, `datasets`, `page_size`, thresholds e limites de saída) precisam ser configurados na entrada `tools[].name: knowledge_search`; eles nunca são lidos de `knowledge_base`.
As requisições de chat de agentes personalizados levam o nome do agente selecionado tanto em `assistant_id` quanto em `context.agent_name`, de modo que a admissão de escopo do Gateway e o carregamento do agente em runtime usam a mesma identidade. As requisições do chat principal usam `lead_agent`; as duas identidades só são admitidas quando a configuração compartilhada habilita o provedor RAGFlow. Ao responder a um pedido de esclarecimento pendente, vence um snapshot atual do seletor enviado explicitamente; clientes que o omitem herdam o escopo aceito no turno anterior. Editar e regenerar segue o mesmo fallback, e o catálogo de arquivos só é carregado depois que um dataset passa de todos os arquivos para arquivos selecionados. Esta versão não adiciona um item Knowledge independente à barra lateral do workspace nem uma página de gestão de conhecimento no DeerFlow; crie, envie, processe e exclua datasets e documentos diretamente no RAGFlow.

Cada mensagem ainda pode selecionar até 1000 documentos. Quando mais de 100 documentos são selecionados em um único dataset, o DeerFlow os valida em lotes de no máximo 100, preservando a seleção completa. Se algum lote contiver um documento inacessível ou não pesquisável, a recuperação é rejeitada.

Implantações avançadas podem habilitar a autorização plugável com `authorization.enabled` no `config.yaml`. Um `AuthorizationProvider` configurado filtra as ferramentas negadas antes que cheguem ao modelo ou ao catálogo de ferramentas adiadas, e o mesmo provider é verificado de novo antes de cada execução de ferramenta de negócio, por meio do middleware de guardrail existente. As permissões de rota `threads:*` e `runs:*` do Gateway derivam do mesmo provider, enquanto as verificações de dono existentes e os gates de gestão exclusivos de admin continuam em vigor. Toda rota HTTP que inicia ou habilita um futuro run de Agent exige `runs:create`: isso inclui os endpoints stateless `POST /api/runs/stream` e `POST /api/runs/wait`, além das mutações de criar, atualizar, retomar e disparar manualmente tarefas agendadas. As mutações de tarefas agendadas mantêm a exigência atual de `threads:write`, e as rotas stateless aplicam separadamente a verificação de posse quando o ID de thread opcional vem no corpo da requisição. Um `tool_search` gerado só pode pular a segunda verificação de ferramenta quando fica à frente do catálogo adiado já filtrado do build atual. O acesso a modelos segue o mesmo provider: a lista `models` do Gateway é filtrada por principal, `model:use` é aplicado nas requisições de detalhe de modelo e de novo quando o runtime resolve o modelo do agente, e um modelo padrão negado cai para o primeiro candidato restante que também passe em `model:use`. O provider RBAC nativo suporta políticas de allow/deny por papel para `tools`, `routes`, `models`, `skills` e `sandbox`, e valida que `default_role` nomeia um papel configurado; a autorização vem desabilitada por padrão. Veja o `config.example.yaml` e a [RFC de autorização](docs/plans/2026-07-10-pluggable-authorization-rfc.md).

As sugestões de follow-up também verificam `model:use` antes de chamar o modelo selecionado, incluindo o modelo padrão quando nenhum nome é informado. Um modelo negado retorna HTTP 403 sem chamada ao LLM; falhas do provider de autorização seguem a política `fail_closed` configurada.

Em agentes com visão, o `view_image` e a leitura subsequente da imagem para o contexto do modelo também exigem `sandbox:execute`. Permitir só o nome da ferramenta não concede acesso ao arquivo de imagem; um papel com execução de sandbox negada não consegue reler metadados de imagem registrados antes, depois que suas permissões mudam. Entradas externas de run e atualizações de estado de thread não podem definir `viewed_images` nem `thread_data`; quando uma imagem salva é lida de uma cópia no host, o caminho dela precisa resolver para a thread do usuário atual e para o caminho virtual de imagem registrado.

Implantações avançadas também podem estender o próprio runtime do agente declarando classes `AgentMiddleware` em `extensions.middlewares`, no `config.yaml` ou no `extensions_config.json`. Cada entrada é uma string `module.path:ClassName` (construtor sem argumentos) ou um objeto `{class, kwargs}`, cujos `kwargs` são passados ao construtor. Os valores de `kwargs` precisam ser tipos JSON (objeto, array, string, número, booleano ou null); datas e timestamps YAML são convertidos em strings ISO para corresponder ao JSON. O DeerFlow carrega a mesma lista configurada nos pipelines do lead agent e dos subagents, depois dos middlewares nativos de runtime e dos guards de loop/token, mas antes da cauda de resposta terminal/segurança/esclarecimento. Assim, forks corporativos podem adicionar guardrails de domínio, governança de tool calls ou hooks de observabilidade sem alterar os builders de middleware nativos. Pacotes ausentes, classes inválidas, módulos quebrados e erros de construtor falham de forma ruidosa na criação do agente. Trate o `config.yaml` e o `extensions_config.json` como arquivos confiáveis, controlados pelo operador: caminhos de middleware são execução de código, assim como as declarações de ferramenta personalizada, modelo, sandbox, guardrail, servidor MCP e interceptor MCP. Os endpoints de toggle de skill/MCP do Gateway preservam esse campo, mas não expõem um caminho de escrita via API para `extensions.middlewares`. Listas de middleware separadas, só para o lead ou só para subagents, ainda não são suportadas.

Para integrações de runtime empacotadas e configuráveis, use o gerenciador de extensões do DeerFlow. Ele aceita um requisito de pacote Python, uma URL Git HTTPS pública ou um diretório local, instala o pacote no grupo de dependências `extensions` dedicado do backend, atualiza o `backend/uv.lock` e adiciona uma entrada habilitada à lista de nível superior `plugins:` do `config.yaml`, que só é lida na inicialização:

```bash
# PyPI — pin a version for a reproducible deployment
make extension-install SOURCE="deerflow-extension-acme==1.2.3"

# Public HTTPS Git — pin an immutable commit
make extension-install \
  SOURCE="git+https://github.com/acme/deerflow-extension-acme.git@0123456789abcdef0123456789abcdef01234567"

# Local package — an absolute path avoids Make's backend-relative working directory
make extension-install SOURCE="$PWD/examples/deerflow-extension-example"

make extension-list
make extension-upgrade SOURCE="$PWD/examples/deerflow-extension-example"
make extension-disable NAME=acme
make extension-enable NAME=acme
make extension-remove NAME=acme
```

A instalação é interativa porque instalar um pacote pode executar build hooks em Python, e a extensão carregada depois roda com os privilégios do Gateway. Para uma origem já revisada, a automação pode reconhecer essa fronteira explicitamente com `cd backend && uv run --frozen --no-group extensions deerflow extensions install <source> --yes`. O gerenciador exige uv 0.8.0 ou mais recente; as imagens Docker fornecidas fixam o uv 0.11.1. Os outros comandos diretos são `deerflow extensions upgrade SOURCE`, `list`, `enable NAME`, `disable NAME` e `remove NAME`; `NAME` pode ser o nome da extensão, a distribuição Python ou o valor `module:install`. Não coloque credenciais em uma URL de origem: uma URL com userinfo embutido ou com um parâmetro de query que pareça credencial é rejeitada antes de o uv rodar. Origens Git remotas precisam usar HTTPS público; URLs Git por SSH são rejeitadas porque o builder Docker padrão não repassa as credenciais SSH do host. Instalar a partir de uma URL de loopback é permitido para ferramentas locais, mas gera um aviso, porque o `127.0.0.1` registrado no lock é outra máquina dentro do builder Docker.

Um pacote gerenciado declara exatamente um entry point padrão PEP 621:

```toml
[project.entry-points."deerflow.extensions"]
acme = "acme_deerflow_extension:install"
```

Esse callable usa o contrato independente `deerflow-extension-api` e pode registrar vários tipos de contribuição: middleware isolado em posições semânticas de modelo ou de ferramenta do lead/subagent, hooks de ciclo de vida de task do lead e dos subagents, observers para chamadas de modelo do próprio DeerFlow que não são envolvidas pelos hooks de chamada de modelo dos middlewares (goal, memória, título e sumarização), serviços com o tempo de vida do Gateway e routers HTTP FastAPI carregados de imediato. O pacote do contrato não tem dependências de framework; as extensões precisam declarar FastAPI, LangChain, LangGraph ou outras bibliotecas que importam.
O [exemplo de triagem de conteúdo buscado](examples/deerflow-extension-jev-screening/README.md) contribui com um middleware desses na posição visível de ferramenta. Depois do opt-in do operador, ele classifica o texto sanitizado que um resultado de ferramenta remota mostra ao modelo, com PII removida quando `pii_redaction` está habilitado, e adiciona um aviso consultivo por meio de uma atualização de estado de ciclo de vida; ele importa apenas o contrato de extensão.

Contribuições full-stack podem, além disso, fornecer páginas de navegador, ações de conversa, operações autenticadas de backend e ferramentas de modelo por meio das [APIs de plugin](docs/full-stack-plugins.md). O [exemplo de bookmarks](examples/deerflow-extension-bookmarks/README.md), independente, demonstra um pacote com dados de usuário persistentes, uma página própria na barra lateral e uma ferramenta de busca somente leitura. Reabrir um bookmark resolve o agente atual da conversa pelo host, então conversas de agentes personalizados mantêm o ponto de entrada original do chat, inclusive em bookmarks antigos. O [exemplo de Agent teams](examples/deerflow-extension-agent-teams/README.md), também independente, permite que Custom Agents completos colaborem por menções nativas com `@`, mensagens compartilhadas e pedidos assíncronos entre pares, com uma página de equipe separada e conversas persistentes dos membros. O Capability Center lista o exemplo com informações de instalação localizadas antes mesmo de ele ser instalado. A instalação e a ativação continuam controladas pela implantação; o Capability Center mostra informações e status dos plugins. O código de navegador roda como código confiável de mesma origem. A API de navegador e o transporte inline `BrowserModule.code` são experimentais. O guia de plugins descreve um caminho aditivo para manifests e recursos estáticos empacotados.

O DeerFlow aloca um extension store com escopo de task apenas para middleware, ciclo de vida ou observação de modelos de sistema. Os serviços recebem dependências de runtime com escopo de app depois que a persistência do Gateway está pronta, e param em ordem inversa depois que os runs ativos são drenados. O `ExtensionRuntimeDeps.run_evidence_reader`, opcional, é uma interface estável e somente leitura para serviços de auditoria, avaliação, sincronização e observabilidade: ele descobre runs alterados com um cursor opaco e retomável, pagina os eventos persistidos de um run conhecido com `after_seq` e lê o status autoritativo do run separadamente das evidências de eventos. Um run store apoiado em banco de dados mantém o cursor de descoberta válido entre reinícios do Gateway; o run store em memória oferece a mesma ordenação só durante a vida do processo atual. Os metadados de evento têm segredos removidos nessa fronteira, mas o conteúdo do evento é devolvido sem alteração. Os dois payloads são snapshots desacoplados, então modificar valores aninhados não muda as evidências armazenadas pelo host. O Gateway de produção fornece um reader com escopo de app, entre usuários, para extensões confiáveis do operador; um host embutido pode vincular o mesmo adaptador a um único usuário. As páginas de runs alterados contêm criações e mudanças em linhas retidas, não tombstones de exclusão; consumidores que reconciliam exclusões precisam consultar o status dos runs conhecidos e tratar um resultado ausente como inexistente. As extensões ainda executam com privilégios do Gateway e mantêm a `session_factory` legada, então o reader é uma fronteira de estabilidade de API e de menor privilégio acidental, não um sandbox para pacotes Python não confiáveis. Os routers HTTP de extensão são montados depois de todas as rotas do host; sobreposições definitivas e rotas que entram nos caminhos do host isentos de autenticação ou de CSRF são rejeitadas com diagnósticos atribuídos, enquanto routers não relacionados continuam carregando. Como os caminhos públicos do host são uma lista de prefixos reservados em que as extensões não podem entrar, **todo endpoint contribuído exige uma sessão autenticada**. Hoje não há como uma extensão expor uma rota não autenticada, então webhooks de entrada de provedores e endpoints públicos de status estão fora do escopo desta versão. Dentro disso, uma extensão distingue um usuário comum de um administrador por `deerflow_extension_api.auth`: `resolve_principal(request)` retorna quem chama, `require_admin(request)` lança `PermissionError` para qualquer outra pessoa e fecha em modo seguro quando a identidade não pode ser determinada. As extensões recebem uma projeção (id de usuário, flag de admin, flag de interno, papéis), nunca o contexto de autenticação do host. Hooks de startup/shutdown de router, lifespans personalizados, Mounts e rotas WebSocket não são aceitos; recursos com tempo de vida pertencem ao `ExtensionService`, e contribuições WebSocket exigem um futuro wrapper de autenticação/Origin de propriedade do host. Os callbacks de ciclo de vida e de modelos de sistema usam o loop canônico de notificação do Gateway, inclusive para subagents em loops isolados.

Rotas de extensão voltadas ao usuário podem chamar `deerflow_extension_api.require_run_evidence_reader(request)` (extension API 0.2.2+). O Gateway exige a permissão autenticada `runs:read` e fixa o escopo do reader nesse usuário, incluindo administradores e chamadores internos. IDs fornecidos por quem chama não mudam esse escopo. Runs invisíveis e runs ausentes retornam o mesmo resultado; cursores de runs alterados não podem ser reutilizados diretamente entre usuários. O `resolve_run_evidence_reader(request)`, opcional, retorna `None` quando o host não suporta a capacidade; o helper obrigatório, nesse caso, lança `NotImplementedError`. Acesso negado lança `PermissionError`. As rotas devem mapear essas exceções para HTTP 503 e 403, respectivamente; falhas do resolver nunca recorrem ao reader de serviço global.

Os serviços de extensão podem, opcionalmente, receber um [host model invoker](backend/docs/extension-model-invocation.md) (extension API 0.2.4+). Os operadores mapeiam explicitamente os papéis lógicos permitidos em `plugins[].host_access.model_invocation`; o host cuida de credenciais, concorrência, timeouts e saída validada por schema. A admissão é limitada; um trabalho de provedor que estourou o timeout mantém seu slot de concorrência até terminar, e a validação de schema roda em processos filhos que podem ser encerrados. O cancelamento feito pelo próprio provedor vira `ModelInvocationFailed`, enquanto o cancelamento da task da extensão que chama continua se propagando normalmente. Sem uma concessão, a capacidade é `None`.

A ordem dos plugins é determinística, a configuração por plugin é passada para `install()`, e `required: true` faz uma falha de carregamento abortar a inicialização; caso contrário, as falhas são reportadas e puladas. `enabled: false` pula a resolução e o import. O gerenciador preserva o `config` privado da extensão ao alterná-la e grava os metadados `name`, `package`, `use`, `enabled` e `required` nas instalações gerenciadas. As instalações são registradas com `required: false`, para que uma extensão que quebre depois seja reportada em vez de bloquear a inicialização do Gateway; passe `extensions install <source> --required` quando a ausência do pacote deve abortar a inicialização. Os plugins são carregados uma vez, quando o app do Gateway é construído, então instalar, habilitar, desabilitar, remover e editar `plugins:` manualmente exigem reiniciar o Gateway. Como isso importa código Python, `plugins:` propositalmente não está disponível no `extensions_config.json`, que é gravável pela API.

Os comandos de gerenciamento fazem o bootstrap do ambiente do checkout sem o grupo de extensões, via `uv run --frozen --no-group extensions`. O modo frozen permite que `disable` e `remove` iniciem mesmo quando a origem remota ou o snapshot gerenciado de uma extensão instalada ficou indisponível, enquanto um checkout novo ainda consegue criar o ambiente sem extensões a partir do lock existente. O próprio gerenciador é dono da transação de dependências com lock que vem em seguida. As mutações de um checkout são serializadas por um lock de processo. A superfície inicial do gerenciador é de criar/remover, não de atualização no lugar: para mudar uma origem instalada, salve o `plugins[].config` privado dela, remova-a, reinstale com o novo pin e restaure essa configuração.

Instalações a partir de diretório local são copiadas para `backend/extensions/sources/<normalized-distribution>/`; é esse snapshot implantável, e não o diretório original, que fica registrado no lock. Metadados do Git, ambientes virtuais, caches de bytecode, links simbólicos e arquivos com provável conteúdo de credenciais não são aceitos como conteúdo do snapshot. Revise o que você instala mesmo assim: filtrar arquivos acidentais não coloca em sandbox uma extensão, seu build backend ou seu código de runtime.

O `make dev`/`make start` local, o desenvolvimento com Docker e a imagem de produção do Gateway consomem todos o mesmo `backend/pyproject.toml` e o mesmo `backend/uv.lock`. Os launchers local e de Docker-dev fazem um sync com lock antes de iniciar; a imagem de produção faz esse sync durante o build e inclui no contexto de build os snapshots locais gerenciados. Os comandos de runtime do Gateway então usam o ambiente já criado, sem resolver nem instalar pacotes. Os syncs de pré-inicialização local e de desenvolvimento com Docker podem baixar artefatos do lock que estejam faltando. Uma implantação de produção, por sua vez, só os baixa durante a instalação explícita ou o build da imagem; iniciar o container de produção do Gateway resultante nunca resolve nem instala extensões pela rede. Um wheel local ou uma URL Git `file://` é rejeitado porque não existiria no contexto de build do Docker; passe um diretório de código-fonte para criar um snapshot gerenciado. Como a configuração de ambiente (por exemplo, um wheelhouse em `UV_FIND_LINKS`) ainda pode resolver um nome simples de pacote para um wheel local, o gerenciador audita cada novo lock antes de habilitar a extensão: qualquer referência local que o build da imagem padrão não consiga reproduzir desfaz a instalação ou a remoção inteira. Reconstrua com `make up` depois de mudar o conjunto de extensões gerenciadas. Veja um exemplo completo no `config.example.yaml` e na [extensão de referência](examples/deerflow-extension-example/).

As sugestões de follow-up geradas pelo Gateway agora normalizam tanto a saída do modelo em string simples quanto o conteúdo rico em blocos/listas antes de fazer o parsing da resposta em array JSON, de modo que wrappers de conteúdo específicos de provedor não descartam sugestões em silêncio.

O composer da Web UI pode polir o rascunho antes do envio. A reescrita roda como uma requisição curta de LLM no Gateway, usando a configuração de modelo `input_polish`, mantém prefixos de skill por barra como `/data-analysis` e só substitui o rascunho local depois que o usuário clica no botão de polir; ela não cria um run de thread nem persiste uma mensagem.

Quando o agente pede um esclarecimento, a Web UI mostra o card de resposta estruturada, mas mantém o composer normal disponível. O usuário pode preencher o card ou enviar uma mensagem de chat livre para contorná-lo; essa mensagem fecha o último esclarecimento pendente e vira a próxima entrada do agente. O texto de resposta que acompanha fica fora do painel de passos de execução, e responder ao pedido mantém na conversa o texto já concluído enquanto o agente continua.

Rascunhos não enviados do composer da Web UI sobrevivem a reloads da página e à troca entre conversas na mesma aba do navegador. Os rascunhos são isolados por usuário, agente e conversa, incluem a skill selecionada e as referências explícitas a conversas, e são limpos assim que um envio é aceito. Documentos de projeto já anexados à thread também sobrevivem a reloads; uploads locais do navegador e trechos de mensagens citadas não são persistidos.

O composer da Web UI suporta referências com `@` na posição do cursor ou pelo botão `@`. Busque skills habilitadas, documentos do projeto atual e outras conversas em um seletor agrupado; as referências selecionadas aparecem inline, junto ao texto do rascunho, e podem ser removidas com a edição normal. Várias skills podem ser selecionadas em uma mensagem (até 16 skills distintas); selecionar de novo uma skill marcada a remove, e cada seleção é verificada contra o registro atual do usuário e a allowlist do agente. Arquivos de projeto só são anexados depois que a ingestão dá certo; referências a conversas exigem a capacidade `read_conversation` e mantêm o limite dela por run. Se a descoberta de capacidades falhar, as referências a conversas salvas ficam intactas e o envio espera uma nova tentativa bem-sucedida. O polimento preserva os rótulos completos das referências quando as instruções são reordenadas. O grupo de arquivos também oferece uploads locais. `/goal`, `/compact` e a entrada legada `/skill-name` continuam suportadas.

O composer da Web UI também suporta ditado por voz no navegador quando ele expõe a Web Speech API. O botão de microfone transcreve a fala apenas para o rascunho local; o DeerFlow recebe só o texto transcrito, e o tratamento do áudio fica a cargo do serviço de reconhecimento de fala do navegador ou do sistema operacional, conforme a política desse ambiente. O usuário pode revisar ou editar o texto antes de enviar.

A Web UI mostra, abaixo do composer, um aviso localizado sobre conteúdo gerado por IA, tanto nas conversas padrão quanto nas de agentes personalizados, lembrando o usuário de verificar informações importantes.

Runs de primeiro turno interrompidos ainda persistem um título de conversa de fallback, então parar uma resposta em streaming não deixa a thread como "Untitled" depois de atualizar.

As respostas em Markdown em streaming animam apenas as palavras recém-chegadas; o texto que já está visível não some e reaparece quando o próximo chunk estende o mesmo bloco.

Na Web UI, turnos concluídos do assistant podem ser ramificados em uma nova conversa principal. Os títulos de branch herdados automaticamente usam o próximo sufixo numérico livre, neutro em relação ao idioma (`Title (2)`, depois `Title (3)` para outro irmão ou para um branch da conversa numerada), para que os títulos gerados de irmãos continuem distintos sem persistir um rótulo específico de locale; títulos de irmãos explícitos ou renomeados que coincidam também reservam o sufixo exibido, mesmo sem carregar metadados de sequência gerada. Um título explícito da API é preservado. Renomear um branch limpa a sequência gerada dele, então o próximo branch automático parte do título renomeado em `(2)`. A lista de chats recentes também agrupa os branches carregados logo abaixo de um pai carregado, com conectores de árvore discretos. Pais ausentes, linhagem malformada ou cíclica e branches em estado de fixação diferente continuam visíveis no nível superior, em vez de serem ocultados ou movidos para o outro lado da fronteira dos fixados. A nova thread parte do checkpoint daquele turno e mantém o checkpoint de replay anterior, então a resposta ramificada pode ser regenerada na hora. A resposta mais recente também pode ser regenerada depois de uma interrupção, mesmo quando o texto parcial em streaming nunca chegou a um checkpoint. Regenerar a resposta mais recente preserva o título atual da thread, inclusive um título que você renomeou manualmente depois da resposta original. Históricos legados ou importados sem links de checkpoint pai usam um fallback cronológico limitado; se não existir um checkpoint de replay anterior, a ramificação ainda dá certo no formato legado de checkpoint único, enquanto a regeneração fica indisponível para essa resposta herdada. Branches existentes de checkpoint único ficam como estão, em vez de se tentar uma cópia insegura de checkpoint. Como os arquivos do workspace não entram em checkpoint, o branch só recebe uma cópia best-effort do workspace atual quando você ramifica a partir do turno mais recente; ramificar a partir de um turno mais antigo mantém apenas o histórico de mensagens restaurado, para que o branch nunca herde arquivos criados em uma parte posterior da conversa.

A Web UI reporta o tempo da task concluída uma vez por run. É o tempo total de relógio, incluindo reasoning do modelo, tool calls e espera, e não uma duração por passo ou só de thinking do modelo. O conteúdo de reasoning continua disponível em sua própria área expansível, separada.

Enquanto uma resposta está em streaming, mensagens só de reasoning ficam no painel de processamento, incluindo os blocos de thinking da Anthropic. Quando o conteúdo da resposta chega junto com o reasoning, ele aparece em um balão do assistant.

Tags literais `<think>` em código cercado, indentado ou inline continuam fazendo parte da resposta e do texto copiado, em vez de serem movidas para a área de reasoning. Isso inclui cercas abertas em linhas de item de lista: o reasoning real depois do código ainda é extraído. Spans de código inline inacabados são preservados durante o streaming dentro de um parágrafo, mas terminam em uma linha em branco ou em um cabeçalho, lista, quebra temática ou cerca que os interrompa. Continuações de parágrafo indentadas não iniciam um bloco de código.

Na Web UI, o último turno de usuário concluído também pode ser editado e executado de novo pela barra de ferramentas da mensagem. O DeerFlow restaura o checkpoint da conversa anterior a essa mensagem do usuário, envia o texto editado como uma nova mensagem de usuário e oculta o turno substituído assim que o replay está em andamento ou dá certo. É apenas um replay do estado da conversa: arquivos, atualizações de memória e efeitos colaterais de ferramentas externas não são desfeitos.

Os links de chat da Web UI aplicam percent-encoding aos identificadores de thread personalizados antes de colocá-los nos segmentos de rota, então caracteres reservados de URL como `#` e `?` não mudam qual conversa é aberta.

### Arquivo de conversas

Excluir um chat pela barra lateral exige uma confirmação que mostra o título dele. A exclusão remove a conversa e seus arquivos e não pode ser desfeita.

Use **Archive chat** no menu de um chat recente na barra lateral para ocultar um trabalho concluído, mantendo as mensagens, os arquivos e o link original. A mensagem de sucesso oferece **Undo**. Abra **Chats → Archived** para encontrar as conversas arquivadas e restaurá-las uma a uma; uma conversa arquivada aberta também mostra um botão de restaurar no cabeçalho. A busca filtra os títulos das conversas carregadas, com **Load more** para as entradas mais antigas.

Arquivar e restaurar preservam o horário de atividade e o estado de fixação do chat. Arquivar não interrompe uma task em execução nem pausa os agendamentos dela, e novas atividades não o restauram automaticamente. Use a ação Delete existente quando a intenção for remover uma conversa e seus arquivos.

### Objetivos de sessão

Use `/goal <completion condition>` para anexar uma condição de conclusão ativa à thread atual. O goal é um estado com escopo de thread, não uma ativação de skill, então continua ativo entre turnos até o DeerFlow concluir que foi satisfeito ou até você limpá-lo. O agente vê o goal ativo em toda chamada ao modelo, então continua trabalhando nele mesmo depois que a compactação de contexto remove a mensagem que o declarou.

Comandos suportados:

```text
/goal finish the implementation and make all tests pass
/goal              # show the active goal
/goal clear        # clear it
```

Depois de cada run apoiado no Gateway, o DeerFlow avalia a conversa visível, incluindo as tool calls do assistant e os resultados de ferramenta encurtados, contra o goal ativo, usando um modelo avaliador sem thinking. Um resultado de ferramenta bem-sucedido não satisfaz sozinho um goal, e quando o assistant teve de adivinhar informação ausente ou ambígua o avaliador reporta `needs_user_input`. O avaliador precisa retornar um blocker tipado (`missing_evidence`, `needs_user_input`, `run_failed`, `external_wait` ou `goal_not_met_yet`) mais evidência visível. O DeerFlow só injeta uma continuação oculta quando o último turno do assistant está salvo em checkpoint de forma durável, o blocker é `goal_not_met_yet`, a thread não mudou durante a avaliação e o breaker de falta de progresso não disparou. O teto de segurança é, por padrão, de 8 continuações ocultas, e avaliações idênticas e repetidas sem progresso param depois de 2 tentativas. `/goal clear` e qualquer nova entrada escrita pelo usuário vencem as continuações na fila. Quando o avaliador considera o goal satisfeito, o DeerFlow o limpa depois que o run finaliza com sucesso e publica o estado atualizado da thread. Se a entrega obrigatória de artifact ou a persistência do recibo dela falhar, o run reporta um erro e o goal continua ativo para uma nova tentativa depois; isso não inicia outra continuação oculta.

A Web UI mostra o goal ativo acima do composer. O mesmo comando está disponível na TUI e nos canais de IM suportados. Na Web UI e nos canais de IM suportados, definir `/goal <completion condition>` também inicia um run com a condição como tarefa; os comandos de status e de limpeza só gerenciam o estado do goal. Definir ou limpar um goal é rejeitado enquanto a thread tem um run em andamento, incluindo um run que pertence a outro worker do Gateway, para que o checkpoint do goal não se ramifique para fora da linhagem de checkpoints de um run ativo.

Quando o seu papel não tem `runs:create`, a Web UI rejeita uma nova tarefa ou um `/goal <completion condition>` antes de preparar a thread ou salvar o goal, e mantém seu rascunho para tentar de novo. O status do goal, a limpeza do goal e o `/compact` continuam regidos pelas permissões dos seus próprios endpoints.

### Compactação manual de contexto

Com `task_continuity.enabled`, o `history_search` busca no histórico ativo e no compactado da task atual. O `role` opcional aceita `user`, `assistant` ou `tool` e filtra antes do limite de oito resultados; omiti-lo ou passar `null` preserva a busca em todos os papéis. Use `history_read` para verificar a fonte original; mensagens históricas do usuário não concedem autorização no presente. Veja [task continuity](docs/task-continuity.md).

A compactação automática e a manual excluem mensagens antigas de lembrete de todos tanto da entrada do resumo quanto do contexto retido. A lista de todos atual fica no estado da thread. No modo de planejamento, se a chamada original de `write_todos` não está mais visível, o DeerFlow adiciona um lembrete com os status mais recentes das tarefas antes da próxima chamada ao modelo. Uma compactação pulada ou que falhou deixa as mensagens existentes como estão.

O `pii_redaction.enabled`, opcional, remove identificadores detectados em mensagens do usuário, resultados de ferramentas remotas, entrada da compactação, resumos reinjetados e na entrada configurada do título por LLM. Vem desligado por padrão. Os placeholders de resumo existentes reservam índices, para que novos valores não os reutilizem depois da compactação. Nenhum mapeamento de PII é persistido, então valores repetidos não podem ser ligados a uma fonte compactada; a numeração pode mudar quando o histórico ou os placeholders de resumo desaparecem. O texto bruto da thread e os títulos de fallback locais continuam disponíveis para exibição; a extração de memória está fora do escopo deste recurso.

A Web UI preserva a ordem das mensagens persistidas ao mesclar o histórico com as atualizações ao vivo. Os passos em streaming em volta de um resultado persistido dentro do histórico carregado ficam juntos, incluindo os que chegam depois do resultado. Passos capturados durante a compactação também continuam visíveis antes do resultado persistido deles quando o histórico não foi atualizado e a interface ainda não os renderizou.

A compactação mantém o pedido atual do usuário e resume a atividade mais antiga de assistant/ferramentas. Quando resgatar esse pedido deixa uma janela de resumo só com assistant/ferramentas, o corte da entrada favorece o conteúdo mais recente dela. Em históricos mistos cuja âncora de mensagem do usuário cai fora do orçamento de corte, a compactação mantém o fallback existente da mensagem final. `summarization.trim_tokens_to_summarize` (4000 por padrão) controla o corte da entrada bruta do resumo; o escaping e a formatação do prompt acrescentam um custo além desse orçamento. Definir essa opção como `null` desabilita o corte da entrada para o modelo de resumo; faça isso apenas quando o modelo aceitar o histórico completo que está sendo compactado.

Use `/compact` no composer da Web UI para resumir o contexto mais antigo da thread atual. O DeerFlow mantém o chat inteiro visível, mas as chamadas futuras ao modelo usam o resumo compactado mais as mensagens recentes. O comando é ignorado quando não há histórico suficiente para compactar, e fica bloqueado enquanto a thread tem um run em andamento, inclusive quando esse run pertence a outro worker do Gateway. Se uma reserva com vários workers perde o lease, o DeerFlow cancela o escritor de checkpoint antes de o run substituto prosseguir e retorna um conflito que pode ser tentado de novo depois da limpeza. As edições de título de thread são serializadas pela mesma fronteira de escrita de estado e mostram um conflito, sem fechar o diálogo de renomear, quando há um run ativo.

O cabeçalho do chat também mostra um medidor da janela de contexto quando o modelo selecionado tem um `context_window` positivo configurado. Ele estima os tokens de mensagem do último checkpoint materializado e mantém visível a porcentagem anterior da mesma thread enquanto os dados são buscados de novo, independentemente da configuração de uso acumulado de tokens.

Quando `token_budget.enabled` e `token_usage.enabled` estão ambos habilitados, o orçamento de cada run do lead agent inclui o uso dos subagents concluídos, incluindo o lote final. As continuações ocultas de goal compartilham o orçamento; um novo run do usuário começa do zero.

### Sub-agents

Quando um sub-agent termina com ferramentas `return_direct=True`, incluindo ferramentas contribuídas por middleware de extensão, as saídas delas são devolvidas na ordem das tool calls. Uma ferramenta que falha marca a task como falha, preservando as saídas do lote.

As chamadas comuns de `task` aceitam `context_mode="isolated"` (padrão) ou `context_mode="snapshot"`. Tasks isoladas recebem o prompt delegado, como antes. Tasks em snapshot recebem também a conversa retida do pai e o resumo de compactação, capturados no dispatch como contexto histórico. Isso ajuda em handoffs que dependem de requisitos anteriores ou de abordagens que falharam, ao custo de mais tokens de entrada. São levados o texto retido, as descrições/resultados de tool calls e os blocos de entrada de mídia serializáveis em JSON. Blocos de mídia binários ou não serializáveis viram um aviso explícito de omissão; a conversa em volta continua disponível. Ficam de fora os system prompts do pai, as mensagens ocultas do framework (como memória injetada e lembretes de todos), os blocos de reasoning, os metadados de execução de ferramentas e as tool calls pendentes. As descrições de tool calls exigem um resultado correspondente retido, inclusive para chamadas ao lado da task atual. Respostas ocultas e válidas de esclarecimento do usuário continuam fazendo parte da conversa. O filho mantém o próprio papel, modelo, ferramentas e restrições de skill. Registros de ferramentas do pai não satisfazem as verificações de execução do filho. Depois disso, os históricos do pai e do filho evoluem de forma independente; o comportamento do sandbox/sistema de arquivos compartilhado não muda. O modo snapshot não restaura mensagens já compactadas nem promete reutilização do cache de prompt. Os itens duráveis de `batch_task` continuam exigindo prompts autocontidos.

Blocos nativos de documento são mantidos nos snapshots. O conteúdo textual, os títulos e o contexto deles passam pela mesma neutralização de tags reservadas e de fronteira de entrada aplicada ao restante do texto histórico; mídia codificada e origens em URL são preservadas sem decodificação.

Para uma comparação manual e sintética entre handoffs completos e snapshots, veja a [avaliação de snapshot de contexto](backend/scripts/benchmark/context_snapshot/README.md).

Os Custom Agents suportam um nome de exibição Unicode opcional, incluindo chinês e emoji. Abra **Agent settings → Display name** do agente para defini-lo (até 100 code points Unicode), ou deixe em branco para mostrar o identificador existente. Caracteres de controle e controles de formatação bidirecional são rejeitados; texto multilíngue comum e emoji são suportados. Nomes só com caracteres invisíveis e caracteres de formatação invisíveis, como espaços de largura zero, são rejeitados. Nomes de exibição inválidos em armazenamento antigo ou editado à mão caem para o identificador do agente na leitura; um aviso identifica o agente afetado. Refazer o bootstrap preserva os nomes de exibição válidos. A galeria, o cabeçalho do chat e a página de boas-vindas usam esse rótulo; URLs e chamadas de API continuam usando o `name` estável em inglês. Quem chama a API pode passar `display_name` nas requisições de criação ou atualização de agente; uma atualização que o omite o preserva, e `null` o limpa. O mesmo campo opcional é suportado no `config.yaml` do agente.

Sub-agents são uma otimização, não a resposta padrão a um pedido complexo.

Depois que o Stop interrompe uma task delegada antes de ela devolver uma resposta, o próximo turno do usuário marca essa task anterior como cancelada no contexto durável do agente, para que ele possa tentar de novo. As respostas existentes são preservadas. Respostas mais antigas sem metadados de status ainda podem aparecer como em andamento; o desfecho delas não é inferido a partir do texto. O registro durável de delegação distingue as chamadas por run e por ID de tool call do provedor, então um turno posterior do usuário pode reutilizar um ID sem substituir trabalho anterior nem perder a contagem de delegações por run daquele turno.

O lead agent pode criar sub-agents sob demanda, cada um com seu próprio contexto delimitado, suas ferramentas e suas condições de término, quando a delegação traz um benefício líquido claro em latência paralela real, capacidade especializada ou isolamento de contexto. Ele mantém fora do dispatch paralelo os escopos interdependentes e os efeitos colaterais que se sobrepõem; uma cadeia sequencial limitada ainda pode rodar em um único sub-agent quando o ganho de especialização ou de isolamento de contexto é claro. O lead usa o menor número útil de sub-agents e reavalia os lotes seguintes, em vez de abrir um leque só porque a tarefa é grande ou tem vários passos. Os sub-agents devolvem resultados estruturados, e o lead agent os verifica e sintetiza em uma saída coerente. Os recibos determinísticos de ferramenta cobrem tanto mensagens diretas de ferramenta quanto resultados `Command` que atualizam estado, como as respostas de `task` delegadas; quando o registro de recibos atinge o orçamento de contexto, ele mantém as ações mais recentes e os IDs originais dos recibos. Operadores podem desabilitar essa camada de proveniência com `verification.receipts_enabled: false`. As skills configuradas para eles são resolvidas no mesmo catálogo com escopo de usuário do lead agent, então skills personalizadas do usuário continuam disponíveis sem expor a versão de outro usuário. As mensagens internas de IA e de ferramenta deles ficam restritas ao grafo delegado, em vez de entrar no stream do chat pai. O histórico de thread recarregado aplica a mesma fronteira: as respostas de IA dos sub-agents capturadas por callback continuam disponíveis nos diagnósticos de eventos de run, mas ficam fora da transcrição do pai, enquanto o resultado da `task` do pai continua anexado ao card da subtarefa. Sub-agents de longa duração compactam o histórico mais antigo quando a sumarização está habilitada e reinjetam o resumo como contexto durável oculto e protegido antes de continuar, de modo que a atividade recente de assistant/ferramentas continua ancorada na task. As instruções de sistema deles, incluindo o papel e o contrato de relatório, sobrevivem à compactação; se só essas instruções e o pedido atual fossem resumidos, a compactação é pulada. Falhas de requisição ao provedor/modelo são reportadas como tasks de sub-agent com falha, e não como resultados bem-sucedidos, para que o lead agent e a Web UI reajam a elas corretamente. Runs pais concorrentes também recebem IDs de execução de sub-agent independentes do lado do servidor, então um provedor que reutiliza um ID de tool call não consegue fazer um run consultar, cancelar ou limpar a task em background de outro run. Os cards recolhidos de sub-agent mostram o modelo efetivo e, quando o provedor devolve metadados de uso, um total acumulado de tokens que é atualizado depois de cada chamada de LLM concluída do sub-agent e persiste após um reload. Com o rastreamento de uso de tokens habilitado, o uso dos sub-agents concluídos é atribuído de volta ao passo que fez o dispatch a partir dos metadados da mensagem terminal de ferramenta daquele run, e não de um cache global ao processo indexado por ID do provedor.

Execuções de sub-agent em background canceladas ou que estouraram o timeout mantêm o uso de tokens reportado pelo provedor nas chamadas de modelo concluídas, incluindo respostas recebidas antes da próxima atualização de progresso. A entrega final de uso ao run pai não conta em dobro os snapshots de progresso anteriores.

Nos critérios de aceitação de arquivo, um arquivo regular vazio no workspace compartilhado pode satisfazer `file:<path> exists` e `file_written:<path>`, inclusive em sandboxes remotos. Ele falha em `file:<path> non-empty` com um resultado determinístico de arquivo vazio.

Para pedir validação de sintaxe JSON, defina explicitamente o `acceptance_criteria` de um item de `task` ou `batch_task` como `["file:../outputs/report.json json-valid"]`. As verificações cobrem apenas arquivos JSON UTF-8 completos dentro do workspace compartilhado, de até **50.000 bytes**. Sintaxe válida retorna `holds`; arquivos vazios, erros de sintaxe, conteúdo que não é UTF-8 ou `NaN`/`Infinity` retornam `does not hold`. Arquivos grandes demais, leituras incompletas, caminhos fora do escopo ou limites de recursos do parser retornam `UNVERIFIED`. As leituras são limitadas a 50.001 bytes para detectar conteúdo acima do tamanho. Os resultados remotos são verificados quanto a um marcador de conclusão, ao código de saída da leitura e ao tamanho sondado. Provedores remotos sem as ferramentas de probe necessárias deixam o resultado sem verificação, em vez de recorrer à leitura do conteúdo inteiro. Escritas concorrentes de mesmo tamanho não produzem um snapshot atômico. As verificações locais autorizam o acesso ao sandbox antes de resolver caminhos ou sondar metadados, e verificam de novo antes de ler o conteúdo; permissões revogadas retornam `UNVERIFIED` sem revelar a existência. Os probes remotos só reportam arquivos ausentes quando há um ancestral pesquisável e um caminho canônico dentro do escopo; diretórios inacessíveis continuam `UNVERIFIED`. BOMs UTF-8 são rejeitados. Escalares de nível superior, chaves duplicadas e números grandes sintaticamente válidos podem passar, sem validação de schemas, campos ou semântica de negócio. Os outros critérios de arquivo não mudam, e arquivos `.json` não são verificados automaticamente. Esse critério padroniza os veredictos, as fronteiras de caminho e os limites de leitura, em vez de exigir verificações ad hoc em bash/Python, e deixa explícito quando a evidência é insuficiente. O status de conclusão da execução e a política de nova tentativa automática não mudam.

Mensagens finais de sub-agent sem conteúdo reportam `No response generated` em vez do texto literal `None`. Um fallback de erro de provedor sem conteúdo reporta o detalhe estruturado do erro, quando disponível.

Uma `task` comum também recebe um snapshot defensivo dos uploads atuais do run que fez o dispatch. Isso permite que sub-agents elegíveis usem `list_uploaded_files` para encontrar arquivos de turnos anteriores sem devolver como históricos os anexos do mesmo turno. Workers de `batch_task` atrasados ou recuperados deixam essa ferramenta desabilitada porque não têm uma fronteira válida de upload local ao turno.

A descoberta de uploads históricos suporta paginação estável: `list_uploaded_files` retorna 20 itens por página por padrão, com máximo de 100; passe o `next_cursor` retornado como `cursor` na chamada seguinte, mantendo os mesmos filtros, até que a última página deixe de retornar um cursor. Quando os metadados do diretório ou o contexto da chamada mudam, uma nova enumeração é exigida explicitamente; veja os detalhes na [documentação de upload de arquivos](backend/docs/FILE_UPLOAD.md).

Os workers duráveis de `batch_task` usam um único snapshot de plugins, de propriedade do app, para a montagem e a execução de ferramentas. Tasks recuperadas adotam o snapshot de plugins do novo worker depois de um reinício do Gateway; objetos de plugin nunca são armazenados nos registros duráveis de task.

A delegação comum por `task` e a execução durável explícita por `batch_task` compartilham a capacidade de processo `subagent_runtime`, cujo escopo é a inicialização. O modo batch mantém em SQL grandes conjuntos de itens independentes, com limites separados de total, vivos e em execução, recuperação após reinício, resultados limitados e um painel na Web UI com escopo de thread. O painel pagina, sob demanda, pré-visualizações limitadas; o texto completo do resultado armazenado só fica disponível pela exportação JSONL com escopo de dono, enquanto o contexto interno de execução e de autorização nunca entra nas respostas voltadas ao dono. Se o worker de batch for parado ou desabilitado mais tarde, as threads com batches persistidos mantêm a inspeção somente leitura dos itens e a exportação JSONL; os controles de execução ficam desabilitados até o worker voltar a rodar. Veja os limites e a semântica de recuperação no `config.example.yaml` e no [contrato de implementação](docs/plans/2026-08-24-subagent-batch-capacity-implementation.md).

Se o lease final de um item expira depois de esgotado o orçamento de novas tentativas, o batch chega a um estado terminal assim que todos os itens são terminais: `failed` quando nenhum deu certo, ou `completed` quando ao menos um deu certo. O item continua `failed` nos dois casos, para que os resultados parciais sigam visíveis.

Integrações diretas com `create_deerflow_agent(...)` podem assumir a mesma fronteira explicitamente, em vez de depender da inicialização do Gateway. Construa um `SubagentRuntime` e compartilhe-o entre todos os grafos da aplicação; o `max_running` dele, o total comum por run, a ferramenta `task` vinculada e as ferramentas opcionais de batch durável passam a usar o mesmo snapshot e o mesmo controlador de execução, de propriedade de quem chama. Um runtime com repositório de batch é dono de um worker e precisa ser iniciado antes da construção do grafo e parado no shutdown da aplicação:

```python
from deerflow.agents import RuntimeFeatures, create_deerflow_agent
from deerflow.subagents import SubagentRuntime

runtime = SubagentRuntime.from_app_config(app_config, batch_repository=batch_repository)
async with runtime:
    graph = create_deerflow_agent(
        model,
        features=RuntimeFeatures(subagent=True),
        subagent_runtime=runtime,
    )
    # Serve or invoke graph while the durable worker is running.
```

O `SubagentRuntime.stop()` espera o serviço de batch que ele possui terminar antes de propagar o cancelamento de quem chama, inclusive cancelamentos repetidos. Essa drenagem não tem timeout; as operações de repositório e a limpeza dos filhos precisam terminar. Se o shutdown do serviço também falhar ou for cancelado, o primeiro cancelamento de quem chama é preservado, com a falha do serviço como causa.

A factory continua sem carregar YAML e sem criar infraestrutura SQL: quem chama fornece o snapshot de configuração, o repositório e o ciclo de vida. Como ela aceita um `system_prompt` de propriedade de quem chama, as integrações diretas também são responsáveis por qualquer texto visível ao modelo sobre esses limites; o middleware padrão aplica os limites de runtime de qualquer forma. A factory não monta as rotas HTTP com escopo de dono do Gateway nem a Web UI, então aplicações diretas precisam expor a própria API/UI de resultados, se precisarem dessas superfícies. Só para a delegação comum, `SubagentRuntime(...)` não precisa de inicialização assíncrona.

Administradores podem adicionar, editar, desabilitar e excluir definições reutilizáveis de worker em **Settings → Subagents**. As definições nativas e as do `config.yaml` continuam visíveis ali como entradas somente leitura. O Lead Agent padrão pode usar todos os sub-agents de runtime habilitados; já cada Custom Agent criado pela página pode permitir todos, nenhum ou um conjunto selecionado. Essa seleção é aplicada tanto no diretório visível ao modelo quanto pela ferramenta `task` do lado do servidor. Nesta versão, as definições gerenciadas valem para a implantação inteira e seguem `agent_storage.backend`: arquivos atômicos em uma implantação local ou o banco de dados compartilhado da aplicação em várias instâncias.

Por exemplo, pesquisas independentes e somente leitura podem rodar em paralelo quando a economia de tempo de relógio supera o custo duplicado de descoberta e síntese, enquanto um refactor de repositório com arquivos compartilhados e feedback sequencial de testes fica com o lead agent. Quando `max_concurrent_subagents` é `1`, a orientação de roteamento paralelo e em vários lotes é desabilitada; a delegação continua disponível apenas quando há ganho concreto de especialização ou de isolamento de contexto.

### Sandbox e sistema de arquivos

As saídas de ferramenta externalizadas no host usam o umask normal de criação de arquivos do Gateway. Os orçamentos de caracteres/contagem de `tool_output`, incluindo overrides por ferramenta, exigem inteiros não negativos; booleanos YAML são rejeitados, em vez de tratados como 0 ou 1. Um override explícito de zero por ferramenta desabilita a externalização, preservando qualquer limite global positivo de fallback. Sandboxes montados que rodam sob outro UID precisam de acesso de leitura pelas permissões do armazenamento compartilhado. Um shutdown abrupto pode deixar arquivos `.tool-output-*.tmp` em `tool_output.storage_subdir` (padrão `.tool-results`), dentro das saídas da thread. Remova as sobras durante a manutenção dos dados de thread, com todos os escritores do Gateway parados, ou ao excluir os dados da thread inativa correspondente.

O `E2BSandboxProvider` usa `wait` como política padrão de overflow. Ele espera `acquire_timeout` e depois faz o turno do agente falhar. O DeerFlow não tenta o turno de novo automaticamente. Os clientes podem usar o erro estruturado para agendar uma nova tentativa.

Use `burst` com `burst_limit` para permitir VMs extras de forma limitada. As políticas `wait` e `reject` usam apenas `replicas`. A política `reject` pode remover uma VM aquecida antes de retornar um erro.

Com ownership em memória, `replicas` limita um processo do Gateway. Com ownership em Redis, o E2B compartilha um Hash de capacidade entre os workers que usam o mesmo `sandbox.ownership.key_prefix`; `replicas` (mais um burst configurado) passa então a ser um limite rígido da implantação inteira. Use um prefixo único e o mesmo limite efetivo por implantação. Para mudar o limite, pare os Gateways dela, apague o Hash de capacidade e reinicie; workers com valores divergentes fecham em modo seguro.

O Hash conta VMs remotas e criações em andamento, repara criações interrompidas a partir dos metadados do E2B, protege com um período de tolerância omissões de inventário defasado e bloqueia novas criações enquanto o Redis ou o inventário inicial estão indisponíveis. Rode o Redis com persistência, memória sem evicção e alta disponibilidade.

A reconciliação do E2B renova as VMs ativas com um timeout positivo que cobre a cadência configurada, mesmo quando `idle_timeout` é zero ou menor que essa cadência. As VMs aquecidas mantêm o comportamento configurado de idle-timeout. Entradas aquecidas locais expiradas não liberam capacidade compartilhada diretamente: antes, o inventário remoto precisa confirmar o desaparecimento, passado o período de tolerância existente. A renovação ativa termina antes que a liberação defina o timeout de aquecida, então uma passada de manutenção concorrente não consegue estender a vida de uma VM ociosa. A limpeza de entradas aquecidas também preserva o ownership adquirido por uma nova requisição durante a varredura. Os heartbeats de ownership continuam independentes de requisições lentas de timeout do E2B, o que evita que atrasos do control plane façam leases de sandboxes ativos expirarem.

O E2B faz snapshot de `skills.container_path` quando o provedor inicia e inclui a raiz canônica na identidade de thread, na seed do warm pool e nos metadados remotos. Uma VM criada para outra raiz nunca é adotada; a reconciliação a remove depois do período de tolerância configurado, assim que nenhum peer ativo for dono dela. Reinicie o Gateway depois de mudar a raiz.

A aquisição no E2B usa um executor limitado. Aquisições em espera não usam o executor padrão do asyncio.

Cada passada de upload de mounts do E2B aceita no máximo 512 MiB e 2.000 arquivos. A passada também tem um prazo cooperativo de 120 segundos. As projeções de skills e os mounts configurados compartilham esses limites. O provedor confere o prazo antes de cada mount e durante o preflight de diretórios. Depois de expirado, o prazo interrompe novos uploads de arquivo. Ele não interrompe chamadas ativas ao sistema de arquivos ou ao SDK do E2B.

Uma VM do E2B mantém o slot até o E2B confirmar a destruição. Essa regra cobre as operações de criação e de recuperação. A descoberta pode encontrar uma VM de outro Gateway. O shutdown fecha um cliente de descoberta sem dono sem destruir a VM dele. A liberação para de contar uma transição quando a VM entra no warm pool. Corridas de shutdown tentam de novo a limpeza remota depois de uma falha transitória de kill. O reset destrói as VMs E2B ativas e aquecidas rastreadas. A instância antiga do provedor não pode aceitar novas aquisições.

O DeerFlow não fica só *falando* em fazer as coisas. Ele tem o próprio computador.

Cada task ganha o próprio ambiente de execução, com uma visão completa do sistema de arquivos: skills, workspace, uploads, outputs. O agente lê, escreve e edita arquivos. Ele consegue ver imagens e, quando configurado com segurança, executar comandos de shell.

A ferramenta nativa `grep` busca em um único arquivo de texto ou em todos os arquivos de texto correspondentes abaixo de um diretório, então um agente pode buscar direto em um documento enviado sem antes ampliar o pedido para o diretório de uploads inteiro.

O `ls` remoto exclui os descendentes ignorados antes de aplicar o limite de 500 entradas da listagem, para que árvores de dependências e de build não tomem o lugar dos arquivos visíveis. Listar explicitamente um diretório ignorado ainda mostra o conteúdo dele; os limites normais de profundidade e de saída continuam valendo.

As listagens de diretório do AIO descartam sessões de shell ausentes para que a próxima requisição consiga se recuperar. Depois de uma conexão perdida, as listagens de diretório e os comandos de shell persistente reportam um desfecho desconhecido sem repetir a operação; as chamadas seguintes usam uma sessão nova.

Os outlines de Markdown enviado reconhecem a sintaxe de cabeçalho ATX, limpam os marcadores de fechamento com uma varredura linear de sufixo e pulam exemplos de código cercado e indentado, para que hashtags e comentários de código não tomem o lugar das seções reais do documento na pré-visualização de cabeçalhos do agente. Exemplos em negrito indentados também ficam de fora; cabeçalhos em negrito no estilo PDF com até três espaços iniciais continuam suportados. Arquivos Markdown UTF-8 com ou sem byte-order mark (BOM) produzem os mesmos outlines e as mesmas pré-visualizações de fallback, com os números de linha originais preservados. Os títulos do outline são limitados a 200 caracteres e as pré-visualizações de fallback a 2.000 caracteres por arquivo, com marcadores de truncamento. Os arquivos enviados completos continuam disponíveis para leituras direcionadas.

Outlines e pré-visualizações de uploads convertidos exigem uma versão de origem correspondente, incluindo os timestamps de modificação. Uma mudança detectada na versão de origem invalida a conversão anterior, mesmo em edições de mesmo tamanho. Registros de posse mais antigos, sem timestamps de origem, também são rejeitados; envie a origem de novo com `uploads.auto_convert_documents: true` para restaurar os outlines baseados em conversão. Os arquivos continuam disponíveis, e conversões Markdown não validadas aparecem como arquivos avulsos na listagem histórica do agente. No Windows, `st_ctime_ns` pode representar a hora de criação; uma reescrita de mesmo tamanho que restaure o `mtime` original pode escapar da validação. As verificações de timestamp são uma validação conservadora de metadados, não uma garantia de igualdade de conteúdo.

Os bytes de imagem carregados para uma chamada a um modelo de visão são transitórios: o DeerFlow remove a mensagem base64 oculta depois que o modelo a consome, para que os checkpoints seguintes não fiquem duplicando esse payload.

Depois de cada run, o DeerFlow registra um resumo das mudanças do workspace para os diretórios `workspace` e `outputs` que pertencem ao run. A Web UI mostra um selo compacto de "files changed" no turno do assistant; ao abri-lo, aparecem os arquivos criados, modificados e excluídos, com diffs de texto quando é seguro exibi-los. Os uploads ficam de fora porque são entradas do usuário, não mudanças geradas pelo agente, e os arquivos temporários/de debug de MCP stdio no namespace `.mcp/`, de propriedade do DeerFlow, ficam de fora porque são estado interno de processo (assim como `.git/` e `node_modules/`, qualquer diretório chamado `.mcp` é excluído em qualquer profundidade). Arquivos grandes, binários ou com aparência de conteúdo sensível são mostrados só como metadados.

Os arquivos apresentados por `present_files` continuam fazendo parte do estado de artifacts da thread, e a Web UI restaura o painel de artifacts e o documento selecionado depois de um refresh da página. Quando uma resposta concluída apresenta com sucesso entre 2 e 50 arquivos, o card final de arquivos também oferece um download em ZIP. A composição do arquivo vem do recibo terminal de entrega, e não de caminhos enviados pelo navegador, e o ZIP contém as versões atuais dos arquivos, que podem ter mudado desde a resposta. O artifact formal selecionado no momento é atualizado uma vez quando o run termina, para que as edições apareçam sem reload manual. Artifacts de texto UTF-8 existentes em `/mnt/user-data/outputs` também podem ser editados e salvos explicitamente pelo painel, em Unix e Windows, enquanto a thread está ociosa; os salvamentos usam revisões de conteúdo para evitar sobrescrever mudanças do agente. As pré-visualizações de código-fonte também reconhecem pelos nomes os artifacts `Dockerfile` e `Makefile`, sem extensão. Tipos de arquivo desconhecidos, incluindo nomes como `constructor` e `__proto__`, mantêm o fallback de download.

As revisões de conteúdo de artifacts são atualizadas quando um arquivo de saída é substituído de forma atômica, mesmo que o tamanho e a hora de modificação sejam preservados. Atualizar a pré-visualização fornece então a nova revisão para salvar; uma pré-visualização mais antiga ainda exige um reload. Arquivos regulares acima do limite de edição de 2 MiB usam a identidade do arquivo e os metadados de mudança nos validadores de intervalo, sem calcular o hash do arquivo inteiro. Intervalos de bytes condicionais em arquivos regulares exigem um ETag correspondente; requisições `If-Range` em forma de data recebem o arquivo atual completo. O salvamento também limita a leitura do arquivo existente a 2 MiB mais um byte de detecção, então um arquivo que cresce ou é substituído depois da verificação de tamanho é rejeitado sem carregar na memória o arquivo inteiro, grande demais.

Artifacts CSV e TSV abrem como tabelas no painel de artifacts e em uma janela separada. A pré-visualização preserva valores de texto (incluindo zeros à esquerda), suporta uma linha de cabeçalho opcional e pagina até 200 linhas e 50 colunas da amostra inicial. Células longas ou com várias linhas podem ser abertas e copiadas por inteiro. Mude para o código-fonte para inspecionar ou editar o arquivo; os downloads e as janelas separadas usam a versão salva.

As pré-visualizações de artifacts HTML resolvem assets relativos a partir do diretório do artifact, a menos que o documento contenha um elemento `<base>` de verdade. Exemplos de tag base em comentários ou em texto de script não mudam essa resolução.

Se a amostra corta ao meio uma quebra de linha CRLF, a pré-visualização mantém as linhas completas anteriores e omite o registro final incompleto, inclusive quando o último campo dele está entre aspas.

Os artifacts de texto são transmitidos com suporte a byte-range HTTP. A Web UI carrega inicialmente no máximo 1 MiB, mostra o tamanho da pré-visualização quando o arquivo é maior e espera uma ação explícita de **Load full file** antes de buscar o restante ou montar o editor de código completo. A edição fica disponível depois que o arquivo inteiro foi carregado; a detecção de mudanças não salvas usa o conteúdo completo, inclusive ao reverter edições ou apagar a parte além da pré-visualização inicial. Se um reload falha ou devolve só uma pré-visualização, o usuário ainda pode sair da edição mantendo o rascunho não salvo. Artifacts ativos em HTML, XHTML e SVG continuam sendo downloads forçados na fronteira do Gateway.

As pré-visualizações e os downloads de artifacts preservam sequências literais de porcentagem nos nomes de arquivo: `report%20final.md` e `report final.md` continuam sendo arquivos distintos. Links Markdown continuam aceitando caminhos com URL-encoding.

A orientação do `write_file` reflete o limite de tokens de saída do modelo ativo, incluindo overrides de agente personalizado e de modo thinking. Para documentos mais longos, o agente é orientado a escrever por seções com `append=True`; modelos sem limite conhecido não recebem nenhuma dica numérica de orçamento.

Com o `AioSandboxProvider`, a execução de shell roda dentro de containers isolados. Com o `LocalSandboxProvider`, as ferramentas de arquivo ainda mapeiam para diretórios por thread no host, mas o `bash` do host vem desabilitado por padrão porque não é uma fronteira de isolamento segura. Reabilite o bash do host apenas em fluxos locais totalmente confiáveis. Os comandos de bash no host têm um timeout de tempo de relógio, e processos de longa duração devem ser iniciados em background, com a saída redirecionada para um log no workspace. No Windows, as exclusões de conversão de argumentos do Git Bash/MSYS se limitam a prefixos seguros de caminho virtual que não sejam a raiz, então os launchers de CLI nativos do host mantêm a compatibilidade normal com MSYS. Quando o sandbox local recorre ao PowerShell, ele captura a saída como UTF-8, para que texto CJK não dependa do locale do host do Gateway.

Os sandboxes Docker AIO mantêm por padrão o comportamento atual de egress aberto, por compatibilidade. Operadores podem definir `sandbox.network.mode` como `isolated` ou `allowlist`; o modo allowlist suporta domínios definidos pelo operador e um card interativo de Human Input para aprovação HTTP(S) temporária ou válida pela vida do sandbox. Endereços privados, de loopback, link-local, multicast e de metadados de nuvem continuam impossíveis de aprovar. Hostnames negados são rejeitados antes da resolução DNS. Runs em modo de interação `scheduled`, `webhook` ou `autonomous` negam automaticamente, sem abrir um card. Esses runs sem supervisão seguem em frente com suposições mínimas apenas em trabalho reversível e de baixo risco; trabalho de alto risco ou irreversível sem autorização suficiente retorna um resultado estruturado `BLOCKED` indicando a decisão que falta, mesmo que o modelo tente pedir esclarecimento. O sidecar confiável usa uma bridge de egress dedicada por sandbox, em vez da bridge padrão compartilhada do Docker, e rejeita nomes de campo HTTP ambíguos antes de encaminhar. Veja em [Sandbox configuration](backend/docs/CONFIGURATION.md#sandbox-network-policy) os requisitos de runtime e o modelo completo de políticas.

O `AioSandboxProvider` normalmente detecta os mounts de dados de thread a partir do backend: containers locais usam os diretórios montados do gateway, enquanto sandboxes remotos/de provisioner recebem os arquivos enviados por sincronização explícita. Implantações em que os dois lados com certeza compartilham os mesmos diretórios de dados de usuário por thread podem definir `sandbox.thread_data_mounts: true` para pular essa aquisição de sandbox e esse sync a cada upload. Deixe o campo sem definir para a detecção automática; defini-lo errado pode deixar os arquivos enviados indisponíveis dentro do sandbox.

Commits de upload que falham reportam o erro original mesmo que a limpeza do arquivo temporário também falhe, por exemplo por uma violação de compartilhamento do Windows. Depois que o arquivo é publicado, uma falha na limpeza do arquivo temporário é registrada em log sem fazer o upload falhar; os arquivos ocultos de staging ficam para a varredura de inicialização.

Uploads, novos arquivos de apoio de skills e novos caminhos do sandbox local rejeitam nomes de dispositivo reservados do Windows em todas as plataformas, incluindo `COM¹`, `LPT²` e nomes com extensão, como `com³.txt`. Renomeie esses arquivos antes de criá-los ou enviá-los, para que a mesma árvore de arquivos continue utilizável no Windows.

Nomes de arquivo enviados que correspondem a `.upload-*.part` são rejeitados porque esse padrão é reservado para arquivos temporários de staging. Renomeie um arquivo assim antes de enviá-lo. A restrição inclui aliases do Windows com pontos ou espaços no final e variações de maiúsculas/minúsculas, como `.upload-notes.part.`, `.upload-notes.part ` e `.UPLOAD-NOTES.PART`, em qualquer host. A verificação HTTP reconhece tanto `/` quanto `\` como separadores de caminho, inclusive no Linux, ao extrair o basename. O endpoint retorna `400` com uma dica de renomeação antes de publicar qualquer arquivo de um lote que contenha um nome reservado, então o chat reporta o erro de upload em vez de continuar sem o anexo. O SDK valida os nomes de arquivo do lote inteiro antes de copiar qualquer arquivo. Novos nomes de documento de projeto seguem a mesma restrição, sejam herdados da origem ou informados explicitamente no upload ou na promoção para a estante; um documento mais antigo da estante com nome reservado continua disponível para download, mas não pode ser anexado diretamente. Baixe, renomeie e envie para a thread. Essa mudança não recupera nem migra uploads antigos de thread que já correspondam ao padrão de staging.

Essa é a diferença entre um chatbot com acesso a ferramentas e um agente com um ambiente de execução de verdade.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

### Controle agêntico do navegador

A detecção automática de dependências do navegador aceita `name`, `group` e `use` em qualquer ordem dentro de uma entrada de ferramenta, com listas YAML indentadas ou sem indentação.

Ler uma página não é o mesmo que *usar* uma página. Ao lado das ferramentas somente leitura `web_fetch` e `web_capture`, o DeerFlow traz um grupo opcional de ferramentas de navegador agêntico que mantém uma sessão de navegador viva, por conversa, para que o agente consiga de fato operar uma página: navegar, ler os elementos interativos, clicar, digitar, enviar formulários e seguir fluxos de vários passos em sites carregados de JavaScript.

Cada ação devolve um snapshot novo dos elementos interativos da página, cada um endereçado por um número `[ref]` estável, de modo que o agente age sobre o que acabou de observar, em vez de adivinhar seletores. As URLs de saída passam por triagem de SSRF por padrão, e as conexões TCP do navegador passam por um proxy local que fixa cada uma nos endereços já triados, então uma resposta DNS que mude depois da verificação não consegue redirecioná-las para um host privado (o UDP do WebRTC não é coberto). O recurso é baseado no Playwright e distribuído como um extra opcional, para manter a instalação básica enxuta:

```bash
cd backend
uv sync --extra browser
uv run playwright install chromium
```

Depois, descomente as entradas de ferramenta `group: browser` no `config.yaml` (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close`). O `make dev` / a inicialização do Docker detecta uma ferramenta `browser_navigate` habilitada e preserva o extra `browser` nos syncs de dependências. O Gateway falha na inicialização se o controle do navegador está configurado mas o Playwright está ausente, e `/api/features` oculta a interface do Browser a menos que o backend consiga de fato servi-la. Mantenha `headless: true` e `allow_private_addresses: false` para tudo o que não for debug local e confiável. Conectar-se a um Chrome existente com `cdp_url` não consegue aplicar o guard de SSRF do DeerFlow para sub-recursos/redirecionamentos e, por isso, fecha em modo seguro, a menos que `allow_unguarded_cdp: true` reconheça esse risco explicitamente; use isso apenas com um navegador local confiável. As sessões de navegador são locais ao processo; mantenha o Gateway com um único processo worker enquanto esse grupo de ferramentas estiver habilitado, porque o dispatch comum de workers do uvicorn não oferece afinidade de thread. Isso significa `GATEWAY_WORKERS=1` e, nas inicializações que não passam nenhuma contagem de workers ao uvicorn (`backend/Dockerfile`, `scripts/serve.sh`), também `WEB_CONCURRENCY` não definido ou igual a `1`, já que o uvicorn tira dele a contagem de processos.

Chats existentes de Custom Agent que não sejam mock expõem os mesmos controles do Browser Live quando o controle do navegador está disponível e o agente deixa `tool_groups` sem restrição ou inclui o grupo `browser`. Uma allowlist explícita de grupos de ferramentas sem `browser` mantém esses controles ocultos.

O cliente Browser Live do workspace negocia frames JPEG binários via WebSocket, mantém apenas o frame pendente mais recente por atualização de tela e revoga as object URLs substituídas. As mensagens de controle do Gateway continuam em JSON, e clientes que não pedem a capacidade binária mantêm o protocolo legado de frames em JSON/base64.

### Engenharia de contexto

**Contexto isolado de sub-agent**: cada sub-agent roda em seu próprio contexto isolado. Isso significa que o sub-agent não enxerga o contexto do agente principal nem o de outros sub-agents. É importante para que ele consiga se concentrar na tarefa em mãos, sem se distrair com o contexto do agente principal ou de outros sub-agents.

**Sumarização**: dentro de uma sessão, o DeerFlow gerencia o contexto de forma agressiva: resume subtarefas concluídas, descarrega resultados intermediários no sistema de arquivos e comprime o que deixou de ser relevante no momento. Isso permite que ele continue afiado em tarefas longas, de vários passos, sem estourar a janela de contexto.

**Recuperação estrita de tool calls**: quando um provedor ou middleware interrompe um loop de tool calls, o DeerFlow agora remove os metadados brutos de tool call do nível do provedor nas mensagens de assistant com parada forçada e injeta resultados de ferramenta de placeholder para as chamadas pendentes antes da próxima invocação do modelo. Isso evita que modelos de reasoning compatíveis com OpenAI, que validam estritamente as sequências de `tool_call_id`, falhem com erros de histórico malformado.

**Conclusão visível de runs com ferramentas**: em turnos interativos, o DeerFlow tenta de novo, uma vez, uma resposta final vazia depois das ferramentas, e então mostra um erro visível em vez de reportar um run bem-sucedido em silêncio.

**Histórico de runs**: uma entrada de usuário só com imagem é registrada uma vez por run, mesmo quando o agente faz várias chamadas ao modelo. O conteúdo de mídia dela fica no histórico sem exigir um resumo em texto.

### Leitura de uma conversa referenciada

Quem chama a API do Gateway pode optar por `read_conversation` e enviar uma lista `conversation_references` junto com um run. O lead agent pode então ler páginas limitadas do texto visível atual dessas conversas que pertencem ao usuário. A permissão de leitura expira com o run, e texto em mensagens antigas não concede acesso. O texto que o agente já leu fica na conversa de destino depois que o acesso expira ou a origem é excluída. Uma mensagem longa demais para uma única leitura traz uma continuação, então o agente pode ler o restante; ele só pede a parte que falta se essa leitura estiver indisponível. Clientes de SDK que não conseguem adicionar campos de nível superior à requisição podem enviar a mesma lista como `context.conversation_references`, e `GET /api/features` informa se a ferramenta está habilitada. Quando está, o composer web mostra um botão "Reference a conversation" ao lado do botão de anexo: escolha até três das suas conversas recentes, e elas são anexadas apenas à próxima mensagem, exibidas como chips no composer e na transcrição. Não há busca automática no histórico. Veja a [configuração](backend/docs/CONFIGURATION.md#reading-referenced-conversations) e o [contrato da requisição](backend/docs/API.md#referencing-a-previous-conversation).

### Notas da tarefa atual

Habilite [notas de task e recall de histórico](docs/task-continuity.md) com `task_continuity.enabled: true`. Uma task pode manter até oito notas. Adições paralelas além dos slots restantes retornam `note_capacity`, preservando as notas existentes. Com a resolução de handles de artifact habilitada, a capacidade conta as chaves resolvidas; aliases da mesma nota compartilham um slot. Argumentos irmãos malformados, que não são dict, não consomem slots nem atrapalham chamadas válidas de nota. Notas com chaves inválidas, conteúdo acima de 750 caracteres, mais de quatro fontes ou IDs de fonte malformados também não reservam slot. Chaves existentes ainda podem ser substituídas ou excluídas. Slots liberados por exclusões irmãs ou por falhas de runtime (como fontes indisponíveis ou negação por política) ficam disponíveis no lote seguinte, quando as adições rejeitadas podem ser tentadas de novo.

### Memória de longo prazo

O [benchmark de isolamento de escopo do DeerMem](backend/scripts/benchmark/deermem_scope_isolation/README.md), que é opt-in, verifica a segurança semântica entre fatos e resumos, e o roteamento de fatos entre usuários e agentes. Tentativas de extração que falham são erros de execução que podem ser tentados de novo, não aprovações de segurança.

No DeerMem, `memory.backend_config.storage_class: markdown` ativa leituras tolerantes de resumo, mantendo as escritas em JSON e a interface existente. Um `memory.json` editado à mão pode conter seu objeto JSON dentro de um bloco cercado `memory-json`; crases embutidas e notas cercadas posteriores são suportadas. Texto de resumo que não pode ser interpretado é movido para `memory.json.corrupt-<timestamp>`, para recuperação, antes da reconstrução. O `storage_path` precisa apontar para o diretório raiz dos dados, não para um arquivo JSON existente.

O shutdown do Gateway drena as atualizações de memória antes de fechar o backend, mesmo quando o shutdown é cancelado. Falhas de recarga da configuração são registradas em log sem abortar o encerramento do runtime. No Kubernetes, reserve em `terminationGracePeriodSeconds` tempo para todos os hooks de shutdown, a resolução de config/backend, `memory.shutdown_flush_timeout_seconds` e o fechamento do backend, mais uma margem de segurança. O timeout de flush não limita o `close()`: backends personalizados precisam fazer o close rápido ou limitado internamente, ou o shutdown pode esperar até o processo ser encerrado à força.

A maioria dos agentes esquece tudo no momento em que a conversa termina. O DeerFlow lembra.

O DeerMem pode, opcionalmente, suprimir fatos extraídos quase duplicados com `memory.backend_config.fact_dedup_enabled: true` e `fact_dedup_similarity_threshold` (padrão `0.7`, intervalo de `0.5` a `1.0`). Essa heurística local e determinística, baseada em palavras e bigramas CJK, compara fatos apenas dentro do mesmo usuário, agente e categoria; não é uma detecção de equivalência semântica. Ela mantém o ID, o texto e a hora de criação existentes, eleva a confiança ao máximo e só atualiza a fonte quando a confiança aumenta. Substituições por correção explícita e fatos propostos para remoção ficam protegidos da mesclagem de quase duplicados. Uma mesclagem não conta como confirmação do usuário. O gate vem desligado por padrão e não afeta atualizações direcionadas de fatos.

O DeerFlow também inclui um backend de memória opcional `openviking`. Ele usa o pacote oficial `langchain-openviking` para capturar turnos concluídos em Sessions estáveis do OpenViking e recuperar memória para injeção no prompt, mantendo o DeerMem como padrão. A integração inicial suporta um usuário do DeerFlow com uma chave de API USER do OpenViking vinculada à credencial, em `memory.mode: middleware`, e não herda cabeçalhos HTTP arbitrários do `ovcli.conf`. Veja em [OpenViking memory backend](docs/OPENVIKING.md) a configuração, o comportamento e os limites atuais.

Ao longo das sessões, o DeerFlow constrói uma memória persistente do seu perfil, das suas preferências e do conhecimento acumulado. Quanto mais você usa, melhor ele conhece você: seu estilo de escrita, sua stack técnica, seus fluxos recorrentes. A memória fica armazenada localmente e sob o seu controle.

O DeerMem continua sendo o backend local padrão. Também há um backend `mem0`, opt-in, para a API hospedada da mem0 Platform ou para servidores self-hosted compatíveis com essa API. A `base_url` dele, que carrega token, precisa usar HTTPS por padrão; HTTP em texto puro exige um opt-in explícito para desenvolvimento local. Veja o [guia do backend mem0](backend/packages/harness/deerflow/agents/memory/backends/mem0/README.md).

Há um backend `honcho`, opt-in, para o Honcho self-hosted ou hospedado (API v3). Ele constrói a memória de modelo de usuário (preferências de longo prazo e uma representação de trabalho entre sessões) no lado do servidor do Honcho, então o backend não faz chamadas de LLM localmente. Cada usuário recebe um workspace isolado derivado do `user_id`; um id de usuário ausente fecha em modo seguro em vez de cair em um workspace compartilhado. O CRUD de fatos e a edição de fatos pela página Settings não estão disponíveis nesse backend. Veja o [guia do backend Honcho](backend/packages/harness/deerflow/agents/memory/backends/honcho/README.md).

As atualizações de memória agora pulam entradas de fato duplicadas no momento da aplicação, então preferências e contexto repetidos não se acumulam sem fim entre sessões.
Arquivos de memória legados são normalizados na leitura ou na importação, incluindo os metadados de fato recuperáveis, para que dados locais antigos continuem utilizáveis à medida que o schema evolui. A normalização no frontend e no backend usa confiança `0.5` quando ela está ausente ou é inválida, define fontes em branco como `unknown` e remove espaços das pontas do conteúdo do fato.

No modo `middleware` padrão do DeerMem, a extração automática agora classifica cada fato proposto por escopo, durabilidade e autoridade antes de um gate de escrita determinístico aceitá-lo. Só são armazenados fatos duráveis e descritivos, no nível do usuário; restrições da thread atual ou do projeto e permissões de ação pontuais ficam no estado da conversa. Resumos globais do usuário exigem tanto escopo de usuário quanto autoridade descritiva, as remoções por contradição passam pelo gate de escopo, e uma remoção que depende de substituição só é aplicada quando a substituição de fato sobrevive à validação e ao armazenamento. Esses rótulos de classificação são metadados só da extração, não acrescentam nenhuma chamada extra de LLM e não são gravados nos arquivos de fato. As ferramentas explícitas de CRUD em `memory.mode: tool` continuam sendo um caminho separado, dirigido pelo modelo. Implantações que sobrescrevem os prompts do DeerMem que acompanham o projeto via `memory.backend_config.prompts_dir` precisam adicionar os novos campos de classificação aos templates personalizados (os formatos de fato/resumo/remoção do `memory_update` e o schema de fato consolidado do `consolidation`): o gate de escrita fecha em modo seguro, então um template não migrado interrompe toda escrita de fato, resumo e remoção originada na extração, o que só aparece nas métricas `rejected_by_scope_gate` e no aviso de alta taxa de rejeição.

Quando um escopo de fatos atinge `max_facts`, o DeerMem ainda usa por padrão a ordem histórica de descarte baseada só em confiança. Operadores podem optar por `memory.backend_config.fact_eviction_policy: hybrid-v1`, que combina confiança limitada (65%), frescor de confirmação explícita (25%) e calor de acesso guiado por consultas (10%). Os metadados de sinal híbrido só são coletados enquanto o hybrid-v1 ou o modo shadow está habilitado. A confirmação explícita é devolvida como `factsToReinforce` pela chamada de LLM de atualização de memória já existente e só é aceita quando o processamento determinístico das mensagens também detecta um sinal de reforço do usuário; ela também zera o relógio de revisão de obsolescência do fato. Esse gate determinístico opera no nível do lote: ele estabelece apenas que uma mensagem humana entre as últimas seis mensagens filtradas do lote de extração atual correspondeu a um padrão de reforço. O ID em `factsToReinforce`, escolhido pelo LLM, fornece o vínculo com o fato; o DeerMem não verifica de forma independente uma correspondência entre sinal e fato. Extração repetida ou injeção automática nunca confirmam um fato. Prompts personalizados de `memory_update` devem adicionar o array opcional `factsToReinforce` para participar do frescor de confirmação. O calor de acesso fica em um sidecar separado, com decaimento, e só aumenta quando o `memory_search` realmente devolve o fato, então as leituras não reescrevem o Markdown canônico nem o `updatedAt` dele. O modo híbrido também reserva um mínimo limitado de slots de correção (10% do teto, no máximo 10; slots não usados voltam à competição normal). A exclusão por capacidade continua física, mas uma auditoria limitada, só de metadados, registra IDs de fato, categorias, scores da política e motivos, sem copiar o conteúdo do fato. `fact_eviction_shadow_enabled: true` avalia o hybrid-v1 ao lado da política padrão sem mudar a retenção real. Esse recurso não adiciona nenhuma invocação de LLM e pode ser revertido selecionando `confidence`.

A memória em arquivos agora separa o contexto global do usuário dos fatos de agente. Cada usuário tem um `memory.json` que contém apenas os resumos `user` e `history`, independentes de projeto; cada fato é um arquivo Markdown canônico abaixo de `agents/{agent_name}/facts/`. As chamadas existentes de middleware do lead agent, API, Settings, importação/exportação e cliente embutido que omitem `agent_name` são resolvidas dentro do DeerMem para o bucket reservado `__default__`. Esse bucket fica fora da gramática válida de nomes de agente personalizado, então um agente personalizado real chamado `lead-agent` tem um repositório de fatos separado, e excluir um agente personalizado não apaga um diretório só de memória, sem `config.yaml`. Os identificadores públicos de agente não diferenciam maiúsculas de minúsculas e são canonizados em minúsculas. Os leitores de runtime/API continuam recebendo um array `facts` de compatibilidade para o agente selecionado/padrão, então o frontend não lê fatos de agente do `memory.json`; os metadados estruturados `source` do Markdown são projetados para o campo string histórico na fronteira do MemoryManager. Um Clear All sem escopo primeiro migra os fatos de JSONs legados por agente ainda não lidos, sem adotar os resumos deles, que logo serão limpos, e depois remove os resumos compartilhados e os fatos de todos os buckets de agente, preservando os arquivos de configuração dos agentes, para que uma leitura posterior não ressuscite fatos legados pulados; uma limpeza com escopo explícito de agente remove apenas os fatos desse agente. Na primeira leitura normal, fatos antigos embutidos no JSON do usuário são migrados automaticamente para `__default__`; fatos gravados no bucket implícito anterior `lead-agent` também são movidos quando esse diretório não é um agente personalizado real. A migração e as escritas normais só notificam o adaptador de retrieval configurado depois que os locks de armazenamento durável são liberados. O DeerMem usa por padrão um adaptador SQLite FTS5/BM25 ciente de escopo, guarda em `.retrieval/` apenas dados de índice derivados que podem ser reconstruídos, e os reconstrói em background durante a inicialização do Gateway ou sob demanda na primeira busca com escopo. Um índice derivado corrompido é recriado automaticamente. Defina `memory.backend_config.retrieval_adapter` como string vazia para desabilitá-lo e usar o fallback local por substring. A tokenização de chinês é opcional; instale o extra `memory-zh` do backend (`uv sync --extra memory-zh`) para busca por subfrases com apoio do jieba. Escritas com journal, um lock compartilhado por usuário e revisões otimistas da memória do usuário evitam atualizações perdidas em silêncio.

Defina `memory.backend_config.retrieval_relevance_enabled: true` para ativar o ranqueamento determinístico por relevância/confiança e a injeção ciente da consulta. Isso **ignora o `retrieval_adapter` na busca**, incluindo o FTS5/BM25 padrão e adaptadores personalizados; a indexação continua configurada. `retrieval_relevance_weight` controla a mistura, e `retrieval_diversity_weight` habilita penalidades para quase duplicados (padrão 0). A pontuação usa no máximo os primeiros 4096 caracteres e 128 tokens por consulta/fato. A busca diversifica só até `top_k`; a injeção diversifica os fatos garantidos e os regulares de forma independente, até os orçamentos de tokens de cada grupo serem atingidos. Deixe o recurso desabilitado para manter o comportamento atual de retrieval e injeção.

A relevância lexical mede a cobertura, ponderada por IDF, dos termos distintos da consulta, então correspondências parciais repetidas não empatam com uma correspondência completa só por saturar o score. Correspondências por prefixo exigem que um token completo seja prefixo do outro, e não apenas quatro caracteres em comum. Em uploads, a injeção ciente da consulta usa o pedido preservado do usuário, e não as descrições de arquivo prefixadas; mensagens só com anexo mantêm a injeção sem consulta. Backends de memória personalizados mais antigos podem manter a assinatura atual de `get_context`: a injeção no prompt e o wrapper assíncrono herdado só passam `query` quando esse callable suporta o argumento nomeado e a dica não é `None`. A busca e a injeção automática usam a mesma ponderação por IDF para o mesmo escopo de candidatos de usuário/agente. A busca filtrada por categoria e os orçamentos de tokens separados da injeção, para garantidos e regulares, ainda podem levar a seleções finais diferentes.

A injeção de memória segue o modo de operação configurado. No modo `middleware`, o DeerMem injeta os resumos globais do usuário e os fatos do agente selecionado. As conversas de bootstrap de agentes personalizados também usam o bucket de fatos desse agente, então os detalhes da configuração não vazam para a memória do agente padrão. No modo `tool`, o bloco automático `<memory>` contém apenas os resumos globais `user` e `history`; os fatos de agente são recuperados explicitamente por `memory_search`, o que evita contexto de fatos duplicado entre o automático e o devolvido pela ferramenta. Definir `memory.injection_enabled: false` continua desabilitando o bloco inteiro em qualquer um dos modos.

Um Custom Agent individual pode optar por ficar sem memória sem mudar a configuração global. Adicione `memory_enabled: false` ao `users/{user_id}/agents/{name}/config.yaml` desse agente. O agente continua recebendo o lembrete da data atual, mas o DeerFlow não injeta memória recuperada, não enfileira atualizações de memória passivas ou motivadas por sumarização (incluindo o `/compact` manual), não expõe ferramentas de memória nem adiciona instruções de ferramentas de memória para esse agente. Se um agente existente é desligado, o bloco de memória injetado antes é removido do estado de checkpoint antes da próxima chamada ao modelo, enquanto o lembrete de data e a conversa permanecem. Omitir o campo (ou defini-lo como `true`) preserva o comportamento global atual de `memory`.

As operações de repositório sobre um único fato são genuinamente incrementais: um upsert/delete lê, registra em journal, grava e reindexa apenas os arquivos de fato endereçados, e devolve um delta incompleto explícito, em vez de um documento completo falso que dependa de cache. Os conjuntos de mudanças de resumo mesclam as chaves filhas `user`/`history` fornecidas por cima das seções persistidas, para que uma atualização parcial não apague irmãs omitidas; importações completas normalizam as duas seções para o schema de compatibilidade completo antes de aplicar os valores de substituição. As importações rejeitam listas de fatos malformadas ou conteúdo em branco/que não é texto com HTTP 400 antes de alterar a memória armazenada; metadados legados recuperáveis continuam recebendo valores padrão. Uma lista de fatos vazia e explícita continua sendo uma limpeza intencional. Os métodos de compatibilidade do Manager/API só materializam um documento completo novo quando o contrato público de resposta exige. As operações pontuais no nível do fato usam revisões esperadas separadas para a memória do usuário e para o fato, e podem fazer rebase explicitamente quando todas as precondições dos fatos endereçados ainda valem. Operações derivadas de snapshot, como limpeza com escopo, criação com teto, consolidação e trimming, nunca reaplicam conjuntos de delete/trim defasados: um conflito de manifest recarrega o documento completo e recalcula a operação, com nova tentativa limitada. Os caminhos de fato usam os dois primeiros caracteres hexadecimais de `SHA-256(fact_id)`, para que os IDs `fact_*` gerados se distribuam entre shards. O token de cache combina o mtime em nanossegundos, o tamanho e a revisão persistida do JSON compartilhado; isso evita que escritas de mesmo tamanho com mtime de baixa resolução devolvam dados defasados, sem precisar varrer os arquivos de fato. Edições diretas de Markdown por fora exigem um reload explícito. Conflitos e corrupção específicos do armazenamento são traduzidos na fronteira do MemoryManager; o Gateway devolve conflito como HTTP 409 e um erro de corrupção estável e sem dados sensíveis como HTTP 500. O `save()` de documento completo continua sendo uma API de compatibilidade e calcula um diff antes de gravar; `facts` malformado ou ausente não consegue mais apagar em silêncio os arquivos Markdown de um agente. A migração legada preserva `user`/`history` não vazios antes de excluir o `memory.json` de um agente; resumos conflitantes mantêm o arquivo legado e falham de forma ruidosa, em vez de escolher um vencedor.

Os fatos legados no `memory.json` migram automaticamente para o bucket Markdown reservado `__default__` na primeira leitura normal de memória do usuário. Operadores que preferem auditar ou concluir a migração antes de servir tráfego podem rodar a CLI opcional e idempotente a partir de `backend/`:

```bash
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
# A custom DeerMem root or original non-directory-safe identity can be explicit:
PYTHONPATH=. python scripts/migrate_memory_markdown.py --storage-path /path/to/deerflow-home --user-id 'test@example.com'
```

A migração de armazenamento da v1 para a v2 é de mão única para uma aplicação em execução: o código anterior ao PR não lê fatos em Markdown. Antes de atualizar uma implantação persistente, pare o DeerFlow e faça um snapshot do sistema de arquivos ou um backup completo da raiz de armazenamento de memória configurada. A migração também mantém de forma durável cada origem JSON destrutiva ao lado do caminho original, como `{manifest_filename}.v1.bak`, antes de gravar os dados v2; um backup existente que não corresponda ou uma falha ao gravar o backup interrompe a migração sem modificar a origem v1. Esse backup local preserva os dados anteriores à migração, mas não substitui um snapshot completo e não contém fatos criados depois da atualização.

`--user-id` pode ser repetido. `--all-users` descobre os buckets existentes, com nomes seguros para diretório, abaixo da raiz de armazenamento selecionada; integrações standalone que passavam IDs brutos com caracteres como `@` devem usar o valor original com `--user-id`. A migração de um usuário que falha é reportada sem esconder o restante da auditoria, e o comando sai com código diferente de zero quando algum usuário falha. O caminho automático na primeira leitura continua habilitado, então rodar essa CLI não é necessário para a inicialização.

## Modelos recomendados

O DeerFlow é agnóstico a modelo: funciona com qualquer LLM que implemente a API compatível com OpenAI. Dito isso, ele rende mais com modelos que oferecem:

- **Janelas de contexto longas** (100k+ tokens), para pesquisa profunda e tarefas de vários passos
- **Capacidade de reasoning**, para planejamento adaptativo e decomposição complexa
- **Entradas multimodais**, para compreensão de imagem e de vídeo
- **Bom uso de ferramentas**, para function calling confiável e saídas estruturadas

## Cliente Python embutido

Em `DeerFlowClient(agent_name="researcher")`, a seleção `mcp_plugins` do agente nomeado vale tanto para o lead agent quanto para as delegações `task` / `batch_task` dele: `null` herda todos os plugins MCP habilitados, `[]` não seleciona nenhum, e IDs de instalação selecionam apenas esses plugins. Chame `client.reset_agent()` depois de editar a configuração salva do agente para atualizar a seleção.

O `DeerFlowClient.stream()` inclui `summary_text` em cada evento `values`. É o resumo atual do contexto compactado, ou `None` quando não existe. Os consumidores podem registrar as mudanças sem ler os internos do checkpoint; snapshots repetidos podem trazer o mesmo resumo, e um snapshot inicial pode já conter um resumo de um turno anterior.

O DeerFlow pode ser usado como uma biblioteca Python embutida, sem rodar os serviços HTTP completos. O `DeerFlowClient` dá acesso direto, em processo, a todas as capacidades do agente e do Gateway, devolvendo os mesmos schemas de resposta da API HTTP do Gateway. O Gateway HTTP também expõe `DELETE /api/threads/{thread_id}` para remover os dados locais de thread gerenciados pelo DeerFlow depois que a thread do LangGraph em si foi excluída:

Os IDs de thread podem ser fornecidos por quem chama e não precisam ser UUIDs. IDs explícitos precisam ter de 1 a 64 letras ASCII, dígitos, hifens ou underscores (`^[A-Za-z0-9_-]{1,64}$`). O DeerFlow só gera um UUID quando `thread_id` é omitido ou `None`; uma string vazia fornecida explicitamente é inválida. Threads existentes endereçáveis por rota, criadas sob regras antigas e mais frouxas, continuam podendo ser lidas e excluídas, mas não podem iniciar novos runs nem criar novo estado de sistema de arquivos ou de sandbox. A exclusão legada pula a limpeza de caminhos locais quando o ID não é seguro pelo contrato canônico. Em threads legadas canônicas cuja conversa existe apenas em checkpoints do LangGraph, o DeerFlow semeia um feed vazio de eventos de run a partir do checkpoint antes do primeiro novo run, para que `/messages/page` mantenha tanto os turnos antigos quanto os novos.

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])
    elif event.type == "messages-tuple" and event.data.get("type") == "tool" and "artifact" in event.data:
        # Structured tool artifacts (for example, ask_clarification cards)
        # are preserved when the ToolMessage provides one.
        print(event.data["artifact"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
client.set_goal("thread-1", "finish the implementation and make all tests pass")
client.get_goal("thread-1")       # {"goal": {...}} or {"goal": None}
client.clear_goal("thread-1")
```

Ao continuar uma thread, `values` ainda contém o estado completo da conversa, enquanto `messages-tuple` e `end.usage` cobrem apenas o turno atual.

O Gateway HTTP aceita os modos de stream `values`, `messages-tuple`, `updates`, `debug`, `tasks`, `checkpoints` e `custom`. Modos não suportados, como `messages` e `events`, opções de run não padrão e não suportadas, como webhooks, execução adiada ou `multitask_strategy="enqueue"`, e opções de SDK não declaradas, como overrides de durabilidade de checkpoint, retornam `422` antes da execução, em vez de serem ignorados ou rebaixados em silêncio.

Todos os métodos que retornam dict são validados no CI contra os modelos Pydantic de resposta do Gateway (`TestGatewayConformance`), o que garante que o cliente embutido fique em sincronia com os schemas da API HTTP. Veja a documentação completa da API em `backend/packages/harness/deerflow/client.py`.

## Projetos

Os projetos agrupam conversas relacionadas sob um nome, instruções e uma estante de documentos compartilhados.

Uma conversa entra em um projeto na criação (quando há um projeto selecionado) ou depois, pelo menu de mover. Os runs nunca alteram essa associação: enviar uma mensagem não atribui nem reatribui uma conversa. Mover uma conversa para fora de um projeto a deixa sem atribuição até que seja movida de novo explicitamente.

Mover uma conversa atualiza a afiliação no cabeçalho dela e também as listas de projetos, inclusive quando uma requisição de metadados mais antiga ainda está em andamento.

Os projetos exigem as tabelas e colunas atuais do banco de dados. Um banco marcado como `0019_thread_incarnations` pelo rollout mais antigo, baseado no 0018, é rejeitado na inicialização se o schema de projetos estiver ausente. Siga o [procedimento de recuperação offline do banco de dados](docs/database-forward-revision-recovery.md) antes de iniciar este build contra esse banco.

### Instruções do projeto

Cada projeto guarda instruções em formato livre (contexto, convenções e restrições que valem para todas as conversas do projeto), editáveis na aba Instructions da página do projeto, com um contador de bytes ao vivo. Quando um run começa em uma thread membro, o Gateway fixa uma vez o estado atual do projeto e renderiza as instruções como um bloco `<project>` limitado e com escopo de requisição, só para aquele run: o bloco nunca entra no system prompt nem no histórico persistido, e cada novo run vê as últimas instruções salvas. As instruções têm teto de `projects.instructions_max_bytes` bytes UTF-8 (padrão 8192, intervalo de 256 a 262144); caracteres multibyte contam pelo tamanho em bytes UTF-8. Instruções acima do limite são rejeitadas com `422` na escrita e nunca são truncadas em silêncio.

### Estante de documentos

Cada projeto tem uma estante de documentos para os arquivos compartilhados pelo projeto inteiro, gerenciada na seção Documents da página do projeto:

- **Upload** de um arquivo (botão ou arrastar e soltar, um arquivo por requisição). Os limites de tamanho da estante reutilizam `uploads.max_file_size` (padrão 50 MiB); enviar de novo um conteúdo idêntico devolve a entrada existente em vez de criar uma duplicata.
- **List** das entradas, com nome, tamanho, hora de modificação e proveniência (enviado ou salvo a partir de uma conversa), com pré-visualização ou download de qualquer entrada.
- **Save to project** a partir de um arquivo de thread: o navegador somente leitura de arquivos de conversa, abaixo da estante, lista os uploads e outputs das threads membro, cada um com uma ação Save to project.
- **Attach to thread**: copia um arquivo da estante para os uploads de uma thread pelo pipeline normal de ingestão, para que a conversa possa trabalhar com ele diretamente.

Os runs em threads membro também recebem um índice `<documents>` limitado, renderizado a cada run a partir do snapshot fixado (com teto em `projects.shelf_index_max_entries` e `projects.shelf_index_max_bytes`), e o agente pode paginar a estante e ler documentos com as ferramentas `list_project_documents` e `read_project_document`.

### Semântica de leitura do arquivamento

Arquivar um projeto congela as escritas, mas mantém as leituras. As threads de um projeto arquivado continuam rodando e continuam recebendo as instruções do projeto e o índice da estante, e a estante segue totalmente legível: listagem, pré-visualização/download, o navegador de arquivos de conversa e o attach-to-thread continuam funcionando. Uploads, save-to-project e mover arquivos individuais da estante para a lixeira exigem um projeto ativo, e um documento na lixeira não pode ser restaurado para um projeto arquivado. Excluir um projeto arquivado continua permitido e move a estante inteira dele para a lixeira.

### Lixeira

Excluir um documento da estante o move para a lixeira em vez de apagá-lo: a entrada mantém seus bytes e um snapshot do projeto de origem por `projects.trash_retention_days` (padrão 30) antes que a varredura de retenção possa removê-la de forma permanente. A página `/workspace/trash`, acessível pela seção Documents da página do projeto e pelo cabeçalho Projects da barra lateral, lista os documentos na lixeira com o projeto de origem e a retenção restante, com as ações Restore e Delete permanently por entrada, além de uma ação Empty trash, que exclui de forma permanente todos os documentos da lixeira, imediatamente, e não depois da janela de retenção; a janela só limita quanto tempo uma entrada pode ficar ali antes de a varredura de retenção recuperá-la. Restore devolve o documento ao projeto de origem, ou a um projeto que você escolhe quando a origem não existe mais ou está arquivada; se o destino já tiver um arquivo ativo idêntico, as entradas são mescladas. Excluir um projeto move a estante inteira dele para a lixeira no mesmo passo.

## Tarefas agendadas

O DeerFlow agora inclui no workspace um MVP de tarefas agendadas como recurso de primeira classe.

Editar o título ou o prompt de uma tarefa única preserva a hora de execução original, incluindo os segundos e a ocorrência selecionada durante um recuo de relógio do horário de verão. Mudar a data, a hora ou o fuso horário recalcula a hora de execução. Trocar de tarefa durante a edição carrega o título, o prompt e o agendamento da própria tarefa selecionada.

Capacidades atuais do MVP:

- Gerenciar tarefas em `/workspace/scheduled-tasks`
- Os formulários de tarefa única rejeitam horários locais pulados por transições de horário de verão; selecione outro horário antes de criar ou salvar a tarefa.
- Escolher se cada tarefa agendada reutiliza uma thread e o histórico de conversa dela ou cria uma thread nova a cada execução
- Fixar cada tarefa em `lead_agent` (padrão) ou em um agente personalizado que o dono já tenha; nomes desconhecidos são rejeitados
- Enviar `assistant_id: null` em um PATCH de tarefa agendada devolve a tarefa para `lead_agent`; omitir `assistant_id` preserva o agente atual, inclusive quando esse agente personalizado já foi excluído
- Duplicar uma tarefa existente no formulário de criação, como rascunho editável, sem copiar o histórico de execuções
- Suporte a agendamentos `once`, `cron` e `interval`
- Editar ou duplicar uma tarefa de intervalo preserva a cadência salva até que o intervalo seja alterado explicitamente, incluindo intervalos abaixo de um minuto permitidos pela configuração do scheduler do operador
- Rodar as execuções agendadas em background como runs não interativos do DeerFlow (`ask_clarification` não é exposto ali)
- Persistir uma execução devida como `queued` quando a thread reutilizada ou o orçamento global de execução está ocupado e iniciá-la quando houver capacidade; as ocorrências na fila sobrevivem a reinícios do Gateway e falham depois de `scheduler.queue_timeout_seconds`
- Congelar a definição de uma tarefa enquanto uma ocorrência está `queued`, `launching` ou `running`, para que uma ocorrência durável não pegue em silêncio outro prompt, thread ou agendamento; passar uma tarefa para pausada ou excluí-la cancela uma ocorrência em espera, enquanto o trabalho em `launching`/`running` precisa terminar antes que essas mutações sejam tentadas de novo, e um disparo manual explícito ainda pode esperar e rodar sem retomar um agendamento pausado
- Pausar, retomar, disparar, inspecionar o histórico e excluir tarefas
- Buscar em títulos ou prompts de tarefas, em combinação com filtros de status/tipo e com o escopo da thread atual.
- Executar o trabalho agendado pelo ciclo de vida normal de runs do DeerFlow
- Com `channel_connections.enabled: true`, enviar um resumo às identidades de IM conectadas do dono da tarefa quando um run agendado termina como sucesso ou falha (outbox + worker de entrega). Tarefas com goal enviam, em vez disso, um aviso de goal não atingido para uma ocorrência `unmet`, além de um aviso de pausa automática quando três ocorrências não atingidas pausam a tarefa. O "run now" manual e as interrupções ficam em silêncio, assim como as ocorrências que terminam sem um run concluído (erro de lançamento, timeout de fila, recuperação após reinício). Indisponibilidades de canal/transporte deixam as entregas estacionadas sem esgotar as tentativas, por até cerca de um dia; rejeições da plataforma são tentadas de novo por aproximadamente 15 minutos antes de se fixarem como `failed`. Uma identidade que você desconecta enquanto uma entrega está em espera nunca recebe o envio: a linha é descartada como `failed`. O push proativo está implementado hoje para o WeCom; outros provedores conectados enfileiram, mas falham até ganharem um caminho `send_notification`.
- Navegar pelo histórico de execuções em páginas de 50; páginas mais antigas pausam a atualização automática, com um retorno explícito às execuções mais recentes. As contagens só aparecem depois de uma leitura bem-sucedida; carregamento e leituras com falha não são reportados como zero execuções.

**Filtrar o histórico de execuções pela API**

Para inspecionar falhas sem baixar todas as ocorrências bem-sucedidas, clientes autenticados com `threads:read` podem pedir `GET /api/scheduled-tasks/{task_id}/runs?status=failed&limit=50&offset=0` para uma tarefa que lhes pertence. O `status` opcional aceita `queued`, `launching`, `running`, `success`, `failed`, `skipped`, `interrupted` ou `unmet`; esses são status de ocorrência, então status de tarefa como `completed` são inválidos (422).

O filtro acontece antes da paginação. `limit` (de 1 a 200, padrão 50) e `offset` (não negativo, padrão 0) se aplicam aos registros correspondentes, ordenados por hora de criação e depois por ID, ambos em ordem decrescente. Omitir `status` preserva a resposta atual em array com o histórico misto; sem correspondências, o retorno é `[]`. A API não altera a execução das tarefas, e a interface de histórico do workspace continua sem filtro.

Limites atuais do MVP:

- Sem jobs de notificação só de texto
- Sem destinos de dispatch para canais ou GitHub (o push de resultado acima não é um destino de dispatch)

Habilite o polling em background com `config.yaml -> scheduler.enabled`. O disparo manual usa o mesmo recurso de tarefa agendada e o mesmo caminho de execução.

### Ciclo de vida, limites de segurança e condições de parada

- A página de tarefas e a API REST (`POST` / `PATCH /api/scheduled-tasks`) aceitam o mesmo goal por execução (`goal_objective`), limite de segurança (`max_runs`, `end_at`) e condição de parada (`stop_condition`) que uma conversa. Enviar `null` em um PATCH limpa qualquer um desses quatro campos; um `end_at` sem offset UTC é a hora local no fuso horário da tarefa.
- A condição de parada é a regra "pare quando …" do usuário. Ela fica em um campo próprio (migração `0031`), nunca dentro das instruções da tarefa. Só quando uma execução começa o DeerFlow a anexa à mensagem daquela execução e pede que ela chame `stop_scheduled_task` quando a regra for satisfeita. Com `scheduler.tool_enabled` ligado, toda execução agendada pode pausar o próprio agendamento, tenha a tarefa sido criada em um chat ou na página de tarefas; com ele desligado, a execução apenas informa que a regra foi satisfeita, sem ser instruída a chamar uma ferramenta que não tem.
- Tarefas com goal criadas na página de tarefas agora são avaliadas como as criadas em chat, e suas execuções também recebem as notas salvas e a referência à execução anterior.
- Retomar calcula a próxima execução a partir de agora, então uma pausa longa nunca gera uma execução de recuperação. Uma tarefa única cujo horário já passou devolve `422 once_time_passed` e precisa de um novo horário. Retomar uma tarefa ativa não muda nada; pausar uma tarefa encerrada devolve `409 task_finished`.
- `max_runs` é o total de execuções automáticas ao longo da vida da tarefa; execuções de teste nunca contam. Reativar uma tarefa cujo limite foi esgotado (Retomar, ou um PATCH que rearma o agendamento de uma tarefa encerrada) devolve `409 limits_exhausted`, a menos que a mesma requisição aumente `max_runs`, adie `end_at` ou remova o limite. `POST /api/scheduled-tasks/{task_id}/resume` aceita para isso um corpo opcional `{"max_runs": …, "end_at": …}` (`null` remove o limite; tarefas criadas em chat com frequência menor que uma hora precisam manter um). Um PATCH que só muda o limite de uma tarefa encerrada o salva e mantém a tarefa encerrada.
- Falhas na verificação do goal (o avaliador falhou ou a conversa mudou durante a verificação) não contam para a pausa automática após três falhas nem zeram a sequência. Mudar o goal, as instruções ou a condição de parada, ou adicionar uma nota, inicia uma nova contagem; Retomar a mantém.
- Enquanto o scheduler deste processo do Gateway não estiver rodando, criar uma tarefa (inclusive Duplicar) devolve `409 scheduler_not_running`, porque a tarefa nunca rodaria no horário. `GET /api/features` informa `scheduled_tasks.available`, `running`, `tool_enabled` e `min_interval_seconds`.
- Os erros de `/api/scheduled-tasks*` têm a forma `{"detail": {"code", "message", "params"}}`; veja [`backend/docs/API.md`](backend/docs/API.md#scheduled-tasks) e `contracts/scheduled_task_errors_contract.json`.

### Criar agendamentos em uma conversa

Defina `scheduler.enabled: true` e `scheduler.tool_enabled: true` e reinicie o Gateway. Um turno interativo autorizado pode usar `schedule_task` para criar, alterar, listar, pausar, retomar ou excluir tarefas, iniciar um teste ou salvar uma nota. Por exemplo: "Every weekday at 9:00, check release-checklist.md and tell me what is still unchecked; stop when everything is checked." No app web o resultado aparece como um card ao vivo com o agendamento, a condição de parada e botões, e o agente responde em uma ou duas frases; no IM e em outros turnos fora da web, o agente descreve em texto o agendamento, a próxima execução e a condição de parada.

- **Quais tarefas uma conversa gerencia.** As tarefas criadas nela e, numa conversa de execução (o chat em que uma execução agendada publicou o resultado), a tarefa a que essa execução pertence: "pause isto" ou "mude para as 10:00" também funcionam ali. Isso vale apenas para os turnos que você envia; uma execução agendada só pode pausar o próprio agendamento com `stop_scheduled_task`.
- **Alterações mantêm a tarefa.** Mudar o horário, as instruções, o goal, a condição de parada ou o limite de segurança é um `update` da mesma tarefa, então o ID e o histórico de execuções permanecem. `resume` retoma uma tarefa pausada ou encerrada sem execução de recuperação. Se o limite já foi usado, o agente pergunta se deve aumentar `max_runs`, adiar `end_at` ou remover o limite, e envia isso junto com a retomada.
- **Fuso horário.** Um fuso que você indicar tem prioridade. Caso contrário, uma tarefa nova usa o fuso do navegador que o app web envia com cada mensagem (`context.client_timezone`, lido só para isso), e o resultado informa qual fuso foi usado. Intervalos e horários únicos com deslocamento UTC não precisam de fuso; para um cron ou um horário local único sem fuso conhecido (por exemplo, vindo do IM), o agente pergunta. Alterações mantêm o fuso salvo; o fuso do navegador nunca altera uma tarefa existente.
- **Onde aparecem os resultados.** Cada execução publica o resultado em um chat novo próprio, com o título "{tarefa} · {hora local}", ou no chat de origem quando a tarefa roda nele. Nada mais é publicado de volta na conversa de origem. O chat da execução mostra as instruções da tarefa como um bloco recolhido "Instruções da tarefa" sob o cabeçalho da execução, em vez de uma longa mensagem do usuário.
- **Idioma.** O agente escreve o título, as instruções e a condição de parada no seu idioma, e as execuções agendadas respondem no idioma das instruções.

Novas tarefas usam por padrão uma conversa nova a cada ocorrência. Um `goal_objective` configurado vale só para aquela ocorrência: o sucesso não interrompe um agendamento recorrente. O agente em execução pode pedir `stop_scheduled_task` para o próprio agendamento quando a sua condição de parada for atingida; o pedido passa a valer durante a finalização terminal. `max_runs` conta apenas os lançamentos automáticos, e `end_at` define um prazo. Qualquer uma das condições de término tem precedência sobre um pedido de pausa. Agendamentos com frequência menor que uma hora criados pela ferramenta exigem uma condição de término; cada dono pode manter no máximo 20 tarefas vivas criadas pela ferramenta, incluindo as pausadas.

Uma ocorrência não atendida é registrada como `unmet`, diferente de uma falha de execução. Três ocorrências automáticas não atendidas e elegíveis pausam uma tarefa recorrente. Um sucesso aceito zera a sequência, inclusive um sucesso apoiado em suposições declaradas; testes manuais, interrupção, falha de execução, espera externa e falhas na verificação do goal não a fazem avançar. Retomar mantém a sequência, então outra ocorrência não atendida elegível pode pausar a tarefa de novo. Os vínculos de notificação existentes recebem os avisos de goal não atendido e de pausa automática pelo mesmo outbox durável; os testes manuais ficam em silêncio.

Você pode pedir ao agente, numa conversa que gerencia a tarefa, que salve uma nota explícita para execuções futuras (no máximo 10 notas de 500 caracteres). Execuções recorrentes novas podem ler a ocorrência executada anterior pelo `read_conversation`, que é opt-in, com as mesmas verificações de dono e de permissão de leitura. Isso oferece uma referência à fonte, não um resumo automático nem uma postagem de volta no chat de origem.

Para um teste, peça diretamente, por exemplo "Run it now", "OK, run it now" ou "先跑一次吧"; no app web, o botão **Run once now** do card faz o mesmo. O host aceita um conjunto limitado de pedidos de execução direta em inglês/chinês vindos do turno atual do usuário, opcionalmente depois de uma confirmação curta como "Sure," ou "好的，". Um simples "yes" ou "好", menções à tarefa e pedidos citados ou condicionais não iniciam uma execução paga. Se uma execução já estiver aguardando para começar, nenhum teste extra é adicionado e o agente avisa. Um teste não conta para `max_runs`.

Uma ocorrência de goal pode usar até nove turnos do agente, com uma requisição ao avaliador depois de cada um. As requisições ao avaliador e os tokens reportados pelo provedor entram no uso do run; quando o uso está ausente, a estimativa de custo correspondente fica desconhecida. O `token_budget` limita o grafo principal e é verificado depois das chamadas ao modelo; o uso do avaliador é adicional, então não se trata de um limite estrito do run inteiro nem em dólares.

**Atualização da avaliação de goal:** os runs de goal agendados, de webhook e autônomos existentes podem aceitar suposições declaradas, reversíveis e de baixo risco, e registrar `relied_on_assumption` no veredicto. A avaliação de goal interativa continua estrita. Essa política também se aplica quando as ferramentas de agendamento em conversa estão desabilitadas; ela não autoriza ações sensíveis nem substitui a autorização do usuário.


Os runs agendados usam `scheduler.recursion_limit` do `config.yaml` (padrão `1000`, igual ao orçamento interativo da web UI). Valores acima de `max_recursion_limit` são limitados a ele. Esse campo é lido no dispatch, então o próximo run agendado o pega sem reiniciar o Gateway.

O scheduler em background é de instância única por padrão. Em uma implantação com vários pods, defina `scheduler.multi_instance: true` e use Postgres compartilhado, `run_ownership.heartbeat_enabled: true` e `run_events.backend: db`; a inicialização e a recuperação periódica passam então a preservar os runs de peers ativos, devolver à fila de forma atômica os claims de lançamento expirados, assumir apenas leases de run expirados e barrar escritas de lançamento defasadas. `max_concurrent_runs` é um teto global compartilhado entre os Pods para ocorrências em `launching`/`running`; as linhas `queued` em espera não o consomem. Sem essas configurações, habilite o scheduler em exatamente um pod do Gateway. Esses campos do scheduler só são lidos na inicialização; reinicie todos os Pods do Gateway juntos ao alterá-los.

### Pré-visualizar ocorrências de cron pela API

Clientes autenticados com `threads:read` podem chamar `POST /api/scheduled-tasks/preview-cron` antes de criar uma tarefa:

```json
{"cron":"0 9 * * 1-5","timezone":"Asia/Shanghai","count":3,"start_at":"2026-09-12T00:00:00Z"}
```

A resposta contém `cron` e `timezone` normalizados, o `start_at` efetivo em UTC e `occurrences` com `run_at` em UTC e `local_time` com offset. Neste exemplo, a primeira ocorrência é `2026-09-14T01:00:00Z` / `2026-09-14T09:00:00+08:00`.

`count` é um inteiro de 1 a 10 (padrão 5). `start_at` precisa incluir um fuso horário; omita-o para capturar a hora do servidor uma única vez. As expressões cron usam a sintaxe de cinco campos do scheduler (máximo de 256 caracteres); nomes de fuso horário têm no máximo 128 caracteres. Entradas inválidas ou agendamentos sem as ocorrências futuras pedidas retornam 422. A pré-visualização compartilha o comportamento de horário de verão do scheduler, não cria tarefa, thread ou run e não reserva execução. É uma capacidade da API; o formulário do workspace ainda não exibe essas ocorrências.

### Notas de atualização

- A ordenação de ocorrências vale para as linhas admitidas por instâncias atualizadas do Gateway, que projetam na tarefa pai apenas ocorrências sequenciadas e adiam a recuperação enquanto alguma ocorrência ainda está viva, seja qual for a instância que a admitiu; uma tarefa cujo histórico é inteiramente sem sequência mantém a ordenação anterior por timestamp até a primeira admissão sequenciada. Durante um rolling upgrade, as linhas admitidas por instâncias anteriores à atualização são projetadas por essas próprias instâncias, como antes, e as garantias de ordenação valem quando todos os escritores do Gateway rodam a versão atualizada. O histórico existente não é preenchido retroativamente; a atualização não reconstrói a ordem passada nem repara contagens históricas.
- Antes de atualizar uma implantação com `GATEWAY_WORKERS > 1` e `scheduler.enabled: true`, mantenha o scheduler em exatamente um worker do Gateway ou configure `scheduler.multi_instance: true` com Postgres compartilhado, `run_ownership.heartbeat_enabled: true` e `run_events.backend: db`. O Gateway atualizado rejeita a combinação insegura na inicialização, em vez de subir em silêncio.
- No modo de várias instâncias, `scheduler.max_concurrent_runs` é um teto de execução do cluster inteiro, não por Pod. Ele inclui as ocorrências agendadas em `launching` e `running`, então a capacidade não se multiplica pelo número de réplicas; as linhas duráveis em espera ficam fora do teto.
- `scheduler.multi_instance` e as configurações relacionadas de scheduler, ownership e eventos de run só são lidas na inicialização. Aplique as mudanças com um reinício coordenado de todos os Pods do Gateway; alterar só o ConfigMap não ativa a recuperação de várias instâncias.

## Workbench de terminal (TUI)

O `deerflow` é um workbench nativo de terminal para quem vive no shell. Ele roda **embutido** sobre o `DeerFlowClient`, sem precisar de Gateway, frontend, nginx ou Docker, e respeita as mesmas configurações de `config.yaml`, checkpointer, skills, memória, MCP e sandbox do restante do DeerFlow.

Chamadas MCP stdio síncronas em paralelo usam sessões independentes, cada uma em seu próprio event loop. Elas não cancelam as conexões umas das outras, mas não compartilham estado do lado do servidor; reutilizar uma sessão exige o mesmo loop. Veja os detalhes nas [notas de sessão MCP](backend/docs/MCP_SERVER.md). Event loops gerenciados manualmente precisam drenar os donos de sessão pendentes antes de fechar; o caminho normal com `asyncio.run()` faz isso automaticamente.

![DeerFlow TUI](docs/tui/tui-preview.svg)

```bash
uv pip install 'deerflow-harness[tui]'        # optional 'textual' dependency

deerflow                                      # launch the terminal UI (TTY required)
deerflow --tui-transparent                    # use the terminal's default background
deerflow --continue                           # resume the most recent thread
deerflow --resume THREAD                      # resume a thread by id
deerflow --print "summarize this repo"        # headless one-shot answer to stdout
deerflow --json  "hello"                       # headless newline-delimited StreamEvents; failure -> one {"type": "error"} record, exit 1
deerflow --recursion-limit 250 --print "task" # override the headless agent-loop limit
```

Em modo headless, `--print` e `--json` saem com status `1` quando o run falha, incluindo erros de provedor devolvidos como mensagens de fallback. O `--print` ainda escreve o texto de fallback no stdout; o `--json` acrescenta um registro terminal de erro.

Uma superfície de chat guiada pelo teclado, com transcrição em streaming (respostas renderizadas em Markdown), cards compactos de atividade de ferramentas, uma paleta de comandos com `/`, `/clear` que atua só na exibição, gerenciamento de goal com `/goal`, seletores `/model` e `/threads`, histórico de entrada, navegação na transcrição com PageUp/PageDown e interrupção com `Esc` / `Ctrl+C`. O composer preserva quebras de linha e indentação em código colado, stack traces e prompts de vários parágrafos; `Enter` envia o documento inteiro. As atualizações da transcrição preservam sua posição de leitura depois que você rola para cima e voltam a acompanhar a nova saída quando você retorna ao final. O `/clear` remove linhas da exibição atual do terminal sem excluir a thread nem a conversa persistida; `/new` e `/clear` pedem que você espere durante um run ativo, em vez de zerar o estado de exibição em andamento. As sessões abertas na TUI também aparecem na barra lateral da Web UI: ela grava no thread store compartilhado, sob o usuário padrão local, então terminal e web ficam em sincronia **sem rodar o Gateway**.

Durante um run ativo, `/resume`, `/threads` e `/switch` pedem que você espere antes de trocar de conversa. Uma referência inválida em `/resume` mostra um erro sem fechar a TUI nem mudar a conversa atual. Depois de uma interrupção e de uma troca de conversa, ações de stream atrasadas da thread anterior não conseguem alterar a exibição nem o estado de run da nova conversa.

Na última linha do composer, `Down` deixa intacto um rascunho não enviado, a menos que você esteja navegando pelo histórico de entrada; depois de recuperar um item do histórico, ele avança para restaurar o rascunho salvo.

Na primeira linha do composer, `Up` também deixa intactos o rascunho, o cursor e o histórico de undo quando não há histórico de entrada disponível. Recuperar um texto de histórico idêntico ou um rascunho salvo também preserva o cursor e o histórico de undo.

Veja o guia completo em [backend/docs/TUI.md](backend/docs/TUI.md).

## Documentação

- [Guia de contribuição](CONTRIBUTING.md) - Configuração do ambiente de desenvolvimento e fluxo de trabalho
- [Guia de configuração](backend/docs/CONFIGURATION.md) - Instruções de instalação e configuração
- [Visão geral da arquitetura](backend/CLAUDE.md) - Detalhes da arquitetura técnica
- [Arquitetura do backend](backend/README.md) - Arquitetura do backend e referência da API

## ⚠️ Aviso de segurança

### Implantação inadequada pode introduzir riscos de segurança

O DeerFlow tem capacidades centrais de alto privilégio, incluindo **execução de comandos do sistema, operações sobre recursos e invocação de lógica de negócio**, e foi projetado para ser, por padrão, **implantado em um ambiente local confiável (acessível apenas pela interface de loopback 127.0.0.1)**. Se você implantar o agente em ambientes não confiáveis, como redes locais (LAN), servidores de nuvem pública ou outros ambientes acessíveis por vários endpoints, sem medidas de segurança rigorosas, isso pode introduzir riscos de segurança, entre eles:

- **Invocação ilegal não autorizada**: as funcionalidades do agente podem ser descobertas por terceiros não autorizados ou por scanners maliciosos da internet, disparando requisições não autorizadas em massa que executam operações de alto risco, como comandos do sistema e leitura/escrita de arquivos, com possíveis consequências graves de segurança.
- **Riscos legais e de conformidade**: se o agente for invocado ilegalmente para conduzir ciberataques, roubo de dados ou outras atividades ilegais, isso pode resultar em responsabilidade legal e riscos de conformidade.

### Admin do Gateway equivale a execução de código

Um admin pode registrar servidores MCP stdio, que rodam comandos dentro do container do Gateway. A API os restringe a uma allowlist (`npx` e `uvx` por padrão, ampliada via `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST`) e rejeita argumentos e variáveis de ambiente que avaliariam código arbitrário. Isso é defesa em profundidade, não uma fronteira: esses launchers existem para buscar e rodar pacotes remotos, então **trate o admin do Gateway como equivalente a execução de código no host** e conceda esse acesso de acordo.

### Papéis de mensagem em chats externos

As requisições de run do Gateway e as atualizações manuais de estado de thread rejeitam com HTTP 400 mensagens `system` / `developer` enviadas pelo cliente, incluindo formas serializadas equivalentes. Chat comum, anexos e replay do histórico de assistant/ferramentas continuam suportados. A autenticação por sessão ou por PAT não concede autoridade de system prompt; os produtores internos confiáveis de runs mantêm essa capacidade.

Essa verificação impede novas injeções de papel; ela não reescreve checkpoints existentes. Se uma versão antiga aceitou uma mensagem de sistema injetada, use uma thread nova ou peça a um operador que revise e limpe o estado afetado. Reiniciar o serviço não remove instruções persistidas, e restaurar um checkpoint antigo pode restaurá-las.

Para verificação local, rode `python backend/tests/poc_external_system_message_injection.py --help`. O mesmo PoC, que é opt-in, suporta `--expect vulnerable` em uma revisão antiga isolada e `--expect blocked` depois da correção. A ajuda dele cobre a criação de PAT, a seleção de ID de thread, o follow-up pelo navegador e a diferença entre persistência e obediência do modelo. Use uma thread descartável nova a cada execução; o teste acrescenta mensagens.

Em um checkout isolado sem a correção, `--expect vulnerable` só demonstra a aceitação quando a requisição retorna 200 e a mensagem injetada exata permanece no checkpoint como `type=system` depois de um follow-up normal. Um marcador em uma resposta da web depende do modelo e não é, sozinho, evidência de que o papel foi promovido. Depois de aplicar a correção, rode o mesmo script com `--expect blocked`: ele exige o 400 específico de rejeição de papel, um checkpoint inalterado, um follow-up comum bem-sucedido e a ausência dos IDs das mensagens rejeitadas. Outras respostas 400 e erros de autenticação, de conflito ou de servidor são inconclusivos, não aprovações.

O PoC não faz limpeza automática. Concluída a verificação, exclua o chat descartável pela ação de excluir da barra lateral da web e revogue o PAT de curta duração, se um tiver sido criado. Reiniciar o serviço não remove uma instrução injetada persistida.

### Padrões de implantação

A stack Docker publica a porta de entrada apenas em `127.0.0.1`, de acordo com o modelo de ambiente local confiável descrito acima. Para acessá-la de outra máquina, defina `BIND_HOST` no `.env` (por exemplo `BIND_HOST=0.0.0.0`), e só depois de adotar as medidas de segurança abaixo.

**Conclua a configuração de primeiro uso antes que o host fique acessível.** Uma instância nova ainda não tem contas, então crie a conta de admin por `/setup` logo depois de iniciar qualquer implantação que não seja só de loopback.

### Recomendações de segurança

**Nota: recomendamos fortemente implantar o DeerFlow em um ambiente de rede local confiável.** Se você precisa de uma implantação entre dispositivos ou entre redes, é obrigatório adotar medidas de segurança rigorosas, como:

- **Allowlist de IP**: use `iptables`, ou implante firewalls de hardware / switches com listas de controle de acesso (ACL), para **configurar regras de allowlist de IP** e negar o acesso de todos os outros endereços IP.
- **Gateway de autenticação**: configure um proxy reverso (por exemplo, nginx) e **habilite uma pré-autenticação forte**, bloqueando qualquer acesso não autenticado.
- **Isolamento de rede**: quando possível, coloque o agente e os dispositivos confiáveis na **mesma VLAN dedicada**, isolada dos outros dispositivos da rede.
- **Mantenha-se atualizado**: continue acompanhando as atualizações dos recursos de segurança do DeerFlow.

## Contribuindo

Contribuições são bem-vindas! Veja no [CONTRIBUTING.md](CONTRIBUTING.md) a configuração do ambiente de desenvolvimento, o fluxo de trabalho e as diretrizes.

O `make test` do backend exclui a cobertura de APIs externas reais e de blocking I/O. Rode `cd backend && make test-blocking-io` para as verificações estritas de blocking I/O. Mantenedores podem rodar a suíte real do `DeerFlowClient` com `cd backend && make test-live`. Esse comando exige um `config.yaml` válido na raiz e credenciais de API. Ele pode gerar custos de API e criar sandboxes, artifacts ou arquivos locais. Execuções diretas do pytest exigem, além disso, `DEER_FLOW_RUN_LIVE_TESTS=1`.

A cobertura de regressão inclui testes de detecção do modo de sandbox Docker e de tratamento do caminho de kubeconfig do provisioner em `backend/tests/`.
Os diagnósticos de blocking IO do backend estão disponíveis a partir da raiz do repositório com `make detect-blocking-io`: ele varre estaticamente o código de negócio do backend em busca de IO bloqueante que possa rodar no event loop do backend, mostra um resumo curto e grava os achados completos em JSON em `.deer-flow/blocking-io-findings.json`. O JSON inclui registros compactos de revisão com `priority`, `location`, `blocking_call`, `event_loop_exposure`, `reason` e `code`.
O Gateway agora força os tipos de conteúdo web ativos (`text/html` e documentos XML como `.xml`, `.xhtml` e `.svg`) a serem baixados como anexos ao servir artifacts, em vez de renderizados inline, o que reduz o risco de XSS em artifacts gerados.

Os orçamentos de assets por rota do frontend podem ser verificados com `cd frontend && pnpm perf:check`. O comando mede `/login` a partir de um build normal de produção e depois faz um build de produção da demo estática para as rotas do workspace baseadas em fixtures. Ele mede o JavaScript e o CSS únicos referenciados por rotas representativas e grava o resultado detalhado em `.next/performance-results.json`.

## Licença

Este projeto é de código aberto e está disponível sob a [Licença MIT](./LICENSE).

## Agradecimentos

O DeerFlow foi construído sobre o trabalho da comunidade de código aberto. Somos muito gratos a todos os projetos e contribuidores cujo esforço tornou o DeerFlow possível. De fato, estamos sobre os ombros de gigantes.

Queremos registrar nosso agradecimento sincero aos seguintes projetos pelas suas contribuições:

- **[LangChain](https://github.com/langchain-ai/langchain)**: o framework deles sustenta nossas interações e chains com LLMs e torna a integração simples.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: a abordagem deles para orquestração multiagente foi fundamental para viabilizar os fluxos mais elaborados do DeerFlow.

Esses projetos mostram o que a colaboração em código aberto consegue fazer, e temos orgulho de construir sobre essas bases.

### Principais contribuidores

Um agradecimento de coração aos autores principais do `DeerFlow`, cuja visão, paixão e dedicação deram vida a este projeto:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

O compromisso e a experiência de vocês são a força por trás do sucesso do DeerFlow. É uma honra ter vocês à frente desta jornada.

## Histórico de estrelas

[![Star History Chart](https://star-history.dera.page/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.dera.page/#bytedance/deer-flow&Date)
