import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

void test("desktop-dev passes an absolute config.desktop.yaml path into shared services", async () => {
  const makefile = await fs.readFile(path.resolve("Makefile"), "utf8");

  assert.match(
    makefile,
    /desktop-dev:\n\t@DEER_FLOW_CONFIG_PATH=\$\(CURDIR\)\/config\.desktop\.yaml \$\(MAKE\) dev-daemon-pro/,
  );
});
