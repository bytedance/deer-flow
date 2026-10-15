import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import {
  MessageDetailsProvider,
  useMaybeMessageDetails,
} from "@/components/workspace/message-details/context";
import { MessageDetailsMenu } from "@/components/workspace/message-details/message-details-menu";
import { MessageDetailsPanel } from "@/components/workspace/message-details/message-details-panel";
import { SkillUsageMenu } from "@/components/workspace/skill-usage/skill-usage-menu";
import { SkillUsagePanel } from "@/components/workspace/skill-usage/skill-usage-panel";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { type SkillUsage } from "@/core/skills/usage";

const skills: SkillUsage[] = [
  {
    name: "research",
    description: "Research a topic with sources.",
    category: "public",
    path: "/mnt/skills/public/research/SKILL.md",
    content:
      "---\nname: research\ndescription: Research a topic with sources.\n---\n# Research instructions\n\nFind primary sources.",
    content_hash: "abc",
    activation: "automatic",
    partial: false,
  },
  {
    name: "presentations",
    description: "Build a slide deck.",
    category: "custom",
    path: "/mnt/skills/custom/presentations/SKILL.md",
    content: "# Presentation instructions\n\nOutline the slides.",
    content_hash: "def",
    activation: "slash",
    partial: true,
  },
];

function Locale({ children }: { children: ReactNode }) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      {children}
    </I18nContext.Provider>
  );
}

function Harness({ onSelect = () => undefined }: { onSelect?: () => void }) {
  return (
    <Locale>
      <MessageDetailsProvider onSelect={onSelect}>
        <SkillUsageMenu skills={skills} />
        <MessageDetailsPanel />
      </MessageDetailsProvider>
    </Locale>
  );
}

async function selectSkill(name: string) {
  fireEvent.keyDown(screen.getByRole("button", { name: "Skills used" }), {
    key: "Enter",
  });
  fireEvent.click(
    await screen.findByRole("menuitem", { name: new RegExp(name) }),
  );
}

afterEach(cleanup);

describe("skill usage inspection", () => {
  it("hides the entry without a chat panel provider or without loaded skills", () => {
    const { rerender } = render(
      <Locale>
        <SkillUsageMenu skills={skills} />
      </Locale>,
    );
    expect(screen.queryByRole("button", { name: "Skills used" })).toBeNull();
    rerender(
      <Locale>
        <MessageDetailsProvider>
          <SkillUsageMenu skills={[]} />
        </MessageDetailsProvider>
      </Locale>,
    );
    expect(screen.queryByRole("button", { name: "Skills used" })).toBeNull();
  });

  it("opens the captured instructions with metadata and switches to another skill", async () => {
    const onSelect = rs.fn();
    render(<Harness onSelect={onSelect} />);
    await selectSkill("research");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "SKILL.md" })).toBeTruthy();
    expect(await screen.findByText(skills[0]!.path)).toBeTruthy();
    expect(screen.getByText("Built-in")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Research instructions" }),
    ).toBeTruthy();
    expect(screen.queryByText(/name: research/)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    await selectSkill("presentations");
    expect(
      await screen.findByRole("heading", { name: "Presentation instructions" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Research instructions" }),
    ).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("partial");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "SKILL.md" })).toBeNull();
  });

  it("copies the original snapshot including frontmatter", async () => {
    const writeText = rs.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<Harness />);
    await selectSkill("research");
    fireEvent.click(
      screen.getByRole("button", { name: "Copy skill snapshot" }),
    );
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(skills[0]!.content),
    );
  });
});

function GenericEntry() {
  const details = useMaybeMessageDetails();
  return (
    <MessageDetailsMenu
      label="Inspect result"
      title="Results"
      icon={<span aria-hidden="true">↗</span>}
      entries={[
        {
          id: "first",
          title: "First result",
          subtitle: "Captured output",
          onSelect: () =>
            details?.select({
              id: "first",
              title: "Result details",
              content: <p>Arbitrary detail content</p>,
              actions: <button>Export result</button>,
            }),
        },
        {
          id: "second",
          title: "Second result",
          onSelect: () =>
            details?.select({
              id: "second",
              title: "Other details",
              content: <p>Another detail</p>,
            }),
        },
      ]}
    />
  );
}

describe("generic message details", () => {
  it("uses the same menu and shell for arbitrary content, titles and actions", async () => {
    render(
      <Locale>
        <MessageDetailsProvider>
          <GenericEntry />
          <MessageDetailsPanel />
        </MessageDetailsProvider>
      </Locale>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Inspect result" }), {
      key: "Enter",
    });
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "First result Captured output",
      }),
    );
    expect(
      screen.getByRole("heading", { name: "Result details" }),
    ).toBeTruthy();
    expect(screen.getByText("Arbitrary detail content")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export result" })).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { name: "Result details" }),
      ),
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Inspect result" }), {
      key: "Enter",
    });
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Second result" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Other details" }),
    ).toBeTruthy();
    expect(screen.queryByText("Arbitrary detail content")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export result" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "Other details" })).toBeNull();
  });
});

function ChangingLocale() {
  const [chinese, setChinese] = useState(false);
  return (
    <I18nContext.Provider
      value={{
        locale: chinese ? "zh-CN" : "en-US",
        setLocale: () => undefined,
        t: chinese ? zhCN : enUS,
      }}
    >
      <button onClick={() => setChinese(true)}>Switch language</button>
      <MessageDetailsProvider>
        <SkillUsageMenu skills={skills} />
        <MessageDetailsPanel />
      </MessageDetailsProvider>
    </I18nContext.Provider>
  );
}

function OtherPanelTrigger() {
  const details = useMaybeMessageDetails();
  return (
    <button
      onClick={(event) => {
        event.currentTarget.focus();
        details?.close({ restoreFocus: false });
      }}
    >
      Open another panel
    </button>
  );
}

describe("skill detail review regressions", () => {
  it("shows unresolved local links and images as inert references while retaining safe web links", () => {
    const content =
      "[Template](templates/apa.md)\n\n[Local section](#section)\n\n[Sandbox file](/mnt/skills/references/a.md)\n\n![Diagram](assets/diagram.png)\n\n[Website](https://example.com/research)";
    render(
      <Locale>
        <SkillUsagePanel skill={{ ...skills[0]!, content }} />
      </Locale>,
    );
    expect(screen.queryByRole("link", { name: "Template" })).toBeNull();
    expect(screen.getByText("Template").getAttribute("title")).toBe(
      "templates/apa.md",
    );
    expect(screen.queryByRole("link", { name: "Local section" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Sandbox file" })).toBeNull();
    expect(screen.queryByRole("img", { name: "Diagram" })).toBeNull();
    expect(screen.getByText("Diagram").getAttribute("title")).toBe(
      "assets/diagram.png",
    );
    expect(
      screen.getByRole("link", { name: "Website" }).getAttribute("href"),
    ).toBe("https://example.com/research");
  });

  it("updates the copy action when locale changes with a snapshot already open", async () => {
    const copiedToast = rs.spyOn(toast, "success");
    const writeText = rs.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<ChangingLocale />);
    await selectSkill("research");
    fireEvent.click(screen.getByRole("button", { name: "Switch language" }));
    expect(screen.getByRole("button", { name: "复制技能快照" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Copy skill snapshot" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "复制技能快照" }));
    await waitFor(() =>
      expect(copiedToast).toHaveBeenCalledWith(
        zhCN.clipboard.copiedToClipboard,
      ),
    );
    expect(writeText).toHaveBeenCalledWith(skills[0]!.content);
    copiedToast.mockRestore();
  });

  it("focuses the opened detail and restores the originating entry on close or Escape", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Skills used" });
    await selectSkill("research");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { name: "SKILL.md" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    await selectSkill("research");
    const heading = screen.getByRole("heading", { name: "SKILL.md" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(screen.queryByRole("heading", { name: "SKILL.md" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("keeps focus with a newly opened panel when replacing the detail", async () => {
    render(
      <Locale>
        <MessageDetailsProvider>
          <SkillUsageMenu skills={skills} />
          <OtherPanelTrigger />
          <MessageDetailsPanel />
        </MessageDetailsProvider>
      </Locale>,
    );
    await selectSkill("research");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { name: "SKILL.md" }),
      ),
    );
    const other = screen.getByRole("button", { name: "Open another panel" });
    fireEvent.click(other);
    expect(screen.queryByRole("heading", { name: "SKILL.md" })).toBeNull();
    expect(document.activeElement).toBe(other);
  });
});
