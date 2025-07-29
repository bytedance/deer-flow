// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { z } from "zod";

export const MCPConfigSchema = z.object({
  mcpServers: z.record(
    z.union(
      [
        z.object({
          command: z.string({
            message: "`command` must be a string",
          }),
          args: z
            .array(z.string(), {
              message: "`args` must be an array of strings",
            })
            .optional(),
          env: z
            .record(z.string(), {
              message: "`env` must be an object of key-value pairs",
            })
            .optional(),
        }),
        z.object({
          url: z
            .string({
              message:
                "`url` must be a valid URL starting with http:// or https://",
            })
            .refine(
              (value) => {
                try {
                  const url = new URL(value);
                  return url.protocol === "http:" || url.protocol === "https:";
                } catch {
                  return false;
                }
              },
              {
                message:
                  "`url` must be a valid URL starting with http:// or https://",
              },
            ),
          env: z
            .record(z.string(), {
              message: "`env` must be an object of key-value pairs",
            })
            .optional(),
          transport: z
            .enum(["sse", "streamable_http"], {
              message: "transport must be either sse or streamable_http"
            })
            .default("sse"),
        }),
      ],
      {
        message: "Invalid server type",
      },
    ),
  ),
});
