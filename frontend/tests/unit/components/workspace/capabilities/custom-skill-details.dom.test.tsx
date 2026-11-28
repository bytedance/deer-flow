import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  load: rs.fn(),
  update: rs.fn(),
  remove: rs.fn(),
  invalidate: rs.fn(),
}));
rs.mock("@/core/skills/api", () => ({
  ...rs.requireActual("@/core/skills/api"),
  loadCustomSkill: mocks.load,
  updateCustomSkill: mocks.update,
  deleteCustomSkill: mocks.remove,
}));
rs.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidate }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

import { CustomSkillDetails } from "@/components/workspace/capabilities/custom-skill-details";
import { enUS } from "@/core/i18n/locales/en-US";
import type { CustomSkillContent } from "@/core/skills/api";

const text = enUS.settings.skills;
const skill: CustomSkillContent = {
  name: "demo",
  description: "Demo skill",
  category: "custom",
  license: "MIT",
  enabled: true,
  editable: true,
  content: "---\nname: demo\ndescription: Demo\n---\nInstructions",
};

function renderDetails(
  overrides: {
    onChanged?: (skill: CustomSkillContent) => void;
    onDeleted?: () => void;
    onExport?: () => void;
  } = {},
) {
  render(
    <CustomSkillDetails
      skill={skill}
      onChanged={overrides.onChanged ?? rs.fn()}
      onDeleted={overrides.onDeleted ?? rs.fn()}
      onExport={overrides.onExport ?? rs.fn()}
    />,
  );
}

beforeEach(() => {
  mocks.load.mockReset().mockResolvedValue(skill);
  mocks.update.mockReset();
  mocks.remove.mockReset().mockResolvedValue({ success: true });
  mocks.invalidate.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("custom skill lifecycle", () => {
  it("loads and edits SKILL.md through the lifecycle API", async () => {
    const onChanged = rs.fn();
    const updated = { ...skill, content: "Updated instructions" };
    mocks.update.mockResolvedValue(updated);
    renderDetails({ onChanged });
    await screen.findByText(
      (_, element) =>
        element?.tagName === "PRE" && element.textContent === skill.content,
    );

    fireEvent.click(screen.getByRole("button", { name: text.editSkill }));
    fireEvent.change(screen.getByLabelText(text.skillContent), {
      target: { value: updated.content },
    });
    fireEvent.click(screen.getByRole("button", { name: text.saveSkill }));

    expect(mocks.update).toHaveBeenCalledWith("demo", updated.content);
    await screen.findByText(
      (_, element) =>
        element?.tagName === "PRE" && element.textContent === updated.content,
    );
    expect(onChanged).toHaveBeenCalledWith(updated);
    expect(mocks.invalidate).toHaveBeenCalledWith({ queryKey: ["skills"] });
  });

  it("exports and confirms deletion from the same detail surface", async () => {
    const onExport = rs.fn();
    const onDeleted = rs.fn();
    renderDetails({ onExport, onDeleted });
    await screen.findByText(
      (_, element) =>
        element?.tagName === "PRE" && element.textContent === skill.content,
    );

    fireEvent.click(screen.getByRole("button", { name: text.exportSkill }));
    expect(onExport).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: text.deleteSkill }));
    expect(screen.getByText(text.deleteConfirm)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: text.confirmDelete }));

    expect(mocks.remove).toHaveBeenCalledWith("demo");
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(mocks.invalidate).toHaveBeenCalledWith({ queryKey: ["skills"] });
  });
});
