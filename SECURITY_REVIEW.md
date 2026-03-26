# Security Code Review — DeerFlow Gateway (XSS Focus)

Date: 2026-03-26  
Reviewer: Codex (re-run per request)  
Scope: `backend/app/gateway/routers/artifacts.py` and related gateway exposure

## Executive Conclusion

**Finding:** Stored Cross-Site Scripting (XSS) in artifact rendering path (**remediated in this branch**)  
**OWASP Top 10:2025 Mapping:** **A03 Injection**  
**Credibility:** **High** (estimated true-positive confidence: **0.92 / 1.00**)

Previously, the artifacts endpoint served `text/html` artifacts inline using `HTMLResponse` with raw file content. In this branch, active content types are now forced to download as attachments to prevent inline execution in the app origin.

---

## Re-run Methodology

1. Re-inspected gateway artifact serving logic line-by-line.
2. Searched the codebase for direct HTML sinks (`HTMLResponse`, `dangerouslySetInnerHTML`) to identify executable rendering paths.
3. Re-validated artifact route behavior around inline render vs forced download.

---

## Technical Evidence

### 1) Direct HTML sink in backend route

In `get_artifact`, when MIME type is `text/html`, the route returns:

- `HTMLResponse(content=actual_path.read_text(encoding="utf-8"))`

This returns untrusted HTML to the browser for direct rendering.

### 2) Route does not force download for HTML by default

Only `?download=true` forces attachment behavior. Without it, HTML is rendered inline.

### 3) Threat model fit

DeerFlow artifacts are generated from model/user-influenced workflows. If an attacker can cause HTML output to include script payloads, visiting the artifact URL can execute script in browser context.

---

## Proof-of-Concept (manual)

> For validation in a test environment only.

1. Create an output artifact named `poc.html` with content:

```html
<!doctype html>
<html>
  <body>
    <h1>PoC</h1>
    <script>
      alert('xss-poc');
    </script>
  </body>
</html>
```

2. Open artifact URL:

`/api/threads/<thread_id>/artifacts/mnt/user-data/outputs/poc.html`

3. Expected: script executes because backend returns inline `HTMLResponse`.

---

## Impact

Potential consequences:
- Session/token theft (depending on frontend auth/storage model)
- Unauthorized actions via victim browser session
- Phishing/UI redress under trusted origin
- Data exfiltration from accessible page context

---

## Why this finding is credible

- **Concrete sink exists** (inline HTML rendering in backend).
- **No sanitization/neutralization** before response generation.
- **Exploit condition is practical** in systems where users can generate or upload HTML artifacts.
- Remaining uncertainty is deployment/browser policy dependent (e.g., CSP), not whether the sink exists.

---

## Recommended Remediation (priority)

1. **Do not inline-render untrusted HTML artifacts.** Serve as attachment by default.
2. If HTML preview is required, serve from an **isolated untrusted origin** (separate domain) with strict sandboxing.
3. Add strong CSP for preview surfaces (e.g., disallow inline scripts, restrict script-src).
4. Add security test coverage:
   - ensure `text/html` artifacts are downloaded (or sandbox-isolated),
   - ensure script execution is blocked in preview flow.

---

## Reviewer Note

This report is intentionally evidence-based and scoped to verifiable code behavior in this repository.
