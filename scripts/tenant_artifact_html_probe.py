"""Shanghai-only native HTML diagnostic: no deployment, credentials, or external network.

Transpile the archived, unchanged native preview helpers and exercise their Blob
iframe in the existing browser image. The HTTP server is a strict cookie/scope
fixture, not the DeerFlow Gateway. Observations are not tenant acceptance.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

CI_IMAGE = "sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01"
BROWSER_IMAGE = (
    "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
)

BROWSER_SCRIPT = r'''
import asyncio,base64,hashlib,json,threading,struct,zlib,subprocess
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from playwright.async_api import async_playwright
MODULE=base64.b64decode(MODULE_BASE64)
WORKSPACE="22222222-2222-2222-2222-222222222222"
requests=[]
def chunk(tag,data):
 return struct.pack(">I",len(data))+tag+data+struct.pack(">I",zlib.crc32(tag+data))
PNG=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,6,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00\xff\x00\x00\xff"))+chunk(b"IEND",b"")
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  u=urlparse(self.path)
  if u.path=="/fixture.js":
   self.send_response(200);self.send_header("Content-Type","application/javascript");self.end_headers();self.wfile.write(FIXTURE_MODULE.encode());return
  if u.path=="/native-preview.js":
   self.send_response(200);self.send_header("Content-Type","application/javascript");self.end_headers();self.wfile.write(MODULE);return
  if u.path=="/":
   body=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html");self.end_headers();self.wfile.write(body);return
  if "/artifacts/" in u.path:
   selector=parse_qs(u.query).get("workspace_id",[None])[0]
   scope=selector or (WORKSPACE if u.path.startswith("/api/workspaces/"+WORKSPACE+"/") else None)
   cookie="access_token=html-probe-only" in self.headers.get("Cookie","")
   allowed=cookie and scope==WORKSPACE
   requests.append({"path":u.path,"query_selector":selector,"resolved_scope":scope,"cookie_present":cookie,"origin":self.headers.get("Origin"),"allowed":allowed})
   self.send_response(200 if allowed else 403)
   kind="image/png" if u.path.endswith(".png") else "text/css" if u.path.endswith(".css") else "application/json"
   self.send_header("Content-Type",kind);self.end_headers()
   self.wfile.write((PNG if kind=="image/png" else b"body{background:rgb(1,2,3)}" if kind=="text/css" else b'{"fixture":true}') if allowed else b"not-authorized")
   return
  self.send_response(404);self.end_headers()
REPORT="""<html><head><script>window.probe={};</script>
<link rel="stylesheet" href="style.css" onload="probe.css='load'" onerror="probe.css='error'">
</head><body><img id="asset" src="chart.png">
<script>fetch('./data.json').then(r=>r.json()).then(()=>probe.fetch='load').catch(()=>probe.fetch='error');</script></body></html>"""
HTML="""<!doctype html><title>Native scoped HTML diagnostic</title><script type="module">
import {appendHtmlPreviewBaseHref,appendHtmlPreviewScrollRestoration} from '/native-preview.js';
const ws='22222222-2222-2222-2222-222222222222';
const report=REPORT_LITERAL;
const control=document.createElement('img');control.id='control';control.src='/api/threads/thread-1/artifacts/mnt/user-data/outputs/chart.png?workspace_id='+ws;document.body.append(control);
for(const [name,path] of [['query','/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.html?workspace_id='+ws],['namespace','/api/workspaces/'+ws+'/threads/thread-1/artifacts/mnt/user-data/outputs/report.html']]){
 const frame=document.createElement('iframe');
 frame.name=name;
 frame.id=name;
 frame.setAttribute('sandbox','allow-scripts allow-forms');
 frame.src=URL.createObjectURL(new Blob([appendHtmlPreviewScrollRestoration(appendHtmlPreviewBaseHref(report,location.origin+path),name)],{type:'text/html'}));
 document.body.append(frame);

}
const assets=await Promise.all([['chart','chart.png'],['css','style.css'],['data','data.json']].map(async([key,path])=>{const response=await fetch(
 '/api/threads/thread-1/artifacts/mnt/user-data/outputs/'+path+'?workspace_id='+ws,{credentials:'include'});
 if(!response.ok)throw new Error('Parent fixture authorization failed');
 return [key,{bytes:Array.from(new Uint8Array(await response.arrayBuffer())),type:response.headers.get('Content-Type')}];
 }));

const packet=Object.fromEntries(assets);
const parentURLs=Object.fromEntries(assets.map(([key,asset])=>[key,URL.createObjectURL(new Blob([new Uint8Array(asset.bytes)],{type:asset.type}))]));
const substitute=(html,urls)=>html.replaceAll('chart.png',urls.chart).replaceAll('style.css',urls.css).replaceAll('./data.json',urls.data);
const parentFrame=document.createElement('iframe');
parentFrame.name='parent_blob';parentFrame.id='parent_blob';parentFrame.setAttribute('sandbox','allow-scripts allow-forms');
const parentContent=appendHtmlPreviewScrollRestoration(
 appendHtmlPreviewBaseHref(substitute(report,parentURLs),
 location.origin+'/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.html?workspace_id='+ws),'parent_blob');
parentFrame.src=URL.createObjectURL(new Blob([parentContent],{type:'text/html'}));document.body.append(parentFrame);
const reportLiteral=JSON.stringify(report).replaceAll('</',String.fromCharCode(60,92,47));
const childCode='const packet='+JSON.stringify(packet)+';const report='+reportLiteral+';' +
 'const urls=Object.fromEntries(Object.entries(packet).map(([key,asset])=>[key,URL.createObjectURL(new Blob([new Uint8Array(asset.bytes)],{type:asset.type}))]));' +
 'const html=report.replaceAll("chart.png",urls.chart).replaceAll("style.css",urls.css).replaceAll("./data.json",urls.data);' +
 'document.open();document.write(html);document.close();';
const childFrame=document.createElement('iframe');
 childFrame.name='child_bytes';
 childFrame.id='child_bytes';
 childFrame.setAttribute('sandbox','allow-scripts allow-forms');
 childFrame.src=URL.createObjectURL(new Blob(['<script>'+childCode+String.fromCharCode(60)+'/script>'],{type:'text/html'}));
 document.body.append(childFrame);

</script>"""
HTML=HTML.replace("REPORT_LITERAL",json.dumps(REPORT).replace("</", "<\\/"))
FIXTURE_MODULE=HTML.split('<script type="module">',1)[1].rsplit('</script>',1)[0]
HTML='<!doctype html><title>Native scoped HTML diagnostic</title><script type="module" src="/fixture.js"></script>'
syntax=subprocess.run(['/usr/bin/node','--check','--input-type=module'],input=FIXTURE_MODULE,capture_output=True,text=True)
assert syntax.returncode==0,syntax.stderr
async def main():
 server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();origin=f"http://127.0.0.1:{server.server_port}"
 try:
  async with async_playwright() as p:
   browser=await p.chromium.launch(headless=True)
   try:
    context=await browser.new_context();await context.add_cookies([{"name":"access_token","value":"html-probe-only","url":origin,"httpOnly":True,"sameSite":"Lax"}]);page=await context.new_page();await page.goto(origin)
    await page.wait_for_selector("iframe#child_bytes")
    await page.wait_for_function("document.querySelector('#control')?.complete && document.querySelector('#control').naturalWidth === 1")
    rows=[]
    for name in ("query","namespace","parent_blob","child_bytes"):
     frame=page.frame(name=name);assert frame is not None
     await frame.wait_for_function("document.querySelector('#asset')?.complete && window.probe?.fetch !== undefined && window.probe?.css !== undefined",timeout=10000)
     state=await frame.evaluate("({imageWidth:document.querySelector('#asset').naturalWidth,css:probe.css,fetch:probe.fetch,base:document.baseURI})")
     state["name"]=name;rows.append(state)
    assert len(requests)>=10
    print(json.dumps({"status":"diagnostic_complete","browser_version":browser.version,"parent_image_width":1,"frames":rows,"requests":requests,
      "scope":"actual native helper/Blob/sandbox behavior against strict local cookie/scope fixture; not Gateway or full React acceptance",
      "network":"none","models_called":False}))
   finally: await browser.close()
 finally: server.shutdown();server.server_close()
asyncio.run(main())
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"deerflow-tenant-frontend-[1-9][0-9]*", args.label)
    archive = args.archive.resolve(strict=True)
    dependencies = args.dependencies.resolve(strict=True)
    assert archive.is_file() and dependencies.is_dir()
    with tarfile.open(archive) as source:
        member = source.extractfile("frontend/src/core/artifacts/preview.ts")
        assert member is not None
        native_source = member.read()
    names = [args.label + "-html-compile", args.label + "-html-browser"]
    try:
        compile_script = """set -eu
mkdir -p /tmp/tenant-source/frontend
ln -s /deps/node_modules /tmp/tenant-source/frontend/node_modules
tar xOf /run/source.tar.gz frontend/src/core/artifacts/preview.ts > /tmp/preview.ts
node - <<'JS'
const fs=require('fs');
 const ts=require('/deps/node_modules/typescript');
 process.stdout.write(ts.transpileModule(fs.readFileSync('/tmp/preview.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText);

JS
"""
        compiled = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                names[0],
                "--label",
                "org.deerflow.tenant.owned=" + args.label,
                "--network",
                "none",
                "--user",
                "999:987",
                "--cpus",
                "0.5",
                "--memory",
                "512m",
                "--memory-swap",
                "512m",
                "-v",
                str(archive) + ":/run/source.tar.gz:ro",
                "-v",
                str(dependencies) + ":/deps/node_modules:ro",
                "--entrypoint",
                "/bin/sh",
                CI_IMAGE,
                "-c",
                compile_script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if compiled.returncode:
            raise RuntimeError(compiled.stderr[-2000:])
        module = compiled.stdout.encode()
        assert 0 < len(module) < 128 * 1024
        script = BROWSER_SCRIPT.replace(
            "MODULE_BASE64", repr(base64.b64encode(module).decode()), 1
        )
        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "-i",
                "--name",
                names[1],
                "--label",
                "org.deerflow.tenant.owned=" + args.label,
                "--network",
                "none",
                "--user",
                "1000:1000",
                "--cpus",
                "0.5",
                "--memory",
                "512m",
                "--memory-swap",
                "512m",
                "--shm-size",
                "128m",
                "--entrypoint",
                "/app/backend/.venv/bin/python3",
                BROWSER_IMAGE,
                "-",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if run.returncode:
            raise RuntimeError(run.stderr[-2500:])
        result = json.loads(run.stdout)
        result.update(
            native_source_sha256=hashlib.sha256(native_source).hexdigest(),
            module_sha256=hashlib.sha256(module).hexdigest(),
            images={"compiler": CI_IMAGE, "browser": BROWSER_IMAGE},
        )
        print(json.dumps(result))
    finally:
        for name in names:
            probe = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.deerflow.tenant.owned" }}',
                    name,
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                assert probe.stdout.strip() == args.label
                subprocess.run(
                    ["docker", "rm", "-f", name], check=True, capture_output=True
                )


if __name__ == "__main__":
    main()
