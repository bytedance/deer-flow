import { readFile, writeFile } from "node:fs/promises";

import { format, resolveConfig } from "prettier";

const source = new URL(
  "../../backend/packages/harness/deerflow/capabilities/builtin.json",
  import.meta.url,
);
const destination = new URL(
  "../src/core/capabilities/builtin.demo.json",
  import.meta.url,
);
const catalog = JSON.parse(await readFile(source, "utf8"));
await writeFile(
  destination,
  await format(JSON.stringify(catalog), {
    ...(await resolveConfig(
      new URL("../package.json", import.meta.url).pathname,
    )),
    parser: "json",
  }),
);
