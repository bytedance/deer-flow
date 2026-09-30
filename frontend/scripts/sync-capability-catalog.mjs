import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

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
      fileURLToPath(new URL("../package.json", import.meta.url)),
    )),
    parser: "json",
  }),
);
