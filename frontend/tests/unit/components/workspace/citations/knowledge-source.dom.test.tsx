import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ArtifactLink } from "@/components/workspace/citations/artifact-link";
import {
  KnowledgeCitationLink,
  KnowledgeSourcesPanel,
  KnowledgeSourcesProvider,
} from "@/components/workspace/citations/knowledge-source";
import { createMarkdownLinkComponent } from "@/components/workspace/messages/markdown-link";
import { I18nProvider } from "@/core/i18n/context";

const id = "0123456789abcdef0123456789abcdef-1";
const href = `#knowledge-${id}`;
const messages = [
  {
    type: "tool",
    name: "knowledge_search",
    content: "retrieved",
    tool_call_id: "call",
    artifact: {
      knowledge_sources: {
        version: 1,
        sources: [
          {
            id,
            provider: "ragflow",
            document_name: "Manual.pdf",
            dataset_name: "Engineering",
            text: "The limit is 42.\n<script>invalid</script>",
            truncated: false,
            pages: [3],
          },
        ],
      },
    },
  },
] as unknown as Message[];
afterEach(cleanup);

function App({ items = messages }: { items?: Message[] }) {
  return (
    <I18nProvider initialLocale="en-US">
      <KnowledgeSourcesProvider messages={items}>
        <KnowledgeCitationLink href={href}>1</KnowledgeCitationLink>
        <KnowledgeSourcesPanel content={`Limit: 42. [citation:1](${href})`} />
      </KnowledgeSourcesProvider>
    </I18nProvider>
  );
}

describe("knowledge source dialogs", () => {
  it("opens the actual excerpt and source page from both citation and source list", () => {
    render(<App />);
    const buttons = screen.getAllByRole("button", {
      name: "View source: Manual.pdf",
    });
    expect(buttons.length).toBe(2);
    fireEvent.click(buttons[0]!);
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Pages 3");
    expect(dialog.textContent).toContain("The limit is 42.");
    expect(dialog.querySelector("script")).toBeNull();
  });
  it("restores citations from persisted JSON and loses access on conversation switch", () => {
    const view = render(
      <App items={JSON.parse(JSON.stringify(messages)) as Message[]} />,
    );
    expect(
      screen.getAllByRole("button", { name: "View source: Manual.pdf" }).length,
    ).toBe(2);
    view.rerender(<App items={[]} />);
    expect(
      screen.queryByRole("button", { name: "View source: Manual.pdf" }),
    ).toBeNull();
    expect(
      screen.getByTitle(
        "Source evidence is unavailable in the loaded conversation.",
      ),
    ).toBeDefined();
  });
});

for (const [surface, Link] of [
  ["message", createMarkdownLinkComponent()],
  ["artifact", ArtifactLink],
] as const) {
  describe(`${surface} knowledge destinations`, () => {
    for (const label of ["Manual.pdf", "citation:1"]) {
      for (const destination of [href, href.replace("#", "#user-content-")]) {
        it(`opens ${label} at ${destination}`, () => {
          render(
            <I18nProvider initialLocale="en-US">
              <KnowledgeSourcesProvider messages={messages}>
                <Link href={destination}>{label}</Link>
              </KnowledgeSourcesProvider>
            </I18nProvider>,
          );
          fireEvent.click(
            screen.getByRole("button", { name: "View source: Manual.pdf" }),
          );
          expect(screen.getByRole("dialog").textContent).toContain(
            "The limit is 42.",
          );
        });
      }
    }
    it("keeps missing sources unavailable and external links navigable", () => {
      render(
        <I18nProvider initialLocale="en-US">
          <KnowledgeSourcesProvider messages={[]}>
            <Link href={href}>Manual.pdf</Link>
            <Link href="https://example.com/manual">External manual</Link>
          </KnowledgeSourcesProvider>
        </I18nProvider>,
      );
      expect(
        screen.getByTitle(
          "Source evidence is unavailable in the loaded conversation.",
        ),
      ).toBeDefined();
      expect(
        screen
          .getByRole("link", { name: "External manual" })
          .getAttribute("href"),
      ).toBe("https://example.com/manual");
    });
  });
}
