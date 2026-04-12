export function shouldRedirectHomePageToWorkspace(env = process.env) {
  return env.DEER_FLOW_DESKTOP_BUNDLE === "1";
}
