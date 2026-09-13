# 🦌 DeerFlow - 2.0

[English](./README.md) | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md) | [Italiano](./README_it.md)


[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

> Il 28 febbraio 2026, DeerFlow ha conquistato il 🏆 primo posto su GitHub Trending dopo il lancio della versione 2. Grazie di cuore alla nostra community: questo risultato è merito vostro! 💪🔥

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) è un **super agent harness** open-source che orchestra **sub-agent**, **memoria** e **sandbox** per affrontare attività molto diverse, da quelle rapide a quelle che richiedono ore.

> [!NOTE]
> **DeerFlow 2.0 è stato riscritto da zero.** Non condivide codice con la v1. Se cerchi il framework Deep Research originale, è mantenuto nel branch [`1.x`](https://github.com/bytedance/deer-flow/tree/1.x).

## Sito ufficiale

Scopri di più e guarda demo reali sul [**sito ufficiale**](https://deerflow.tech).

## Piano Coding di ByteDance Volcengine

- Consigliamo fortemente di usare Doubao-Seed-2.0-Code, DeepSeek v3.2 e Kimi 2.5 per eseguire DeerFlow
- [Scopri di più](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [Per sviluppatori nella Cina continentale](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow integra InfoQuest, la suite intelligente di ricerca e crawling sviluppata da BytePlus:  
[InfoQuest (include esperienza online gratuita)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

---

## Indice

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Sito ufficiale](#sito-ufficiale)
  - [Piano Coding di ByteDance Volcengine](#piano-coding-di-bytedance-volcengine)
  - [InfoQuest](#infoquest)
  - [Configurazione rapida in una riga (per agent)](#configurazione-rapida-in-una-riga-per-agent)
  - [Avvio rapido](#avvio-rapido)
  - [Da Deep Research a Super Agent Harness](#da-deep-research-a-super-agent-harness)
  - [Funzionalità principali](#funzionalità-principali)
  - [Modelli consigliati](#modelli-consigliati)
  - [Client Python embedded](#client-python-embedded)
  - [Documentazione](#documentazione)
  - [⚠️ Avviso di sicurezza](#️-avviso-di-sicurezza)
  - [Contribuire](#contribuire)
  - [Licenza](#licenza)
  - [Ringraziamenti](#ringraziamenti)
  - [Cronologia stelle](#cronologia-stelle)

## Configurazione rapida in una riga (per agent)

Se usi Claude Code, Codex, Cursor, Windsurf o altri coding agent, puoi passare queste istruzioni in un’unica frase:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

Questo prompt è pensato per i coding agent: clona la repo se necessario, preferisce Docker quando disponibile e si ferma indicando il prossimo comando esatto e l’eventuale configurazione mancante.

## Avvio rapido

### Configurazione

1. **Clona la repository DeerFlow**

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
```

2. **Esegui il setup guidato**

Dalla root del progetto (`deer-flow/`):

```bash
make setup
```

Si apre una procedura interattiva che ti guida nella scelta del provider LLM, della ricerca web opzionale e delle preferenze di esecuzione/sicurezza (sandbox mode, accesso bash, strumenti di scrittura file).

Puoi eseguire `make doctor` in qualsiasi momento per verificare la configurazione e ottenere suggerimenti di correzione.

> **Configurazione avanzata/manuale**: se preferisci modificare direttamente `config.yaml`, esegui `make config` per copiare il template completo.  
> Consulta `config.example.yaml` come riferimento completo.

### Esecuzione applicazione

#### Opzione 1: Docker (consigliata)

**Sviluppo** (hot-reload, mount del sorgente):

```bash
make docker-init
make docker-start
```

**Produzione**:

```bash
make up
make down
```

Accesso: http://localhost:2026

#### Opzione 2: Sviluppo locale

1. Verifica prerequisiti:
```bash
make check
```

2. Installa dipendenze:
```bash
make install
```

3. Avvia i servizi:
```bash
make dev
```

Accesso: http://localhost:2026

## Da Deep Research a Super Agent Harness

DeerFlow è nato come framework Deep Research, ma la community lo ha portato ben oltre.  
Gli sviluppatori lo hanno usato per pipeline dati, generazione presentazioni, automazioni e flussi complessi.

Per questo DeerFlow 2.0 è stato ripensato da zero: non è più solo un framework da assemblare, ma un **harness completo** per agenti, estensibile e pronto all’uso.

## Funzionalità principali

### Skills & Tools

Le skill sono moduli di capacità strutturati (file Markdown) che definiscono workflow, best practice e risorse correlate.

Le skill vengono caricate progressivamente solo quando servono, così il contesto resta snello anche con modelli sensibili ai token.

Gli strumenti seguono la stessa filosofia: ricerca web, fetch web, operazioni su file, esecuzione bash e supporto a tool personalizzati via MCP o funzioni Python.

### Integrazione con Claude Code

La skill `claude-to-deerflow` permette di interagire con DeerFlow direttamente da Claude Code.

Installazione:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Poi assicurati che DeerFlow sia in esecuzione (default `http://localhost:2026`) e usa il comando `/claude-to-deerflow`.

### Sub-agent

DeerFlow può scomporre task complessi in sub-agent, ciascuno con contesto, strumenti e condizioni di termine dedicate.  
Quando possibile, i sub-agent lavorano in parallelo e convergono in un risultato unico e strutturato.

### Sandbox & file system

Ogni task ha un proprio ambiente esecutivo con filesystem completo (skills, workspace, upload, output).  
Con `AioSandboxProvider`, l’esecuzione shell avviene in container isolati.  
Con `LocalSandboxProvider`, gli strumenti file usano directory per thread sull’host, mentre il bash host è disabilitato di default.

### Context engineering

- **Contesto isolato per sub-agent**
- **Riassunto aggressivo dei passaggi completati**
- **Recupero rigoroso delle tool-call interrotte**

### Memoria a lungo termine

Tra sessioni, DeerFlow mantiene memoria persistente di profilo, preferenze e conoscenze accumulate.

## Modelli consigliati

DeerFlow è model-agnostic e funziona con qualsiasi LLM compatibile OpenAI API.  
Rende al meglio con modelli che supportano:

- finestre di contesto lunghe (100k+ token)
- capacità di reasoning
- input multimodali
- uso strumenti affidabile

## Client Python embedded

DeerFlow può essere usato anche come libreria Python embedded, senza avviare tutti i servizi HTTP.

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

response = client.chat("Analyze this paper for me", thread_id="my-thread")

for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])
```

## Documentazione

- [Guida ai contributi](CONTRIBUTING.md)
- [Guida configurazione](backend/docs/CONFIGURATION.md)
- [Panoramica architettura](backend/CLAUDE.md)
- [Architettura backend](backend/README.md)

## ⚠️ Avviso di sicurezza

### Un deployment improprio può introdurre rischi

DeerFlow include funzionalità ad alto privilegio (esecuzione comandi di sistema, operazioni su risorse, invocazione logica di business) ed è progettato di default per ambienti locali fidati.

Rischi principali:
- invocazioni non autorizzate
- uso improprio malevolo
- rischi legali/compliance

### Raccomandazioni

Se devi esporre DeerFlow oltre una rete fidata locale, applica misure rigorose:

- allowlist IP (iptables / ACL)
- reverse proxy con autenticazione forte
- isolamento di rete (VLAN dedicata)
- aggiornamento continuo delle patch di sicurezza

## Contribuire

I contributi sono benvenuti!  
Consulta [CONTRIBUTING.md](CONTRIBUTING.md) per setup, workflow e linee guida.

## Licenza

Progetto open source sotto [MIT License](./LICENSE).

## Ringraziamenti

DeerFlow è costruito sulle fondamenta della community open source.  
Ringraziamo in particolare:

- [LangChain](https://github.com/langchain-ai/langchain)
- [LangGraph](https://github.com/langchain-ai/langgraph)

### Contributor principali

- [Daniel Walnut](https://github.com/hetaoBackend/)
- [Henry Li](https://github.com/magiccube/)

## Cronologia stelle

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
