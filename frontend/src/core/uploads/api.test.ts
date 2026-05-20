import assert from "node:assert/strict";
import test from "node:test";

process.env.SKIP_ENV_VALIDATION = "1";
process.env.NEXT_PUBLIC_BACKEND_BASE_URL = "http://127.0.0.1:8001";

const { buildDeleteUploadedFileUrl } = await import(
  new URL("./api.ts", import.meta.url).href
);

void test("encodes uploaded filenames in delete URLs", () => {
  const url = buildDeleteUploadedFileUrl(
    "thread-123",
    "report (final) #1?.pdf",
  );

  assert.equal(
    url,
    "http://127.0.0.1:8001/api/threads/thread-123/uploads/report%20(final)%20%231%3F.pdf",
  );
});
