# 🦌 DeerFlow - 2.0

[English](./README.md) | Portugues (Brasil) | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md)

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) e um **super agent harness** open source que orquestra **subagentes**, **memoria** e **sandboxes** para realizar tarefas complexas com ajuda de **skills extensiveis**.

## Site oficial

Veja mais detalhes e demos reais em [deerflow.tech](https://deerflow.tech).

## Inicio rapido

### 1. Clone o repositorio

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
```

### 2. Gere os arquivos locais de configuracao

Na raiz do projeto, execute:

```bash
make config
```

Isso cria os arquivos locais a partir dos templates fornecidos.

### 3. Configure pelo menos um modelo em `config.yaml`

Exemplo:

```yaml
models:
  - name: gpt-4
    display_name: GPT-4
    use: langchain_openai:ChatOpenAI
    model: gpt-4
    api_key: $OPENAI_API_KEY
    max_tokens: 4096
    temperature: 0.7
```

Gateways compativeis com OpenAI, como OpenRouter, podem usar `langchain_openai:ChatOpenAI` com `base_url`.

### 4. Defina as chaves de API

Opcao recomendada: editar o arquivo `.env` na raiz do projeto.

```bash
OPENAI_API_KEY=seu-token
TAVILY_API_KEY=seu-token-tavily
INFOQUEST_API_KEY=seu-token-infoquest
```

## Como executar

### Opcao 1: Docker (recomendado)

Ambiente de desenvolvimento:

```bash
make docker-init
make docker-start
```

### Opcao 2: Desenvolvimento local

Instale as dependencias e inicie os servicos separadamente conforme o guia principal e os documentos do backend.

## Principais recursos

- Skills e tools extensiveis
- Subagentes com contexto isolado
- Sandbox e sistema de arquivos por thread
- Memoria de longo prazo
- Engenharia de contexto para tarefas longas

## Documentacao

- [Guia de contribuicao](./CONTRIBUTING.md)
- [Guia de configuracao](./backend/docs/CONFIGURATION.md)
- [Arquitetura tecnica](./backend/CLAUDE.md)
- [Arquitetura do backend](./backend/README.md)

## Aviso de seguranca

O DeerFlow possui capacidades de alto privilegio, incluindo execucao de comandos, operacoes em arquivos e invocacao de logica de negocio. O uso padrao foi pensado para ambientes locais e confiaveis.

Se voce pretende expor o sistema em redes nao confiaveis, implemente medidas rigorosas como:

- allowlist de IP
- proxy reverso com autenticacao forte
- isolamento de rede
- atualizacao continua das configuracoes de seguranca

## Licenca

Este projeto e distribuido sob a [Licenca MIT](./LICENSE).
