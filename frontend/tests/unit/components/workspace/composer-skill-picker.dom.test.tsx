import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ComposerSkillPicker } from "@/components/workspace/composer-skill-picker";
import type { Skill } from "@/core/skills";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      inputBox: {
        skillPickerLabel: "Skills",
        skillPickerSearch: "Search skills...",
        skillPickerEmpty: "No matching skills.",
        skillPickerGroup: "Skills",
      },
    },
  }),
}));

function makeSkill(name: string, description: string, enabled = true): Skill {
  return {
    name,
    description,
    enabled,
  } as Skill;
}

const skills = [
  makeSkill("data-analysis", "Analyze CSV data"),
  makeSkill("web-design", "Design landing pages"),
  makeSkill("pdf", "Extract PDF text", false),
];

afterEach(() => cleanup());

describe("ComposerSkillPicker", () => {
  it("opens a searchable list of enabled skills from the toolbar button", () => {
    render(<ComposerSkillPicker skills={skills} onPick={rs.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Skills" }));

    expect(screen.getByText("/data-analysis")).toBeDefined();
    expect(screen.getByText("/web-design")).toBeDefined();
    // Disabled skills never appear in the picker.
    expect(screen.queryByText("/pdf")).toBeNull();
  });

  it("filters by the search query and reports an empty state", () => {
    render(<ComposerSkillPicker skills={skills} onPick={rs.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Skills" }));
    fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
      target: { value: "csv" },
    });

    expect(screen.getByText("/data-analysis")).toBeDefined();
    expect(screen.queryByText("/web-design")).toBeNull();

    fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
      target: { value: "no-such-skill" },
    });
    expect(screen.getByText("No matching skills.")).toBeDefined();
  });

  it("hands the picked skill to the composer and closes", () => {
    const onPick = rs.fn();
    render(<ComposerSkillPicker skills={skills} onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: "Skills" }));
    fireEvent.click(screen.getByText("/web-design"));

    expect(onPick).toHaveBeenCalledTimes(1);
    const picked = onPick.mock.calls[0]![0] as Skill;
    expect(picked.name).toBe("web-design");
    expect(picked.description).toBe("Design landing pages");
    expect(screen.queryByText("/web-design")).toBeNull();
  });

  it("selects the highlighted skill with Enter and disables with no skills", () => {
    const onPick = rs.fn();
    render(<ComposerSkillPicker skills={skills} onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: "Skills" }));
    const input = screen.getByPlaceholderText("Search skills...");
    fireEvent.change(input, { target: { value: "web" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onPick).toHaveBeenCalledTimes(1);
    expect((onPick.mock.calls[0]![0] as Skill).name).toBe("web-design");

    cleanup();
    render(
      <ComposerSkillPicker
        skills={[makeSkill("pdf", "x", false)]}
        onPick={onPick}
      />,
    );
    const noSkillsButton = screen.getByRole("button", {
      name: "Skills",
    });
    expect(noSkillsButton.getAttribute("disabled")).not.toBeNull();
  });
});
