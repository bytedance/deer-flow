import { useState } from "react";
import { createRoot } from "react-dom/client";

import { QueryClientProvider } from "@/components/query-client-provider";
import { ArtifactFilePreview } from "@/components/workspace/artifacts/artifact-file-preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
} from "@/core/workspaces/context";

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const report = `<!doctype html><html><head><title>Private report</title>
<link rel="stylesheet" href="css/main.css">
</head><body><h1>Private report</h1><div class="box">Nested stylesheet</div>
<img id="asset" src="img/chart.png" alt="Private chart">
<p id="script">waiting</p><p id="data">waiting</p>
<button id="refresh" type="button">Refresh data</button>
<button id="hold" type="button">Hold data</button><button id="denied" type="button">Check denied</button><p id="denials">waiting</p>
<a id="external" href="https://example.test/source">External source</a>
<script src="script.js"></script>
<script>
window.probe={isolated:false};
try {window.parent.document.body;} catch {window.probe.isolated=true;}
async function refresh(){try{const r=await fetch('./data.json');const d=await r.json();document.getElementById('data').textContent=d.workspace+':'+d.read_count;}catch{document.getElementById('data').textContent='error';}}
document.getElementById('refresh').addEventListener('click',refresh);refresh();
document.getElementById('hold').addEventListener('click',()=>fetch('./data.json?hold=1').then(r=>r.json()).then(d=>{document.getElementById('data').textContent=d.workspace;}).catch(()=>{}));
document.getElementById('denied').addEventListener('click',async()=>{const results=await Promise.allSettled([fetch('/api/auth/me'),fetch('/api/threads/foreign/artifacts/private.txt'),fetch('./data.json',{method:'POST',body:'denied'})]);document.getElementById('denials').textContent=results.every(x=>x.status==='rejected')?'refused':'leaked';});
</script></body></html>`;
function Preview() {
  const [active, setActive] = useState(true);
  const lifetime = useWorkspaceLifetime();
  const controls = useWorkspaceContext();
  if (!lifetime || !controls)
    throw new Error("Fixture requires a confirmed workspace");
  return (
    <>
      <div data-testid="scope">{lifetime?.scope.workspaceId}</div>
      <button onClick={() => void controls.select(P)}>Personal</button>
      <button onClick={() => void controls.select(T)}>Team</button>
      <button onClick={() => setActive((value) => !value)}>
        {active ? "Hide report" : "Show report"}
      </button>
      <img
        id="control"
        src={urlOfArtifact({
          threadId: "thread-1",
          filepath: "/mnt/user-data/outputs/report/img/chart.png",
          workspaceId: lifetime?.scope.workspaceId,
        })}
        alt="Parent control"
      />
      <ArtifactFilePreview
        active={active}
        content={report}
        language="html"
        scrollKey="thread-1:report.html"
        url={urlOfArtifact({
          threadId: "thread-1",
          filepath: "/mnt/user-data/outputs/report/report.html",
          workspaceId: lifetime?.scope.workspaceId,
        })}
      />
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <AuthProvider
    initialUser={{
      id: "alice",
      email: "alice@example.test",
      system_role: "user",
      needs_setup: false,
    }}
  >
    <QueryClientProvider>
      <I18nContext.Provider
        value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
      >
        <WorkspaceProvider enabled>
          <WorkspaceReadyBoundary>
            <Preview />
          </WorkspaceReadyBoundary>
        </WorkspaceProvider>
      </I18nContext.Provider>
    </QueryClientProvider>
  </AuthProvider>,
);
