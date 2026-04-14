export function shouldRenderTodoQueue({ hidden, collapsed, todos }) {
  return !hidden && !collapsed && Array.isArray(todos) && todos.length > 0;
}
