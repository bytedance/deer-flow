const MODELS_URL = "http://localhost:2026/api/models";
const REDIRECT_URL = "http://localhost:2026/workspace/chats/new";

export function getPreflightOutcome({ ok }) {
  if (ok) {
    return {
      shouldRedirect: true,
      redirectUrl: REDIRECT_URL,
    };
  }

  return {
    shouldRedirect: false,
    redirectUrl: null,
  };
}

async function runPreflight({ button, status }) {
  button.disabled = true;
  status.textContent = "Checking DeerFlow at localhost:2026...";

  try {
    const response = await fetch(MODELS_URL, { method: "GET" });
    const outcome = getPreflightOutcome({ ok: response.ok });

    if (outcome.shouldRedirect) {
      window.location.href = outcome.redirectUrl;
      return;
    }

    status.textContent = "DeerFlow is still unavailable. Leave this page open and retry when the local app is ready.";
  } catch {
    status.textContent = "Unable to reach DeerFlow at localhost:2026. Start the local services, then retry.";
  } finally {
    button.disabled = false;
  }
}

function initPreflight() {
  const button = document.getElementById("retry-button");
  const status = document.getElementById("preflight-status");

  if (!(button instanceof HTMLButtonElement) || !(status instanceof HTMLElement)) {
    return;
  }

  void runPreflight({ button, status });

  button.addEventListener("click", () => {
    void runPreflight({ button, status });
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPreflight, { once: true });
  } else {
    initPreflight();
  }
}
