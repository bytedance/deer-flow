import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  KnowledgeCitationLink,
  KnowledgeSourcesPanel,
  KnowledgeSourcesProvider,
} from "@/components/workspace/citations/knowledge-source";
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
