# GPT Image 2 integration proposal

## Verified local state

- Hermes profiles `picture_create` and `picture_create2` have GPT Image 2 Skills and an OpenAI API key configured. A non-disclosing comparison confirms they use the same key. Neither profile sets OPENAI_BASE_URL or OPENAI_API_BASE in its profile .env.
- Existing CLI source: `C:/Users/Administrator/.hermes/home/GPT-Image2-Skill/src/gpt_image_cli/cli.py`; current model identifier is `gpt-image-2`. It calls images.generate for text prompts and images.edit for reference images/masks.
- Hermes also contains an openai-codex image provider, but the inspected root config does not select it. Do not conflate this with the API-key Skill installed in the two picture profiles.
- DDFW's bundled image-generation Skill currently implements other providers. It is not an Image 2 adapter. Default public Skills are exempt from grants, so a new integration must use a distinct managed Skill and tool name.
- No credential value was displayed, no generation API request has been made, and no runtime config has been changed by this investigation. Configured credentials have not yet been verified against the remote API.

## Recommended implementation

Add a native `gpt_image2` tool and a distinct `gpt-image2` Skill. Register the tool through root config.yaml; keep the implementation independent of Hermes's running container. Reuse the API contract and relevant prompt guidance rather than mounting Hermes's data directory into DDFW sandboxes.

The tool accepts a prompt, image size/quality, and optional current-thread reference images/mask. It resolves identity from authenticated server context, validates input paths inside the current user's thread, invokes the image API, and saves verified image bytes in that thread's outputs directory. Return an artifact through the existing DDFW file presentation mechanism. Use bounded timeouts and response sizes; do not automatically retry an ambiguous paid generation. Errors must not include API keys or authorization headers.

Both the new tool and new Skill remain managed extensions: administrators can grant them to users/groups, and normal users without grants cannot invoke the tool or read the Skill projection. Existing defaults and personal/sandbox isolation remain intact.

## Credential alternatives requiring the user's choice

1. Personal credentials, consistent with the existing isolation policy: extend the private credential UI/API to support this native provider. Import the existing Hermes key only into the DDFW administrator's encrypted credential slot. Other users save their own keys; no fallback to the administrator's key.
2. Explicit enterprise shared credential: keep the existing key as an operator-managed backend-only secret. Only users/groups granted Image 2 can use it. All calls consume that shared account's quota. This is a deliberate exception to personal credential isolation for this integration only.

Do not select alternative 2 implicitly from the presence of a Hermes key. Never put either mode's key in Skill text, frontend responses, logs, or shared sandbox mounts.

## Other approaches considered

- HTTP MCP service: supports reuse across multiple agent platforms, but adds a deployed service and transport/artifact plumbing. Prefer this if cross-platform centralized management is the main goal.
- Copy the CLI Skill directly into the sandbox: quick for a single user, but requires sandbox dependencies and key delivery, and a default-open bash tool cannot serve as the only authorization boundary. Not the recommended enterprise integration.

## Acceptance checks

- Mocked API tests cover generation, reference editing, validation, timeout/error redaction and output ownership.
- Verify new-tool/new-Skill deny, user/group grant and revocation; verify chosen credential isolation or explicit shared-account behavior.
- Frontend credential checks are needed for personal mode; no raw key reads after saving.
- Back up local config/private credential store before migration. Build/restart only affected DDFW services; Hermes stays unchanged.
- One small generation verifies the real API, followed by artifact preview/download checks. Report any lack of image-model access rather than claiming the integration works based only on configuration.

## Approved decision
User selected alternative 2: the company key is shared only by authorized users/groups. Implement native tool + managed Skill as recommended.
