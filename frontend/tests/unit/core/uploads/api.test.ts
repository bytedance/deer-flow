import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { deleteUploadedFile, uploadFiles } from "@/core/uploads/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Error" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

async function uploadError(response: Response): Promise<Error> {
  mockedFetch.mockResolvedValueOnce(response);

  let thrown: unknown;
  try {
    await uploadFiles("thread-1", []);
  } catch (error) {
    thrown = error;
  }

  expect(thrown).toBeInstanceOf(Error);
  return thrown as Error;
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("uploads api", () => {
  test("preserves string error details", async () => {
    const error = await uploadError(
      jsonResponse(413, { detail: "File exceeds the upload limit" }),
    );

    expect(error.message).toBe("File exceeds the upload limit");
  });

  test("formats FastAPI validation error details", async () => {
    const error = await uploadError(
      jsonResponse(422, {
        detail: [
          {
            type: "missing",
            loc: ["body", "files"],
            msg: "Field required",
            input: null,
          },
          {
            type: "value_error",
            loc: ["body", "files", 0],
            msg: "File is empty",
            input: "",
          },
        ],
      }),
    );

    expect(error.message).toBe(
      "body.files: Field required; body.files.0: File is empty",
    );
    expect(error.message).not.toContain("[object Object]");
  });

  test("serializes object error details", async () => {
    const error = await uploadError(
      jsonResponse(400, {
        detail: { code: "invalid_archive", reason: "Archive is corrupt" },
      }),
    );

    expect(error.message).toBe(
      '{"code":"invalid_archive","reason":"Archive is corrupt"}',
    );
    expect(error.message).not.toContain("[object Object]");
  });

  test.each([
    [
      "object",
      { msg: "Archive rejected", code: "invalid_archive", retryable: false },
      '{"msg":"Archive rejected","code":"invalid_archive","retryable":false}',
    ],
    [
      "array",
      [{ msg: "Archive rejected", code: "invalid_archive", retryable: false }],
      '[{"msg":"Archive rejected","code":"invalid_archive","retryable":false}]',
    ],
  ])(
    "serializes a generic %s detail containing msg without a validation loc",
    async (_label, detail, expected) => {
      const error = await uploadError(jsonResponse(400, { detail }));

      expect(error.message).toBe(expected);
      expect(error.message).not.toContain("[object Object]");
    },
  );

  test.each([
    ["missing", {}],
    ["null", { detail: null }],
    ["blank string", { detail: "   " }],
    ["empty array", { detail: [] }],
    ["empty object", { detail: {} }],
    ["unexpected scalar", { detail: 42 }],
  ])("uses the upload fallback for %s detail", async (_label, body) => {
    const error = await uploadError(jsonResponse(400, body));

    expect(error.message).toBe("Upload failed");
  });

  test("uses the upload fallback for non-JSON responses", async () => {
    const error = await uploadError(
      new Response("Bad Gateway", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    expect(error.message).toBe("Upload failed");
  });

  test("encodes uploaded filenames in delete request paths", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        message: "Deleted report#1?.txt",
      }),
    );

    await expect(
      deleteUploadedFile("thread-1", "report#1?.txt"),
    ).resolves.toEqual({
      success: true,
      message: "Deleted report#1?.txt",
    });

    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/threads/thread-1/uploads/report%231%3F.txt",
      { method: "DELETE" },
    );
  });
});
