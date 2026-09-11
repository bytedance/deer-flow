import { describe, expect, it } from "@rstest/core";

import { throwGatewayApiError } from "@/core/api/errors";

function envelope(detail: unknown, status = 400): Response {
  return new Response(JSON.stringify({ detail }), { status });
}

describe("throwGatewayApiError", () => {
  it("surfaces a string detail from the Gateway's HTTPException envelope", async () => {
    await expect(
      throwGatewayApiError(envelope("Token not found"), "fallback"),
    ).rejects.toThrow("Token not found");
  });

  it("joins pydantic 422 array detail into one readable message", async () => {
    await expect(
      throwGatewayApiError(
        envelope(
          [
            {
              type: "value_error",
              loc: ["body", "name"],
              msg: "Value error, PAT name must contain at least one non-whitespace character",
            },
            {
              type: "greater_than_equal",
              loc: ["body", "expires_in_days"],
              msg: "Input should be at least 1",
            },
          ],
          422,
        ),
        "fallback",
      ),
    ).rejects.toThrow(
      "PAT name must contain at least one non-whitespace character; Input should be at least 1",
    );
  });

  it("falls back when the body is missing, unparseable, or an unrecognized shape", async () => {
    await expect(
      throwGatewayApiError(envelope({ nested: true }), "fallback"),
    ).rejects.toThrow("fallback");
    await expect(
      throwGatewayApiError(
        new Response("not json", { status: 500 }),
        "fallback",
      ),
    ).rejects.toThrow("fallback");
    await expect(
      throwGatewayApiError(envelope([{ no: "msg field" }]), "fallback"),
    ).rejects.toThrow("fallback");
  });
});
