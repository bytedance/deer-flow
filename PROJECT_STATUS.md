# Aitouch — Статус проекта

> Основан на [DeerFlow](https://github.com/bytedance/deer-flow) (ByteDance)
> Последнее обновление: 2026-03-13

---

## 🏗️ Архитектура

```
deer-flow/
├── backend/          — LangGraph-агент (Python, FastAPI)
├── frontend/         — Next.js 15, Tailwind CSS v4, React
├── config.yaml       — Конфигурация моделей и инструментов
├── extensions_config.json — MCP-серверы
└── .env              — API-ключи
```

**Порты:**
| Сервис | Порт |
|---|---|
| Nginx (публичный) | 2026 |
| Next.js frontend | 3000 |
| Gateway API | 8001 |
| LangGraph server | — (внутренний) |

---

## ✅ Выполненные изменения

### 1. API и инструменты поиска
- [x] Добавлен **Perplexity sonar-pro** как основной инструмент веб-поиска
  - Файл: `backend/src/community/perplexity/__init__.py`
  - Файл: `backend/src/community/perplexity/tools.py`
  - Вызывает `https://api.perplexity.ai/chat/completions` через `httpx`
  - Возвращает `answer` + `sources` (citations)
- [x] Настроен `web_fetch` через Jina AI
- [x] Все ключи прописаны в `.env`

### 2. Модели (config.yaml)
- [x] Основная модель: **gemini-3.1-flash-lite-preview** (`thinking_budget: 512`)
- [x] Расширенная модель: **gemini-3.1-pro-preview** (`thinking_budget: 1024`)
- [x] Запасная модель: **gemini-2.5-flash** (без thinking)
- [x] Flash-lite стоит первой — отдельная квота, не исчерпывается

### 3. MCP-серверы (extensions_config.json)
Заполнена вкладка "Инструменты" в настройках UI:
- [x] `filesystem` — доступ к файлам (включён)
- [x] `github` — GitHub API (выключен, нужен токен)
- [x] `postgres` — подключение к БД (выключен)
- [x] `brave-search` — альтернативный поиск (выключен)

### 4. Дизайн и UI

#### Шрифт
- [x] Заменён Geist → **Inter** с поддержкой кириллицы
  - Файл: `frontend/src/app/layout.tsx`
  - Веса: 300–800, subsets: latin + cyrillic

#### Цветовая схема (globals.css)
- [x] Основной цвет: **Electric Blue `#1C64F2`**
- [x] Светлая тема (Soft UI / Bento):
  - Фон: `#F4F6F9`
  - Карточки: `#FFFFFF` с мягкой тенью
  - Границы: `#E5E7EB`
- [x] Тёмная тема (Glassmorphism):
  - Фон: `#0B0F19` с радиальным градиентом-свечением
  - Карточки: `rgba(255,255,255,0.04)` + `backdrop-filter: blur(12px)`
  - Границы: `rgba(255,255,255,0.08)`
- [x] Скруглённые углы: `--radius: 1rem` (базовый)
- [x] Анимации hover на карточках
- [x] Тонкий кастомный скроллбар

#### Фокус и ring
- [x] Убрана синяя обводка при фокусе (`outline: none !important`)
- [x] `--ring: transparent` в обеих темах

### 5. Логотип
- [x] Создан компонент `frontend/src/components/ui/logo.tsx`
  - Кастомный SVG-логотип (wordmark "Aitouch")
  - Prop `collapsed` — показывает только букву "A" в свёрнутом сайдбаре
- [x] Вставлен в хедер сайдбара (`workspace-header.tsx`)

### 6. Интернационализация — Русский язык
- [x] Добавлен локаль `ru-RU` в список поддерживаемых
- [x] `DEFAULT_LOCALE = "ru-RU"` — русский по умолчанию
- [x] Создан полный файл переводов `frontend/src/core/i18n/locales/ru-RU.ts`
  - ~365 строк, все секции UI переведены
- [x] **Фикс**: старый cookie `en-US` больше не переопределяет русский дефолт
  - `hooks.ts`: если cookie == `"en-US"` → игнорируем, ставим `ru-RU`
  - `server.ts`: аналогичная логика на сервере

#### Приветствие (Aitouch)
- [x] Заголовок: `"Привет! Чем займёмся?"`
- [x] Описание: `"Aitouch — мультимодальный ИИ-агент для маркетинга. Исследует рынок, создаёт контент, анализирует данные и генерирует лендинги, презентации и рекламные кампании."`

### 7. Удалённые функции
- [x] **Убран модуль follow-up подсказок** (`input-box.tsx`)
  - Удалены: state, useEffect с fetch, JSX-блок, Dialog подтверждения
  - Причина: верстка вылезала за края, медленная генерация

### 8. Баги — исправлено
- [x] **Названия чатов показывали `[{'type': 'text', 'text': '...'}]`**
  - Файл: `backend/src/agents/middlewares/title_middleware.py`
  - Добавлен метод `_extract_text()` для корректного извлечения текста из LangChain message content (list-формат)
- [x] **Чат не отвечал** — исчерпана квота gemini-3.1-pro (250 req/day)
  - Flash-lite поставлен первым в списке моделей

---

## 🔑 API-ключи

| Сервис | Переменная | Статус |
|---|---|---|
| Google AI (Gemini) | `GOOGLE_API_KEY` | ✅ Активен (ключ обновлён 14.03.2026) |
| Perplexity | `PERPLEXITY_API_KEY` | ✅ Активен |
| Tavily (резерв) | `TAVILY_API_KEY` | ✅ Активен |

> ⚠️ Бесплатный лимит Gemini: **250 запросов/день на модель**

---

## 📁 Ключевые файлы

| Файл | Назначение |
|---|---|
| `config.yaml` | Модели, инструменты, параметры агента |
| `.env` | API-ключи |
| `extensions_config.json` | MCP-серверы для UI |
| `backend/src/community/perplexity/tools.py` | Perplexity web_search |
| `backend/src/agents/lead_agent/prompt.py` | Системный промпт (`SYSTEM_PROMPT_TEMPLATE`) |
| `backend/src/agents/middlewares/title_middleware.py` | Генерация заголовков чатов |
| `frontend/src/styles/globals.css` | Дизайн-система, темы, анимации |
| `frontend/src/app/layout.tsx` | Шрифт Inter |
| `frontend/src/core/i18n/` | Интернационализация |
| `frontend/src/core/i18n/locales/ru-RU.ts` | Русский перевод |
| `frontend/src/components/ui/logo.tsx` | Логотип Aitouch |

---

## 🔧 Системный промпт

**Расположение:** `backend/src/agents/lead_agent/prompt.py`

Переменная `SYSTEM_PROMPT_TEMPLATE` содержит полный промпт с секциями:
- `<role>` — роль (текущее имя: `"DeerFlow 2.0"`, можно изменить на `"Aitouch"`)
- `<thinking_style>`, `<clarification_system>`, `<skill_system>`
- `<response_style>`, `<citations>`, `<critical_reminders>`

Сборка: функция `apply_prompt_template()` подставляет:
- `{agent_name}` → `"DeerFlow 2.0"` (нужно поменять на `"Aitouch"`)
- `{soul}` → из `SOUL.md` агента (если создан)
- `{memory_context}` → воспоминания из памяти
- `{skills_section}` → список навыков

**Промпты памяти:** `backend/src/agents/memory/prompt.py`

---

## 🐳 Docker — развёртывание

Проект запущен в Docker (4 контейнера):

| Контейнер | Назначение | Порт |
|---|---|---|
| `deer-flow-nginx` | Reverse proxy | 2026 (публичный) |
| `deer-flow-frontend` | Next.js | 3000 (внутренний) |
| `deer-flow-gateway` | FastAPI Gateway | 8001 (внутренний) |
| `deer-flow-langgraph` | LangGraph агент | 2024 (внутренний) |

**Монтируемые volumes** (меняются без пересборки):
- `config.yaml` → `/app/config.yaml`
- `extensions_config.json` → `/app/extensions_config.json`
- `backend/.deer-flow/` → данные, память, файлы потоков
- `skills/` → навыки агентов

**Код Python/Frontend** — запечён в образах, для обновления нужно:
```bash
# Быстро (без rebuild): скопировать файл в контейнер
docker cp backend/src/agents/middlewares/title_middleware.py deer-flow-langgraph:/app/backend/src/agents/middlewares/title_middleware.py
docker restart deer-flow-langgraph

# Полный rebuild (frontend или major изменения):
DEER_FLOW_HOME="$PWD/backend/.deer-flow" DEER_FLOW_REPO_ROOT="$PWD" \
DEER_FLOW_CONFIG_PATH="$PWD/config.yaml" DEER_FLOW_EXTENSIONS_CONFIG_PATH="$PWD/extensions_config.json" \
DEER_FLOW_DOCKER_SOCKET="/var/run/docker.sock" BETTER_AUTH_SECRET="<secret>" \
docker compose -p deer-flow -f docker/docker-compose.yaml build --no-cache frontend
```

---

## 🚧 Что можно сделать дальше

- [ ] Переименовать агента в "Aitouch" в системном промпте (`prompt.py`, строка ~400)
- [ ] Создать `SOUL.md` для кастомизации личности агента
- [ ] Включить нужные MCP-серверы в `extensions_config.json` (добавить токены)
- [ ] Настроить `nginx` для HTTPS / кастомного домена
- [ ] Добавить fallback на Tavily если Perplexity недоступен
- [ ] Расширить русский перевод для новых функций
- [ ] Оптимизировать `thinking_budget` под реальные задачи

---

## 🚀 Запуск

```bash
cd /root/deer-flow

# Backend
cd backend && uv run python -m uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001

# Frontend
cd frontend && npm run build && npm start

# Или через make
make dev
```

**Публичный адрес:** `http://<server-ip>:2026`
