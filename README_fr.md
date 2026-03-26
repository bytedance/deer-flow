# 🦌 DeerFlow - 2.0

[English](./README.md) | [中文](./README_zh.md) | [日本語](./README_ja.md) | Français

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> Le 28 février 2026, DeerFlow a décroché la 🏆 1re place sur GitHub Trending suite au lancement de la version 2. Un immense merci à notre incroyable communauté — c'est grâce à vous ! 💪🔥

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) est un **super agent harness** open source qui orchestre des **sub-agents**, de la **mémoire** et des **sandboxes** pour accomplir pratiquement n'importe quelle tâche — le tout propulsé par des **skills extensibles**.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0 est une réécriture complète.** Il ne partage aucun code avec la v1. Si vous cherchez le framework Deep Research original, il est maintenu sur la [branche `1.x`](https://github.com/bytedance/deer-flow/tree/main-1.x) — les contributions y sont toujours les bienvenues. Le développement actif a migré vers la 2.0.

## Site officiel

[<img width="2880" height="1600" alt="image" src="https://github.com/user-attachments/assets/a598c49f-3b2f-41ea-a052-05e21349188a" />](https://deerflow.tech)

Découvrez-en plus et regardez des **démos réelles** sur notre [**site officiel**](https://deerflow.tech).

## Coding Plan de ByteDance Volcengine

<img width="4808" height="2400" alt="英文方舟" src="https://github.com/user-attachments/assets/2ecc7b9d-50be-4185-b1f7-5542d222fb2d" />

- Nous recommandons fortement d'utiliser Doubao-Seed-2.0-Code, DeepSeek v3.2 et Kimi 2.5 pour exécuter DeerFlow
- [En savoir plus](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [Développeurs en Chine continentale, cliquez ici](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow intègre désormais le toolkit de recherche et de crawling intelligent développé par BytePlus — [InfoQuest (essai gratuit en ligne)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Table des matières

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Site officiel](#site-officiel)
  - [InfoQuest](#infoquest)
  - [Table des matières](#table-des-matières)
  - [Démarrage rapide](#démarrage-rapide)
    - [Configuration](#configuration)
    - [Lancer l'application](#lancer-lapplication)
      - [Option 1 : Docker (recommandé)](#option-1--docker-recommandé)
      - [Option 2 : Développement local](#option-2--développement-local)
    - [Avancé](#avancé)
      - [Mode Sandbox](#mode-sandbox)
      - [Serveur MCP](#serveur-mcp)
      - [Canaux de messagerie](#canaux-de-messagerie)
  - [Du Deep Research au Super Agent Harness](#du-deep-research-au-super-agent-harness)
  - [Fonctionnalités principales](#fonctionnalités-principales)
    - [Skills et outils](#skills-et-outils)
      - [Intégration Claude Code](#intégration-claude-code)
    - [Sub-Agents](#sub-agents)
    - [Sandbox et système de fichiers](#sandbox-et-système-de-fichiers)
    - [Context Engineering](#context-engineering)
    - [Mémoire à long terme](#mémoire-à-long-terme)
  - [Modèles recommandés](#modèles-recommandés)
  - [Client Python intégré](#client-python-intégré)
  - [Documentation](#documentation)
  - [⚠️ Avertissement de sécurité](#️-avertissement-de-sécurité)
  - [Contribuer](#contribuer)
  - [Licence](#licence)
  - [Remerciements](#remerciements)
    - [Contributeurs principaux](#contributeurs-principaux)
  - [Star History](#star-history)

## Démarrage rapide

### Configuration

1. **Cloner le dépôt DeerFlow**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Générer les fichiers de configuration locaux**

   Depuis le répertoire racine du projet (`deer-flow/`), exécutez :

   ```bash
   make config
   ```

   Cette commande crée les fichiers de configuration locaux à partir des templates fournis.

3. **Configurer le(s) modèle(s) de votre choix**

   Éditez `config.yaml` et définissez au moins un modèle :

   ```yaml
   models:
     - name: gpt-4                       # Internal identifier
       display_name: GPT-4               # Human-readable name
       use: langchain_openai:ChatOpenAI  # LangChain class path
       model: gpt-4                      # Model identifier for API
       api_key: $OPENAI_API_KEY          # API key (recommended: use env var)
       max_tokens: 4096                  # Maximum tokens per request
       temperature: 0.7                  # Sampling temperature

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENAI_API_KEY          # OpenRouter still uses the OpenAI-compatible field name here
       base_url: https://openrouter.ai/api/v1

     - name: gpt-5-responses
       display_name: GPT-5 (Responses API)
       use: langchain_openai:ChatOpenAI
       model: gpt-5
       api_key: $OPENAI_API_KEY
       use_responses_api: true
       output_version: responses/v1
   ```

   OpenRouter et les passerelles compatibles OpenAI similaires doivent être configurés avec `langchain_openai:ChatOpenAI` et `base_url`. Si vous préférez utiliser un nom de variable d'environnement propre au fournisseur, pointez `api_key` vers cette variable explicitement (par exemple `api_key: $OPENROUTER_API_KEY`).

   Pour router les modèles OpenAI via `/v1/responses`, continuez d'utiliser `langchain_openai:ChatOpenAI` et définissez `use_responses_api: true` avec `output_version: responses/v1`.

   Exemples de providers basés sur un CLI :

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

   - Codex CLI lit `~/.codex/auth.json`
   - L'endpoint Responses de Codex rejette actuellement `max_tokens` et `max_output_tokens`, donc `CodexChatModel` n'expose pas de limite de tokens par requête
   - Claude Code accepte `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_CREDENTIALS_PATH`, ou en clair `~/.claude/.credentials.json`
   - Sur macOS, DeerFlow ne sonde pas le Keychain automatiquement. Exportez l'auth Claude Code explicitement si nécessaire :

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

4. **Définir les clés API pour le(s) modèle(s) configuré(s)**

   Choisissez l'une des méthodes suivantes :

- Option A : Éditer le fichier `.env` à la racine du projet (recommandé)


   ```bash
   TAVILY_API_KEY=your-tavily-api-key
   OPENAI_API_KEY=your-openai-api-key
   # OpenRouter also uses OPENAI_API_KEY when your config uses langchain_openai:ChatOpenAI + base_url.
   # Add other provider keys as needed
   INFOQUEST_API_KEY=your-infoquest-api-key
   ```

- Option B : Exporter les variables d'environnement dans votre shell

   ```bash
   export OPENAI_API_KEY=your-openai-api-key
   ```

   Pour les providers basés sur un CLI :
   - Codex CLI : `~/.codex/auth.json`
   - Claude Code OAuth : handoff explicite via env/fichier ou `~/.claude/.credentials.json`

- Option C : Éditer `config.yaml` directement (non recommandé en production)

   ```yaml
   models:
     - name: gpt-4
       api_key: your-actual-api-key-here  # Replace placeholder
   ```

### Lancer l'application

#### Option 1 : Docker (recommandé)

**Développement** (hot-reload, montage des sources) :

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
```

`make docker-start` ne lance `provisioner` que si `config.yaml` utilise le mode provisioner (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` avec `provisioner_url`).
Les processus backend récupèrent automatiquement les changements dans `config.yaml` au prochain accès à la configuration, donc les mises à jour de métadonnées des modèles ne nécessitent pas de redémarrage manuel en développement.

> [!TIP]
> Sous Linux, si les commandes Docker échouent avec `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, ajoutez votre utilisateur au groupe `docker` et reconnectez-vous avant de réessayer. Voir [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied) pour la solution complète.

**Production** (build des images en local, montage de la config et des données) :

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

> [!NOTE]
> Le serveur d'agents LangGraph fonctionne actuellement via `langgraph dev` (le serveur CLI open source).

Accès : http://localhost:2026

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour le guide complet de développement avec Docker.

#### Option 2 : Développement local

Si vous préférez lancer les services en local :

Prérequis : complétez d'abord les étapes de « Configuration » ci-dessus (`make config` et clés API des modèles). `make dev` nécessite un fichier de configuration valide (par défaut `config.yaml` à la racine du projet ; modifiable via `DEER_FLOW_CONFIG_PATH`).

1. **Vérifier les prérequis** :
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

2. **Installer les dépendances** :
   ```bash
   make install  # Install backend + frontend dependencies
   ```

3. **(Optionnel) Pré-télécharger l'image sandbox** :
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```

4. **Démarrer les services** :
   ```bash
   make dev
   ```

5. **Accès** : http://localhost:2026

### Avancé
#### Mode Sandbox

DeerFlow supporte plusieurs modes d'exécution sandbox :
- **Exécution locale** (exécute le code sandbox directement sur la machine hôte)
- **Exécution Docker** (exécute le code sandbox dans des conteneurs Docker isolés)
- **Exécution Docker avec Kubernetes** (exécute le code sandbox dans des pods Kubernetes via le service provisioner)

En développement Docker, le démarrage des services suit le mode sandbox défini dans `config.yaml`. En mode Local/Docker, `provisioner` n'est pas démarré.

Voir le [Guide de configuration Sandbox](backend/docs/CONFIGURATION.md#sandbox) pour configurer le mode de votre choix.

#### Serveur MCP

DeerFlow supporte des serveurs MCP et des skills configurables pour étendre ses capacités.
Pour les serveurs MCP HTTP/SSE, les flux de tokens OAuth sont supportés (`client_credentials`, `refresh_token`).
Voir le [Guide MCP Server](backend/docs/MCP_SERVER.md) pour les instructions détaillées.

#### Canaux de messagerie

DeerFlow peut recevoir des tâches depuis des applications de messagerie. Les canaux démarrent automatiquement une fois configurés — aucune IP publique n'est requise.

| Canal | Transport | Difficulté |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Facile |
| Slack | Socket Mode | Modérée |
| Feishu / Lark | WebSocket | Modérée |

**Configuration dans `config.yaml` :**

```yaml
channels:
  # LangGraph Server URL (default: http://localhost:2024)
  langgraph_url: http://localhost:2024
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

  # Optional: global session defaults for all mobile channels
  session:
    assistant_id: lead_agent
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

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    allowed_users: []               # empty = allow all

    # Optional: per-channel / per-user session settings
    session:
      assistant_id: mobile_agent
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip_agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true
```

Définissez les clés API correspondantes dans votre fichier `.env` :

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret
```

**Configuration Telegram**

1. Ouvrez une conversation avec [@BotFather](https://t.me/BotFather), envoyez `/newbot`, et copiez le token HTTP API.
2. Définissez `TELEGRAM_BOT_TOKEN` dans `.env` et activez le canal dans `config.yaml`.

**Configuration Slack**

1. Créez une Slack App sur [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.
2. Dans **OAuth & Permissions**, ajoutez les Bot Token Scopes : `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Activez le **Socket Mode** → générez un App-Level Token (`xapp-…`) avec le scope `connections:write`.
4. Dans **Event Subscriptions**, abonnez-vous aux bot events : `app_mention`, `message.im`.
5. Définissez `SLACK_BOT_TOKEN` et `SLACK_APP_TOKEN` dans `.env` et activez le canal dans `config.yaml`.

**Configuration Feishu / Lark**

1. Créez une application sur [Feishu Open Platform](https://open.feishu.cn/) → activez la capacité **Bot**.
2. Ajoutez les permissions : `im:message`, `im:message.p2p_msg:readonly`, `im:resource`.
3. Dans **Events**, abonnez-vous à `im.message.receive_v1` et sélectionnez le mode **Long Connection**.
4. Copiez l'App ID et l'App Secret. Définissez `FEISHU_APP_ID` et `FEISHU_APP_SECRET` dans `.env` et activez le canal dans `config.yaml`.

**Commandes**

Une fois un canal connecté, vous pouvez interagir avec DeerFlow directement depuis le chat :

| Commande | Description |
|---------|-------------|
| `/new` | Démarrer une nouvelle conversation |
| `/status` | Afficher les infos du thread en cours |
| `/models` | Lister les modèles disponibles |
| `/memory` | Consulter la mémoire |
| `/help` | Afficher l'aide |

> Les messages sans préfixe de commande sont traités comme du chat classique — DeerFlow crée un thread et répond de manière conversationnelle.

## Du Deep Research au Super Agent Harness

DeerFlow a démarré comme un framework de Deep Research — et la communauté s'en est emparée. Depuis le lancement, les développeurs l'ont poussé bien au-delà de la recherche : construction de pipelines de données, génération de présentations, mise en place de dashboards, automatisation de workflows de contenu. Des usages qu'on n'avait jamais anticipés.

Ça nous a révélé quelque chose d'important : DeerFlow n'était pas qu'un simple outil de recherche. C'était un **harness** — un runtime qui donne aux agents l'infrastructure nécessaire pour vraiment accomplir du travail.

On l'a donc reconstruit de zéro.

DeerFlow 2.0 n'est plus un framework à assembler soi-même. C'est un super agent harness — clé en main et entièrement extensible. Construit sur LangGraph et LangChain, il embarque tout ce dont un agent a besoin out of the box : un système de fichiers, de la mémoire, des skills, une exécution sandboxée, et la capacité de planifier et de lancer des sub-agents pour les tâches complexes et multi-étapes.

Utilisez-le tel quel. Ou démontez-le et faites-en le vôtre.

## Fonctionnalités principales

### Skills et outils

Les skills sont ce qui permet à DeerFlow de faire *pratiquement n'importe quoi*.

Un Agent Skill standard est un module de capacité structuré — un fichier Markdown qui définit un workflow, des bonnes pratiques et des références vers des ressources associées. DeerFlow est livré avec des skills intégrés pour la recherche, la génération de rapports, la création de présentations, les pages web, la génération d'images et de vidéos, et bien plus. Mais la vraie force réside dans l'extensibilité : ajoutez vos propres skills, remplacez ceux fournis, ou combinez-les en workflows composites.

Les skills sont chargés progressivement — uniquement quand la tâche le nécessite, pas tous en même temps. Ça permet de garder la fenêtre de contexte légère et de bien fonctionner même avec des modèles sensibles au nombre de tokens.

Quand vous installez des archives `.skill` via le Gateway, DeerFlow accepte les métadonnées frontmatter optionnelles standard comme `version`, `author` et `compatibility`, plutôt que de rejeter des skills externes par ailleurs valides.

Les outils suivent la même philosophie. DeerFlow est livré avec un ensemble d'outils de base — recherche web, fetch de pages web, opérations sur les fichiers, exécution bash — et supporte les outils custom via des serveurs MCP et des fonctions Python. Remplacez n'importe quoi. Ajoutez n'importe quoi.

Les suggestions de suivi générées par le Gateway normalisent désormais aussi bien la sortie texte brut du modèle que le contenu riche au format bloc/liste avant de parser la réponse en tableau JSON, de sorte que les wrappers de contenu propres à chaque provider ne suppriment plus silencieusement les suggestions.

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
```

#### Intégration Claude Code

Le skill `claude-to-deerflow` vous permet d'interagir avec une instance DeerFlow en cours d'exécution directement depuis [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Envoyez des tâches de recherche, vérifiez le statut, gérez les threads — le tout sans quitter le terminal.

**Installer le skill** :

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Assurez-vous ensuite que DeerFlow tourne (par défaut sur `http://localhost:2026`) et utilisez la commande `/claude-to-deerflow` dans Claude Code.

**Ce que vous pouvez faire** :
- Envoyer des messages à DeerFlow et recevoir des réponses en streaming
- Choisir le mode d'exécution : flash (rapide), standard, pro (planification), ultra (sub-agents)
- Vérifier la santé de DeerFlow, lister les modèles/skills/agents
- Gérer les threads et l'historique des conversations
- Upload des fichiers pour analyse

**Variables d'environnement** (optionnel, pour des endpoints custom) :

```bash
DEERFLOW_URL=http://localhost:2026            # Unified proxy base URL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

Voir [`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md) pour la référence API complète.

### Sub-Agents

Les tâches complexes tiennent rarement en une seule passe. DeerFlow les décompose.

L'agent principal peut lancer des sub-agents à la volée — chacun avec son propre contexte délimité, ses outils et ses conditions d'arrêt. Les sub-agents s'exécutent en parallèle quand c'est possible, remontent des résultats structurés, et l'agent principal synthétise le tout en une sortie cohérente.

C'est comme ça que DeerFlow gère les tâches qui prennent de quelques minutes à plusieurs heures : une tâche de recherche peut se déployer en une dizaine de sub-agents, chacun explorant un angle différent, puis converger vers un seul rapport — ou un site web — ou un jeu de slides avec des visuels générés. Un seul harness, de nombreuses mains.

### Sandbox et système de fichiers

DeerFlow ne se contente pas de *parler* de faire les choses. Il dispose de son propre ordinateur.

Chaque tâche s'exécute dans un conteneur Docker isolé avec un système de fichiers complet — skills, workspace, uploads, outputs. L'agent lit, écrit et édite des fichiers. Il exécute des commandes bash et du code. Il visualise des images. Le tout sandboxé, le tout auditable, zéro contamination entre les sessions.

C'est la différence entre un chatbot avec accès à des outils et un agent doté d'un véritable environnement d'exécution.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

### Context Engineering

**Contexte isolé des Sub-Agents** : chaque sub-agent s'exécute dans son propre contexte isolé. Il ne peut voir ni le contexte de l'agent principal, ni celui des autres sub-agents. L'objectif est de garantir que chaque sub-agent reste concentré sur sa tâche sans être parasité par des informations non pertinentes.

**Résumé** : au sein d'une session, DeerFlow gère le contexte de manière agressive — en résumant les sous-tâches terminées, en déchargeant les résultats intermédiaires vers le système de fichiers, en compressant ce qui n'est plus immédiatement pertinent. Ça lui permet de rester efficace sur des tâches longues et multi-étapes sans faire exploser la fenêtre de contexte.

### Mémoire à long terme

La plupart des agents oublient tout dès qu'une conversation se termine. DeerFlow, lui, se souvient.

D'une session à l'autre, DeerFlow construit une mémoire persistante de votre profil, de vos préférences et de vos connaissances accumulées. Plus vous l'utilisez, mieux il vous connaît — votre style d'écriture, votre stack technique, vos workflows récurrents. La mémoire est stockée localement et reste sous votre contrôle.

Les mises à jour de la mémoire ignorent désormais les entrées de faits en double au moment de l'application, de sorte que les préférences et le contexte répétés ne s'accumulent plus indéfiniment entre les sessions.

## Modèles recommandés

DeerFlow est agnostique en termes de modèle — il fonctionne avec n'importe quel LLM implémentant l'API compatible OpenAI. Cela dit, il offre de meilleures performances avec des modèles qui supportent :

- **De longues fenêtres de contexte** (100k+ tokens) pour la recherche approfondie et les tâches multi-étapes
- **Des capacités de raisonnement** pour la planification adaptative et la décomposition de tâches complexes
- **Des entrées multimodales** pour la compréhension d'images et de vidéos
- **Un usage fiable des outils (tool use)** pour des appels de fonctions et des sorties structurées fiables

## Client Python intégré

DeerFlow peut être utilisé comme bibliothèque Python intégrée sans lancer l'ensemble des services HTTP. Le `DeerFlowClient` fournit un accès direct in-process à toutes les capacités d'agent et de Gateway, en retournant les mêmes schémas de réponse que l'API HTTP Gateway. Le HTTP Gateway expose également `DELETE /api/threads/{thread_id}` pour supprimer les données de thread locales gérées par DeerFlow après la suppression du thread LangGraph :

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

Toutes les méthodes retournant des dicts sont validées en CI contre les modèles de réponse Pydantic du Gateway (`TestGatewayConformance`), garantissant que le client intégré reste synchronisé avec les schémas de l'API HTTP. Voir `backend/packages/harness/deerflow/client.py` pour la documentation API complète.

## Documentation

- [Guide de contribution](CONTRIBUTING.md) - Mise en place de l'environnement de développement et workflow
- [Guide de configuration](backend/docs/CONFIGURATION.md) - Instructions d'installation et de configuration
- [Vue d'ensemble de l'architecture](backend/CLAUDE.md) - Détails de l'architecture technique
- [Architecture backend](backend/README.md) - Architecture backend et référence API

## ⚠️ Avertissement de sécurité

### Un déploiement inapproprié peut introduire des risques de sécurité

DeerFlow dispose de capacités clés à hauts privilèges, notamment **l'exécution de commandes système, les opérations sur les ressources et l'invocation de logique métier**. Il est conçu par défaut pour être **déployé dans un environnement local de confiance (accessible uniquement via l'interface de loopback 127.0.0.1)**. Si vous déployez l'agent dans des environnements non fiables — tels que des réseaux LAN, des serveurs cloud publics ou d'autres environnements accessibles depuis plusieurs terminaux — sans mesures de sécurité strictes, cela peut introduire des risques, notamment :

- **Invocation non autorisée** : les fonctionnalités de l'agent pourraient être découvertes par des tiers non autorisés ou des scanners malveillants, déclenchant des requêtes non autorisées en masse qui exécutent des opérations à haut risque (commandes système, lecture/écriture de fichiers), pouvant causer de graves conséquences.
- **Risques juridiques et de conformité** : si l'agent est utilisé illégalement pour mener des cyberattaques, du vol de données ou d'autres activités illicites, cela peut entraîner des responsabilités juridiques et des risques de conformité.

### Recommandations de sécurité

**Note : nous recommandons fortement de déployer DeerFlow dans un environnement réseau local de confiance.** Si vous avez besoin d'un déploiement multi-appareils ou multi-réseaux, vous devez mettre en place des mesures de sécurité strictes, par exemple :

- **Liste blanche d'IP** : utilisez `iptables`, ou déployez des pare-feux matériels / commutateurs avec ACL, pour **configurer des règles de liste blanche d'IP** et refuser l'accès à toutes les autres adresses IP.
- **Passerelle d'authentification** : configurez un proxy inverse (ex. nginx) et **activez une authentification forte en amont**, bloquant tout accès non authentifié.
- **Isolation réseau** : si possible, placez l'agent et les appareils de confiance dans le **même VLAN dédié**, isolé des autres équipements réseau.
- **Restez informé** : continuez à suivre les mises à jour de sécurité du projet DeerFlow.

## Contribuer

Les contributions sont les bienvenues ! Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour la mise en place de l'environnement de développement, le workflow et les conventions.

La couverture de tests de régression inclut la détection du mode sandbox Docker et les tests de gestion du kubeconfig-path du provisioner dans `backend/tests/`.

## Licence

Ce projet est open source et disponible sous la [Licence MIT](./LICENSE).

## Remerciements

DeerFlow est construit sur le travail remarquable de la communauté open source. Nous sommes profondément reconnaissants envers tous les projets et contributeurs dont les efforts ont rendu DeerFlow possible. Nous nous tenons véritablement sur les épaules de géants.

Nous tenons à exprimer notre sincère gratitude aux projets suivants pour leurs contributions inestimables :

- **[LangChain](https://github.com/langchain-ai/langchain)** : leur excellent framework propulse nos interactions LLM et nos chaînes, permettant une intégration et des fonctionnalités fluides.
- **[LangGraph](https://github.com/langchain-ai/langgraph)** : leur approche innovante de l'orchestration multi-agents a été déterminante pour les workflows sophistiqués de DeerFlow.

Ces projets illustrent le pouvoir transformateur de la collaboration open source, et nous sommes fiers de bâtir sur leurs fondations.

### Contributeurs principaux

Un grand merci aux auteurs principaux de `DeerFlow`, dont la vision, la passion et le dévouement ont donné vie à ce projet :

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Votre engagement sans faille et votre expertise sont le moteur du succès de DeerFlow. Nous sommes honorés de vous avoir à la barre de cette aventure.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
