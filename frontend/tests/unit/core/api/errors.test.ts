import { describe, expect, it } from "@rstest/core";

import {
  GatewayApiError,
  parseGatewayApiError,
  throwGatewayApiError,
} from "@/core/api/errors";

function response(status: number, body: unknown): Response {
  return {
    ok: false,
    status,
    statusText: "Error",
    json: async () => {
      if (body === undefined) {
        throw new SyntaxError("Unexpected end of JSON input");
      }
      return body;
    },
  } as unknown as Response;
}

async function caught(promise: Promise<unknown>): Promise<GatewayApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(GatewayApiError);
    expect(error).toBeInstanceOf(Error);
    return error as GatewayApiError;
  }
  throw new Error("expected a rejection");
}

describe("throwGatewayApiError", () => {
  it("keeps a string detail as the message (channels and other callers unchanged)", async () => {
    const error = await caught(
      throwGatewayApiError(
        response(400, { detail: "Channel is not configured" }),
        "fallback",
      ),
    );
    expect(error.message).toBe("Channel is not configured");
    expect(error.code).toBeNull();
    expect(error.params).toEqual({});
    expect(error.status).toBe(400);
    expect(error.rawMessage).toBe("Channel is not configured");
  });

  it("exposes code, params and status for a coded detail", async () => {
    const error = await caught(
      throwGatewayApiError(
        response(422, {
          detail: {
            code: "interval_too_short",
            message: "every_seconds must be at least 60",
            params: { min_seconds: 60 },
          },
        }),
        "fallback",
      ),
    );
    expect(error.message).toBe("every_seconds must be at least 60");
    expect(error.code).toBe("interval_too_short");
    expect(error.params).toEqual({ min_seconds: 60 });
    expect(error.status).toBe(422);
    expect(error.rawMessage).toBe("every_seconds must be at least 60");
  });

  it("treats a coded detail without params as empty params", () => {
    const error = parseGatewayApiError(
      {
        detail: { code: "task_not_found", message: "Scheduled task not found" },
      },
      404,
      "fallback",
    );
    expect(error.code).toBe("task_not_found");
    expect(error.params).toEqual({});
  });

  it("maps FastAPI's validation list to invalid_request with the fallback message", async () => {
    const error = await caught(
      throwGatewayApiError(
        response(422, {
          detail: [
            {
              loc: ["body", "max_runs"],
              msg: "Input should be a valid integer",
              type: "int_parsing",
            },
          ],
        }),
        "Failed to update scheduled task",
      ),
    );
    expect(error.message).toBe("Failed to update scheduled task");
    expect(error.code).toBe("invalid_request");
    expect(error.rawMessage).toBe("Input should be a valid integer");
  });

  it("falls back when the body is empty or not JSON", async () => {
    const empty = await caught(
      throwGatewayApiError(response(502, {}), "Failed to load"),
    );
    expect(empty.message).toBe("Failed to load");
    expect(empty.code).toBeNull();
    expect(empty.rawMessage).toBe("");

    const notJson = await caught(
      throwGatewayApiError(response(502, undefined), "Failed to load"),
    );
    expect(notJson.message).toBe("Failed to load");
    expect(notJson.status).toBe(502);
  });
});
