# 🦌 DeerFlow - 2.0

[English](./README.md) | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | Русский

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

> 28 февраля 2026 года DeerFlow занял 🏆 #1 в GitHub Trending после релиза версии 2. Спасибо огромное нашему сообществу — всё благодаря вам! 💪🔥

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) — open-source **Super Agent Harness**, который управляет **Sub-Agents**, **Memory** и **Sandbox** для решения почти любой задачи. Всё на основе расширяемых **Skills**.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0 — проект переписан с нуля.** Общего кода с v1 нет. Если нужен оригинальный Deep Research фреймворк — он живёт в ветке [`1.x`](https://github.com/bytedance/deer-flow/tree/main-1.x), туда тоже принимают контрибьюты. Активная разработка идёт в 2.0.

## Официальный сайт

[<img width="2880" height="1600" alt="image" src="https://github.com/user-attachments/assets/a598c49f-3b2f-41ea-a052-05e21349188a" />](https://deerflow.tech)

Больше информации и живые демо на [**официальном сайте**](https://deerflow.tech).

## Coding Plan от ByteDance Volcengine

<img width="4808" height="2400" alt="英文方舟" src="https://github.com/user-attachments/assets/2ecc7b9d-50be-4185-b1f7-5542d222fb2d" />

- Рекомендуем Doubao-Seed-2.0-Code, DeepSeek v3.2 и Kimi 2.5 для запуска DeerFlow
- [Подробнее](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [Для разработчиков из материкового Китая](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow интегрирован с инструментарием для умного поиска и краулинга от BytePlus — [InfoQuest (есть бесплатный онлайн-доступ)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"
    alt="InfoQuest_banner"
  />
</a>

---

## Содержание

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Официальный сайт](#официальный-сайт)
  - [InfoQuest](#infoquest)
  - [Содержание](#содержание)
  - [Установка одной фразой для coding agent](#установка-одной-фразой-для-coding-agent)
  - [Быстрый старт](#быстрый-старт)
    - [Конфигурация](#конфигурация)
    - [Запуск](#запуск)
      - [Вариант 1: Docker (рекомендуется)](#вариант-1-docker-рекомендуется)
      - [Вариант 2: Локальная разработка](#вариант-2-локальная-разработка)
    - [Дополнительно](#дополнительно)
      - [Режим Sandbox](#режим-sandbox)
      - [MCP-сервер](#mcp-сервер)
      - [Мессенджеры](#мессенджеры)
      - [Трассировка LangSmith](#трассировка-langsmith)
  - [От Deep Research к Super Agent Harness](#от-deep-research-к-super-agent-harness)
  - [Core Features](#core-features)
    - [Skills & Tools](#skills--tools)
      - [Интеграция с Claude Code](#интеграция-с-claude-code)
    - [Sub-Agents](#sub-agents)
    - [Sandbox & файловая система](#sandbox--файловая-система)
    - [Context Engineering](#context-engineering)
    - [Long-Term Memory](#long-term-memory)
  - [Рекомендуемые модели](#рекомендуемые-модели)
  - [Встроенный Python-клиент](#встроенный-python-клиент)
  - [Документация](#документация)
  - [⚠️ Безопасность](#️-безопасность)
  - [Участие в разработке](#участие-в-разработке)
  - [Лицензия](#лицензия)
  - [Благодарности](#благодарности)
    - [Ключевые контрибьюторы](#ключевые-контрибьюторы)
  - [История звёзд](#история-звёзд)

## Установка одной фразой для coding agent

Если вы используете Claude Code, Codex, Cursor, Windsurf или другой coding agent, просто отправьте ему эту фразу:

```text
Если DeerFlow еще не клонирован, сначала клонируй его, а затем подготовь локальное окружение разработки по инструкции https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

Этот prompt предназначен для coding agent. Он просит агента при необходимости сначала клонировать репозиторий, предпочесть Docker, если он доступен, и в конце вернуть точную команду запуска и список недостающих настроек.

## Быстрый старт

### Конфигурация

1. **Склонировать репозиторий DeerFlow**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Сгенерировать локальные конфиги**

   Из корня проекта (`deer-flow/`) запустите:

   ```bash
   make config
   ```

   Команда создаёт локальные конфиги на основе шаблонов.

3. **Настроить модель**

   Отредактируйте `config.yaml` и задайте хотя бы одну модель:

   ```yaml
   models:
     - name: gpt-4                       # Внутренний идентификатор
       display_name: GPT-4               # Отображаемое имя
       use: langchain_openai:ChatOpenAI  # Путь к классу LangChain
       model: gpt-4                      # Идентификатор модели для API
       api_key: $OPENAI_API_KEY          # API-ключ (рекомендуется: переменная окружения)
       max_tokens: 4096                  # Максимальное количество токенов на запрос
       temperature: 0.7                  # Температура сэмплирования

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENAI_API_KEY
       base_url: https://openrouter.ai/api/v1

     - name: gpt-5-responses
       display_name: GPT-5 (Responses API)
       use: langchain_openai:ChatOpenAI
       model: gpt-5
       api_key: $OPENAI_API_KEY
       use_responses_api: true
       output_version: responses/v1
   ```

   OpenRouter и аналогичные OpenAI-совместимые шлюзы настраиваются через `langchain_openai:ChatOpenAI` с параметром `base_url`. Для CLI-провайдеров:

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

   - Codex CLI читает `~/.codex/auth.json`
   - Claude Code принимает `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN` или `~/.claude/.credentials.json`
   - На macOS при необходимости экспортируйте аутентификацию Claude Code явно:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

4. **Указать API-ключи**

   - **Вариант А**: файл `.env` в корне проекта (рекомендуется)

   ```bash
   TAVILY_API_KEY=your-tavily-api-key
   OPENAI_API_KEY=your-openai-api-key
   INFOQUEST_API_KEY=your-infoquest-api-key
   ```

   - **Вариант Б**: переменные окружения в терминале

   ```bash
   export OPENAI_API_KEY=your-openai-api-key
   ```

   - **Вариант В**: напрямую в `config.yaml` (не рекомендуется для продакшена)

### Запуск

#### Вариант 1: Docker (рекомендуется)

**Разработка** (hot-reload, монтирование исходников):

```bash
make docker-init    # Загрузить образ Sandbox (один раз или при обновлении)
make docker-start   # Запустить сервисы
```

**Продакшен** (собирает образы локально):

```bash
make up     # Собрать образы и запустить все сервисы
make down   # Остановить и удалить контейнеры
```

> [!TIP]
> На Linux при ошибке `permission denied` для Docker daemon добавьте пользователя в группу `docker` и перелогиньтесь. Подробнее в [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied).

Адрес: http://localhost:2026

#### Вариант 2: Локальная разработка

1. **Проверить зависимости**:
   ```bash
   make check  # Проверяет Node.js 22+, pnpm, uv, nginx
   ```

2. **Установить зависимости**:
   ```bash
   make install
   ```

3. **(Опционально) Загрузить образ Sandbox заранее**:
   ```bash
   make setup-sandbox
   ```

4. **Запустить сервисы**:
   ```bash
   make dev
   ```

5. **Адрес**: http://localhost:2026

### Дополнительно

#### Режим Sandbox

DeerFlow поддерживает несколько режимов выполнения:
- **Локальное выполнение** — код запускается прямо на хосте
- **Docker** — код выполняется в изолированных Docker-контейнерах
- **Docker + Kubernetes** — выполнение в Kubernetes-подах через provisioner

Подробнее в [руководстве по конфигурации Sandbox](backend/docs/CONFIGURATION.md#sandbox).

#### MCP-сервер

DeerFlow поддерживает настраиваемые MCP-серверы для расширения возможностей. Для HTTP/SSE MCP-серверов поддерживаются OAuth-токены (`client_credentials`, `refresh_token`). Подробнее в [руководстве по MCP-серверу](backend/docs/MCP_SERVER.md).

#### Мессенджеры

DeerFlow принимает задачи прямо из мессенджеров. Каналы запускаются автоматически при настройке, публичный IP не нужен.

| Канал | Транспорт | Сложность |
|-------|-----------|-----------|
| Telegram | Bot API (long-polling) | Просто |
| Slack | Socket Mode | Средне |
| Feishu / Lark | WebSocket | Средне |
| DingTalk | Stream Push (WebSocket) | Средне |

**Конфигурация в `config.yaml`:**

```yaml
channels:
  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    # domain: https://open.feishu.cn       # China (default)
    # domain: https://open.larksuite.com   # International

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN
    app_token: $SLACK_APP_TOKEN
    allowed_users: []

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    allowed_users: []

  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID             # ClientId с DingTalk Open Platform
    client_secret: $DINGTALK_CLIENT_SECRET     # ClientSecret с DingTalk Open Platform
    allowed_users: []                          # пусто = разрешить всем
    card_template_id: ""                       # Опционально: ID шаблона AI Card для потокового эффекта печатной машинки
```

**Настройка Telegram**

1. Напишите [@BotFather](https://t.me/BotFather), отправьте `/newbot` и скопируйте HTTP API-токен.
2. Укажите `TELEGRAM_BOT_TOKEN` в `.env` и включите канал в `config.yaml`.

**Настройка DingTalk**

1. Создайте приложение на [DingTalk Open Platform](https://open.dingtalk.com/) и включите возможность **Робот**.
2. На странице настроек робота установите режим приёма сообщений на **Stream**.
3. Скопируйте `Client ID` и `Client Secret`. Укажите `DINGTALK_CLIENT_ID` и `DINGTALK_CLIENT_SECRET` в `.env` и включите канал в `config.yaml`.
4. *(Опционально)* Для включения потоковых ответов AI Card (эффект печатной машинки) создайте шаблон **AI Card** на [платформе карточек DingTalk](https://open.dingtalk.com/document/dingstart/typewriter-effect-streaming-ai-card), затем укажите `card_template_id` в `config.yaml` с ID шаблона. Также необходимо запросить разрешения `Card.Streaming.Write` и `Card.Instance.Write`.

**Доступные команды**

| Команда | Описание |
|---------|----------|
| `/new` | Начать новый диалог |
| `/status` | Показать информацию о текущем треде |
| `/models` | Список доступных моделей |
| `/memory` | Просмотреть память |
| `/help` | Показать справку |

> Сообщения без команды воспринимаются как обычный чат — DeerFlow создаёт тред и отвечает.

#### Трассировка LangSmith

DeerFlow имеет встроенную интеграцию с [LangSmith](https://smith.langchain.com) для наблюдаемости. При включении все вызовы LLM, запуски агентов и выполнения инструментов отслеживаются и отображаются в дашборде LangSmith.

Добавьте в файл `.env` в корне проекта:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=deer-flow
```

`LANGSMITH_ENDPOINT` по умолчанию `https://api.smith.langchain.com` и может быть переопределён при необходимости. Устаревшие переменные `LANGCHAIN_*` (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY` и т.д.) также поддерживаются для обратной совместимости; `LANGSMITH_*` имеет приоритет, когда заданы обе.

В Docker-развёртываниях трассировка отключена по умолчанию. Установите `LANGSMITH_TRACING=true` и `LANGSMITH_API_KEY` в `.env` для включения.

## От Deep Research к Super Agent Harness

DeerFlow начинался как фреймворк для Deep Research, и сообщество вышло далеко за эти рамки. После запуска разработчики строили пайплайны, генерировали презентации, поднимали дашборды, автоматизировали контент. То, чего мы не ожидали.

Стало понятно: DeerFlow не просто research-инструмент. Это **harness**: runtime, который даёт агентам необходимую инфраструктуру.

Поэтому мы переписали всё с нуля.

DeerFlow 2.0 — это Super Agent Harness «из коробки». Batteries included, полностью расширяемый. Построен на LangGraph и LangChain. По умолчанию есть всё, что нужно агенту: файловая система, memory, skills, sandbox-выполнение и возможность планировать и запускать sub-agents для сложных многошаговых задач.

Используйте как есть. Или разберите и переделайте под себя.

## Core Features

### Skills & Tools

Skills — это то, что позволяет DeerFlow делать почти что угодно.

Agent Skill — это структурированный модуль: Markdown-файл с описанием воркфлоу, лучших практик и ссылок на ресурсы. DeerFlow поставляется со встроенными skills для ресёрча, генерации отчётов, слайдов, веб-страниц, изображений и видео. Но главное — расширяемость: добавляйте свои skills, заменяйте встроенные или собирайте из них составные воркфлоу.

Skills загружаются по мере необходимости, только когда задача их требует. Это держит контекстное окно чистым.

```
# Пути внутри контейнера sandbox
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← ваш skill
```

#### Интеграция с Claude Code

Skill `claude-to-deerflow` позволяет работать с DeerFlow прямо из [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Отправляйте задачи, проверяйте статус, управляйте тредами, не выходя из терминала.

**Установка скилла**:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

**Что можно делать**:
- Отправлять сообщения в DeerFlow и получать потоковые ответы
- Выбирать режимы выполнения: flash (быстро), standard, pro (planning), ultra (sub-agents)
- Проверять статус DeerFlow, просматривать модели, скиллы, агентов
- Управлять тредами и историей диалога
- Загружать файлы для анализа

Полный справочник API в [`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md).

### Sub-Agents

Сложные задачи редко решаются за один проход. DeerFlow их декомпозирует.

Lead agent запускает sub-agents на лету, каждый со своим изолированным контекстом, инструментами и условиями завершения. Sub-agents работают параллельно, возвращают структурированные результаты, а lead agent собирает всё в единый итог.

Вот как DeerFlow справляется с задачами на минуты и часы: research-задача разветвляется в дюжину sub-agents, каждый копает свой угол, потом всё сходится в один отчёт, или сайт, или слайддек со сгенерированными визуалами. Один harness, много рук.

### Sandbox & файловая система

DeerFlow не просто *говорит* о том, что умеет что-то делать. У него есть собственный компьютер.

Каждая задача выполняется внутри изолированного Docker-контейнера с полной файловой системой: skills, workspace, uploads, outputs. Агент читает, пишет и редактирует файлы. Выполняет bash-команды и пишет код. Смотрит на изображения. Всё изолировано, всё прозрачно, никакого пересечения между сессиями.

Это разница между чатботом с доступом к инструментам и агентом с реальной средой выполнения.

```
# Пути внутри контейнера sandbox
/mnt/user-data/
├── uploads/          ← ваши файлы
├── workspace/        ← рабочая директория агентов
└── outputs/          ← результаты
```

### Context Engineering

**Изолированный контекст**: каждый sub-agent работает в своём контексте и не видит контекст главного агента или других sub-agents. Агент фокусируется на своей задаче.

**Управление контекстом**: внутри сессии DeerFlow агрессивно сжимает контекст и суммирует завершённые подзадачи, выгружает промежуточные результаты в файловую систему, сжимает то, что уже не актуально. На длинных многошаговых задачах контекстное окно не переполняется.

### Long-Term Memory

Большинство агентов забывают всё, когда диалог заканчивается. DeerFlow помнит.

DeerFlow сохраняет ваш профиль, предпочтения и накопленные знания между сессиями. Чем больше используете, тем лучше он вас знает: стиль, технологический стек, повторяющиеся воркфлоу. Всё хранится локально и остаётся под вашим контролем.

## Рекомендуемые модели

DeerFlow работает с любым LLM через OpenAI-совместимый API. Лучше всего — с моделями, которые поддерживают:

- **Большое контекстное окно** (100k+ токенов) — для deep research и многошаговых задач
- **Reasoning capabilities** — для адаптивного планирования и сложной декомпозиции
- **Multimodal inputs** — для работы с изображениями и видео
- **Strong tool-use** — для надёжного вызова функций и структурированных ответов

## Встроенный Python-клиент

DeerFlow можно использовать как Python-библиотеку прямо в коде — без запуска HTTP-сервисов. `DeerFlowClient` даёт доступ ко всем возможностям агента и Gateway, возвращает те же схемы ответов, что и HTTP Gateway API:

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
```

## Документация

- [Руководство по участию](CONTRIBUTING.md) — настройка среды разработки, воркфлоу и гайдлайны
- [Руководство по конфигурации](backend/docs/CONFIGURATION.md) — инструкции по настройке
- [Обзор архитектуры](backend/CLAUDE.md) — технические детали
- [Архитектура бэкенда](backend/README.md) — бэкенд и справочник API

## ⚠️ Безопасность

### Неправильное развёртывание может привести к угрозам безопасности

DeerFlow обладает ключевыми высокопривилегированными возможностями, включая **выполнение системных команд, операции с ресурсами и вызов бизнес-логики**. По умолчанию он рассчитан на **развёртывание в локальной доверенной среде (доступ только через loopback-адрес 127.0.0.1)**. Если вы разворачиваете агент в недоверенных средах — локальных сетях, публичных облачных серверах или других окружениях, доступных с нескольких устройств — без строгих мер безопасности, это может привести к следующим угрозам:

- **Несанкционированные вызовы**: функциональность агента может быть обнаружена неавторизованными третьими лицами или вредоносными сканерами, что приведёт к массовым несанкционированным запросам с выполнением высокорисковых операций (системные команды, чтение/запись файлов) и серьёзным последствиям для безопасности.
- **Юридические и compliance-риски**: если агент будет незаконно использован для кибератак, кражи данных или других противоправных действий, это может повлечь юридическую ответственность и compliance-риски.

### Рекомендации по безопасности

**Примечание: настоятельно рекомендуем развёртывать DeerFlow только в локальной доверенной сети.** Если вам необходимо развёртывание через несколько устройств или сетей, обязательно реализуйте строгие меры безопасности, например:

- **Белый список IP-адресов**: используйте `iptables` или аппаратные межсетевые экраны / коммутаторы с ACL, чтобы **настроить правила белого списка IP** и заблокировать доступ со всех остальных адресов.
- **Шлюз аутентификации**: настройте обратный прокси (nginx и др.) и **включите строгую предварительную аутентификацию**, запрещающую любой доступ без авторизации.
- **Сетевая изоляция**: по возможности разместите агент и доверенные устройства в **одном выделенном VLAN**, изолированном от остальной сети.
- **Следите за обновлениями**: регулярно отслеживайте обновления безопасности проекта DeerFlow.

## Участие в разработке

Приветствуем контрибьюторов! Настройка среды разработки, воркфлоу и гайдлайны — в [CONTRIBUTING.md](CONTRIBUTING.md).

## Лицензия

Проект распространяется под [лицензией MIT](./LICENSE).

## Благодарности

DeerFlow стоит на плечах open-source сообщества. Спасибо всем проектам и разработчикам, чья работа сделала его возможным.

Отдельная благодарность:

- **[LangChain](https://github.com/langchain-ai/langchain)** — фреймворк для взаимодействия с LLM и построения цепочек.
- **[LangGraph](https://github.com/langchain-ai/langgraph)** — многоагентная оркестрация, на которой держатся сложные воркфлоу DeerFlow.

### Ключевые контрибьюторы

Авторы DeerFlow, без которых проекта бы не было:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

## История звёзд

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
