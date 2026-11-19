import { expect, rs, test } from "@rstest/core";

import { resolveConversationActions } from "@/core/extensions/actions";
import type { FrontendExtension } from "@/core/extensions/contracts";
import { enUS } from "@/core/i18n";

for (const callback of ["factory", "availability", "thenable"]) {
  test(`contains rejected asynchronous ${callback} without an unhandled rejection`, async () => {
    const warning = rs
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    try {
      const rejected = () => Promise.reject(new Error("invalid async plugin"));
      const extension = {
        conversationActions:
          callback === "factory"
            ? rejected
            : () => ({
                label: "Broken",
                icon: "bookmark",
                actions: [
                  {
                    id: "save",
                    label: "Save",
                    icon: "bookmark",
                    execute: async () => undefined,
                    available:
                      callback === "thenable"
                        ? () => ({
                            then: (
                              _resolve: unknown,
                              reject: (error: Error) => void,
                            ) => reject(new Error("invalid thenable")),
                          })
                        : rejected,
                  },
                ],
              }),
      } as unknown as FrontendExtension;
      expect(
        resolveConversationActions(
          extension,
          {
            namespace: "broken",
            module: null,
            entry: null,
            title: "Broken",
            description: "",
            settings: {},
          },
          enUS,
          "en-US",
        ),
      ).toBeUndefined();
      // Give rejected promises a full event-loop turn. Rstest fails on unhandled rejections.
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(warning).toHaveBeenCalledTimes(1);
    } finally {
      warning.mockRestore();
    }
  });
}
