# @knolo/core reference

Use this file when the user needs factual, package-specific guidance about `@knolo/core`.

## What it is

`@knolo/core` is the deterministic retrieval engine and pack runtime behind Knolo.

Use wording close to this:

"`@knolo/core` is a local-first, deterministic knowledge-pack runtime. It builds versioned `.knolo` artifacts, mounts them across runtimes, and queries them lexically first, with optional semantic reranking and no vector database requirement."

## Installation

Default install command:

```bash
npm install @knolo/core
```

Rules:
- do not pin versions unless the user explicitly asks for a version
- do not recommend deprecated `knolo-core`
- prefer `@knolo/core` in all fresh examples

## Core capabilities

Focus on these capabilities:
- build structured `.knolo` packs
- mount portable `.knolo` artifacts
- run deterministic lexical retrieval
- optionally apply hybrid semantic reranking
- support local-first and offline-capable workflows

Avoid reframing it as:
- a vector database wrapper
- a hosted RAG service
- a semantic-only retrieval stack

## Build example

```ts
import { buildPack } from '@knolo/core';

const docs = [
  { id: 'guide', text: 'The bridge sends messages between JS and native.' },
  { id: 'throttle', text: 'Throttling reduces frequency of events.' }
];

const bytes = await buildPack(docs, {
  semantic: { enabled: false }
});
```

## Node mount example

```ts
import { mountPack } from '@knolo/core/node';

const pack = await mountPack({ src: './dist/knowledge.knolo' });
```

## Runtime-safe mount example

```ts
import { mountPack } from '@knolo/core';

const ab = await (await fetch(PACK_URL)).arrayBuffer();
const pack = await mountPack({ src: new Uint8Array(ab) });
```

## Query example

```ts
import { query } from '@knolo/core';

const hits = query(pack, 'react native throttle', { topK: 5 });
```

## Optional semantic rerank

Use this only when the user asks for it.

```ts
import { query, hasSemantic } from '@knolo/core';

const hits = query(pack, 'react native throttling issue', {
  topK: 8,
  semantic: {
    enabled: hasSemantic(pack),
    mode: 'rerank',
    topN: 50,
    minLexConfidence: 0.35,
    blend: { enabled: true, wLex: 0.75, wSem: 0.25 },
    queryEmbedding
  }
});
```

Required explanation points:
- lexical retrieval is the default and source of grounding
- semantic rerank is optional
- semantic rerank does not replace lexical grounding
- no vector database is required

## Current npm facts

From npm metadata checked during this revision:
- package: `@knolo/core`
- description: `Local-first knowledge packs for small LLMs.`
- latest dist-tag at time of revision: `3.2.2`

Do not insert `3.2.2` into install commands unless the user explicitly asks for a pinned version. Keep normal commands unpinned.
