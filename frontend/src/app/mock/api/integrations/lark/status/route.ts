const status = {
  installed: false,
  version: "v1.0.65",
  manifest_version: null,
  latest_available_version: "v1.0.65",
  runtime_version_mismatch: false,
  app_configured: false,
  app_id: null,
  app_brand: null,
  skills_expected: 27,
  skills_installed: 0,
  installed_skills: [],
  enabled_skills: [],
  install_path: "/mock/integrations/skills/lark-cli",
  cli: {
    available: false,
    path: null,
    version: null,
    error: "lark-cli is not on PATH",
  },
  auth: {
    status: "unavailable",
    message: "lark-cli is not installed on the Gateway",
    user: null,
    verified: false,
  },
  sandbox_runtime_mode: "none",
  sandbox_runtime_ready: false,
  sandbox_runtime_detail: null,
};

export function GET() {
  return Response.json(status);
}
