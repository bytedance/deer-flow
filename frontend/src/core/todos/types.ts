export interface Todo {
  content?: string;
  status?: "pending" | "in_progress" | "completed" | "blocked" | "waiting";
}
