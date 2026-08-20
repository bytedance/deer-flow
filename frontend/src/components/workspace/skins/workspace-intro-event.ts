export const WORKSPACE_INTRO_EVENT = "deerflow:workspace-intro";

export function playWorkspaceIntro() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(WORKSPACE_INTRO_EVENT));
}
