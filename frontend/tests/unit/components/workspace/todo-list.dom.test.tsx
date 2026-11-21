import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { TodoList } from "@/components/workspace/todo-list";
import type { Todo } from "@/core/todos";

afterEach(cleanup);

test("keeps todo rows mounted when distinct items move past duplicate labels", () => {
  const draft: Todo = { content: "Draft", status: "pending" };
  const review: Todo = { content: "Review", status: "waiting" };
  const completedDraft: Todo = { content: "Draft", status: "completed" };
  const { rerender } = render(
    <TodoList todos={[draft, review, completedDraft]} collapsed={false} />,
  );
  const reviewRow = screen.getByText("Review").closest("li");
  const draftRows = screen
    .getAllByText("Draft")
    .map((text) => text.closest("li"));

  rerender(
    <TodoList todos={[review, draft, completedDraft]} collapsed={false} />,
  );

  expect(screen.getByText("Review").closest("li")).toBe(reviewRow);
  const nextDraftRows = screen
    .getAllByText("Draft")
    .map((text) => text.closest("li"));
  expect(nextDraftRows[0]).toBe(draftRows[0]);
  expect(nextDraftRows[1]).toBe(draftRows[1]);
  expect(nextDraftRows[0]).not.toBe(nextDraftRows[1]);
});
