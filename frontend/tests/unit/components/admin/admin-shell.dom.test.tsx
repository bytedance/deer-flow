import { describe, expect, test } from "@rstest/core";
import { render, screen } from "@testing-library/react";

import { AdminShell } from "@/components/admin/admin-shell";

describe("AdminShell", () => {
  test("provides dedicated operations navigation without chat controls", () => {
    render(
      <AdminShell>
        <div>概览内容</div>
      </AdminShell>,
    );

    expect(screen.getByRole("link", { name: "内容安全" })).not.toBeNull();
    expect(screen.getByRole("link", { name: "租户与用户" })).not.toBeNull();
    expect(screen.queryByText("新对话")).toBeNull();
  });
});
