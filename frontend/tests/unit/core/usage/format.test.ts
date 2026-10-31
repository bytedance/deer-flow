import { expect, test } from "@rstest/core";

import { modelUsageRows } from "@/core/usage/format";

test("model breakdown sorts by usage without mutating server data", () => {
  const models = {
    flash: {
      tokens: 30,
      runs: 1,

      input_tokens: 20,
      cache_read_tokens: 10,
    },
    pro: {
      tokens: 50,
      runs: 2,

      input_tokens: 40,
      cache_read_tokens: 0,
    },
  };
  expect(modelUsageRows(models).map((row) => row.name)).toEqual([
    "pro",
    "flash",
  ]);
  expect(Object.keys(models)).toEqual(["flash", "pro"]);
});
