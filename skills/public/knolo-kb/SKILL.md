---
name: knolo-kb
description: "use for knolo tasks in deerflow or other javascript/typescript repos when the user needs to install, explain, build with, mount, query, troubleshoot, or migrate to @knolo/core. prefer this skill when the user mentions @knolo/core, knolo, .knolo packs, deterministic lexical retrieval, local-first knowledge packs, browser or react native mounting, optional semantic reranking, or replacing deprecated knolo-core with the current scoped package. focus on @knolo/core only unless the user explicitly asks about other knolo packages."
---

# Knolo KB

Use this skill to help users adopt `@knolo/core` with the smallest reliable setup.

Default stance:
- center answers on `@knolo/core`
- prefer deterministic lexical retrieval first
- treat semantic reranking as optional
- do not require a vector database
- keep workflows local-first and offline-capable where possible

Package rules:
- Use `@knolo/core` as the primary and default Knolo package.
- Treat unscoped `knolo-core` as deprecated and replace it with `@knolo/core`.
- Do not invent, pin, or guess package versions in commands or examples unless the user explicitly asks for a version.
- When the user asks for install commands, use unpinned commands such as `npm install @knolo/core`.
- Do not introduce other Knolo packages unless the user explicitly asks for them.

## Workflow

Start by deciding which of these jobs the user needs.

### 1. Install or migrate to `@knolo/core`
Use this when the user wants to add Knolo to an existing repo or replace deprecated `knolo-core`.

Steps:
1. Recommend the smallest install first:
   ```bash
   npm install @knolo/core
   ```
2. If the repo currently uses `knolo-core`, tell the user to:
   - replace install commands with `npm install @knolo/core`
   - replace imports from `knolo-core` with imports from `@knolo/core` or `@knolo/core/node` as appropriate
3. Keep the first integration path simple: docs in, `.knolo` pack out, mount, then query.

### 2. Build a `.knolo` pack
Use this when the user has local docs, markdown, JSON docs, or another small knowledge corpus.

Default approach:
1. Build a deterministic lexical pack first.
2. Validate that the pack mounts and queries correctly.
3. Only discuss semantic options after the lexical path is working.

Minimal example:

```ts
import { buildPack } from '@knolo/core';

const docs = [
  { id: 'intro', text: 'Knolo builds deterministic knowledge packs.' },
  { id: 'mount', text: 'Use @knolo/core/node for local file paths in Node.' }
];

const bytes = await buildPack(docs, {
  semantic: { enabled: false }
});
```

### 3. Mount a pack
Use the runtime-specific entrypoint.

#### Node.js local filesystem path

```ts
import { mountPack } from '@knolo/core/node';

const pack = await mountPack({ src: './dist/knowledge.knolo' });
```

#### Browser, URL, Expo, or React Native bytes

```ts
import { mountPack } from '@knolo/core';

const ab = await (await fetch(PACK_URL)).arrayBuffer();
const pack = await mountPack({ src: new Uint8Array(ab) });
```

Rules:
- Use `@knolo/core/node` only for local filesystem paths in Node.js.
- Use `@knolo/core` for runtime-safe mounting from URL, `Uint8Array`, or `ArrayBuffer`.

### 4. Query a pack
Use lexical-first querying as the default answer path.

```ts
import { query } from '@knolo/core';

const hits = query(pack, 'debounce vs throttle', { topK: 5 });

for (const hit of hits) {
  console.log(hit.text);
  console.log(hit.metadata);
}
```

When explaining results, emphasize:
- deterministic lexical retrieval
- stable and reproducible behavior
- no embedding dependency for the default path

### 5. Optional semantic rerank
Use this only when the user asks for better ranking quality or already has embeddings.

Rules:
- semantic runs after lexical retrieval
- semantic never replaces lexical grounding
- no vector database is required
- keep the lexical-first explanation explicit

Example:

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

## DeerFlow guidance

Inside DeerFlow, bias toward the easiest first success:
- install `@knolo/core`
- build a pack from local docs
- mount the pack
- answer questions from the pack

Good user phrasing that should trigger this skill:
- `use @knolo/core to build a .knolo pack from this docs folder`
- `replace knolo-core with @knolo/core`
- `mount this .knolo file and query it`
- `show the minimal lexical-first knolo setup`

## Response style

When answering:
- give the smallest working `@knolo/core` setup first
- clearly separate required vs optional features
- call out deprecated `knolo-core` immediately when relevant
- avoid discussing unrelated Knolo packages unless the user asked for them
- keep examples directly runnable
- do not claim a vector database is needed

## Resources

See `references/knolo-core-reference.md` for package facts, wording, install guidance, and copy-ready examples focused only on `@knolo/core`.
