# Search query evaluation

**Backstory** — The scenario describing one person's information need. It is the unit of evaluation.

**Human reference query** — One human-written search query associated with a backstory. Each listed reference carries equal weight within its backstory.

**First search query** — The first `web_search` query in the lead agent's checkpoint after zero or more preparatory tool batches, in checkpoint tool-call order. Subagents are disabled during capture.

**Coverage** — The fraction of attempted backstories for which a first search query received both semantic and lexical similarity scores.

**Decision limit** — The maximum number of assistant checkpoints inspected for a backstory. A case that reaches this bound without a search or final answer remains unscored.

**Runtime evidence** — The Gateway's record of the effective model, sampling parameters and assembly fingerprints for one continuation run, saved alongside deployment artifact hashes and context snapshots.
