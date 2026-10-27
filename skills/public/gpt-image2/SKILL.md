---
name: gpt-image2
description: 使用 GPT Image 2 生成图片、中文海报、产品图，或根据当前会话上传的参考图进行编辑。Use for GPT Image 2 generation and reference-image editing with authorized company billing.
allowed-tools:
  - gpt_image2
  - read_file
  - view_image
  - present_files
  - image_search
  - ask_clarification
---

# GPT Image 2

Use the native `gpt_image2` tool to generate or edit images. The administrator manages company billing. Users need explicit access to the tool; access to this Skill alone does not authorize a paid call.

## Workflow

1. Establish the requested subject, style, composition, aspect ratio and any exact text. Keep exact Chinese text verbatim in the prompt. Ask a brief clarification only when required information is missing.
2. For editing, use reference images already uploaded to this conversation and pass their `/mnt/user-data/uploads/...` paths. Earlier results in this conversation's outputs may also be used. Never pass another user's files, host paths or remote image URLs.
3. Call `gpt_image2` once per requested image. Default quality is `medium`. Use `low` for drafts or explicit low-cost requests and `high` for detailed final posters/text. Supported sizes: `1024x1024` square, `1536x1024` landscape, `1024x1536` portrait, or `auto`.
4. For text-to-image, omit `reference_images`. For editing, pass up to four PNG/JPEG/WebP reference paths and clearly state what to preserve/change. An optional mask must be a PNG with alpha and the same dimensions as the first reference; transparent areas are edited.
5. The returned PNG is automatically presented in the chat as a preview/download artifact. Briefly describe the result; do not claim to have visually inspected it unless it was actually viewed.

## Failure handling

- If authorization is denied, ask the administrator for the `gpt_image2` tool and this Skill. Do not work around the denial with another tool or script.
- If the company key, billing or model access is unavailable, report the error. Do not ask employees to paste the company's key into the chat.
- A timeout or lost connection can occur after billing. Do not automatically retry or submit duplicate requests. Tell the user the outcome is uncertain before another attempt.
- At most two requests run concurrently. If busy, report that status rather than launching repeated calls.

## Credential boundary

Use the native tool only. Do not inspect environment files, install the Hermes CLI, read credential stores, or copy keys into scripts/sandboxes. Outputs and references remain scoped to the current user and conversation.
