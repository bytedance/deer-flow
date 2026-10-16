"""Shanghai-only native React HTML resource main: no deployment, credentials, or external network.

Bundle the archived native React component and exercise its opaque Blob iframe
in the existing browser image. The HTTP server is a strict cookie/scope
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

BROWSER_SCRIPT = r"""
import asyncio,base64,json,threading,struct,zlib,mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from playwright.async_api import async_playwright
FILES={k:base64.b64decode(v) for k,v in json.loads(base64.b64decode(FILES_BASE64)).items()}
P="11111111-1111-1111-1111-111111111111";T="22222222-2222-2222-2222-222222222222"
requests=[];reads={P:0,T:0};forbidden_hits=[];held_started=threading.Event();held_release=threading.Event();held_module_started=threading.Event()
def chunk(tag,data):return struct.pack(">I",len(data))+tag+data+struct.pack(">I",zlib.crc32(tag+data))
PNG=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,6,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00\xff\x00\x00\xff"))+chunk(b"IEND",b"")
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,status,body,kind):
  self.send_response(status);self.send_header("Content-Type",kind);self.send_header("Cache-Control","no-store");self.end_headers();
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):
  u=urlparse(self.path)
  cookie="access_token=html-bridge-fixture" in self.headers.get("Cookie","")
  if u.path=="/":return self.reply(200,b'<!doctype html><style>iframe{width:640px;height:400px}#control{width:16px;height:16px}</style><div id="root"></div><script src="/compiled/app.js"></script>',"text/html")
  if u.path.startswith("/compiled/"):
   name=u.path[len("/compiled/"):]
   if name in FILES:return self.reply(200,FILES[name],mimetypes.guess_type(name)[0] or "application/octet-stream")
   return self.reply(404,b"not-found","text/plain")
  if u.path=="/api/auth/me" or "/threads/foreign/" in u.path:forbidden_hits.append(u.path)
  if u.path=="/api/workspaces":
   body=[{"id":ws,"name":"Personal" if ws==P else "Team","kind":"personal" if ws==P else "team","status":"active","personal_user_id":"alice" if ws==P else None,"role":"owner","membership_version":1,"policy_version":1} for ws in (P,T)]
   return self.reply(200 if cookie else 401,json.dumps(body).encode(),"application/json")
  if u.path=="/api/workspaces/current":
   ws=self.headers.get("X-Deerflow-Workspace")
   return self.reply(200 if cookie and ws in (P,T) else 403,json.dumps({"actor_user_id":"alice","workspace_id":ws,"membership_version":1,"policy_version":1}).encode(),"application/json")
  if "/artifacts/" in u.path:
   ws=parse_qs(u.query).get("workspace_id",[None])[0];header=self.headers.get("X-Deerflow-Workspace")
   allowed=cookie and ws in (P,T) and (header is None or header==ws)
   requests.append({"path":u.path,"workspace":ws,"workspace_header":header,"cookie_present":cookie,"allowed":allowed})
   if not allowed:return self.reply(403,b"not-authorized","text/plain")
   if u.path.endswith(".png"):return self.reply(200,PNG,"image/png")
   if u.path.endswith("/css/main.css"):return self.reply(200,b'@import "./theme.css";body{color:rgb(12,34,56)}',"text/css;charset=utf-8")
   if u.path.endswith("/css/theme.css"):return self.reply(200,b'.box{background-image:url("../img/tile.png");height:24px;width:24px}',"text/css;charset=utf-8")
   if u.path.endswith("/script.js"):return self.reply(200,('document.getElementById("script").textContent="script:'+ws+'";').encode(),"text/javascript;charset=utf-8")
   module_files={
    "/modules/value.js":'window.valueLoads=(window.valueLoads||0)+1;export const label='+json.dumps(ws)+';',
    "/modules/bridge.js":'export {label} from "./value.js";',
    "/modules/cycle-a.js":'import {b} from "./cycle-b.js";export function a(){return "a";}export function cycle(){return b();}',
    "/modules/cycle-b.js":'import {a} from "./cycle-a.js";export function b(){return a()+"b";}',
    "/modules/main.js":'import {label} from "./bridge.js";import {cycle} from "./cycle-a.js";document.getElementById("module").textContent="module:"+label+":"+cycle();const response=await fetch(new URL("./module-data.json",import.meta.url));document.getElementById("module-meta").textContent=(await response.json()).workspace;document.getElementById("dynamic").addEventListener("click",async()=>{const path="./dynamic.js";const module=await import(path);document.getElementById("dynamic-module").textContent=module.value+":"+window.dynamicLoads+":"+window.valueLoads;window.dynamicSettled=(window.dynamicSettled||0)+1;});document.getElementById("hold-module").addEventListener("click",()=>import("./slow.js").catch(()=>{}));document.getElementById("denied-module").addEventListener("click",async()=>{const results=await Promise.allSettled([import("/api/auth/me"),import("/api/threads/foreign/artifacts/private.js"),import("./wrong-mime.js")]);document.getElementById("module-denials").textContent=results.every(result=>result.status==="rejected")&&!window.wrongMime?"refused":"leaked";});window.moduleReady=true;',
    "/modules/literal.js":'import {label} from "./value.js";export const literal="literal:"+label;',
    "/modules/dynamic.js":'import {label} from "./value.js";window.dynamicLoads=(window.dynamicLoads||0)+1;export const value=await Promise.resolve("dynamic:"+label);'
   }
   if u.path.endswith("/modules/slow.js"):
    held_module_started.set();held_release.wait(12);return self.reply(200,b'export const retired=true;',"text/javascript")
   if u.path.endswith("/modules/wrong-mime.js"):return self.reply(200,b'window.wrongMime=true;export default 1;',"text/plain")
   if u.path.endswith("/modules/config.json"):return self.reply(200,json.dumps({"workspace":ws}).encode(),"application/json")
   for suffix,script in module_files.items():
    if u.path.endswith(suffix):return self.reply(200,script.encode(),"text/javascript;charset=utf-8")
   if u.path.endswith("/modules/module-data.json"):return self.reply(200,json.dumps({"workspace":ws}).encode(),"application/json")
   if u.path.endswith("/data.json"):
    if parse_qs(u.query).get("hold")==["1"]:
     held_started.set();held_release.wait(12);return self.reply(200,b'{"workspace":"retired"}',"application/json")
    if held_started.is_set():held_release.set()
    reads[ws]+=1;return self.reply(200,json.dumps({"workspace":ws,"read_count":reads[ws]}).encode(),"application/json")
   return self.reply(404,b"not-found","text/plain")
  return self.reply(404,b"not-found","text/plain")
async def main():
 server=ThreadingHTTPServer(("127.0.0.1",0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f"http://127.0.0.1:{server.server_port}"
 rows=[];errors=[];failure=None;boundaries={};failed_requests=[];inflight={};console_errors=[]
 try:
  async with async_playwright() as p:
   browser=await p.chromium.launch(headless=True)
   try:
    context=await browser.new_context();await context.add_cookies([{"name":"access_token","value":"html-bridge-fixture","url":origin,"httpOnly":True,"sameSite":"Lax"}]);page=await context.new_page();page.on("pageerror",lambda e:errors.append(str(e)));page.on("requestfailed",lambda r:failed_requests.append(r.url))
    page.on("request",lambda request:inflight.__setitem__(id(request),request.url))
    page.on("requestfinished",lambda request:inflight.pop(id(request),None))
    page.on("requestfailed",lambda request:inflight.pop(id(request),None))
    page.on("console",lambda message:console_errors.append(message.text) if message.type=="error" else None)
    try:
     await page.goto(origin)  # The scoped UI/resource assertions below own readiness.
     for ws,label in [(P,None),(T,"Team")]:
      if label:await page.get_by_role("button",name=label,exact=True).click()
      await page.wait_for_function("(ws) => document.querySelector('[data-testid=scope]')?.textContent===ws",arg=ws)
      await page.wait_for_function("document.querySelector('#control')?.complete && document.querySelector('#control').naturalWidth===1")
      handle=await page.locator('iframe[title="Artifact preview"]').element_handle();frame=await handle.content_frame();assert frame is not None
      await frame.wait_for_function("window.probe && document.querySelector('#asset')?.complete && document.querySelector('#data')?.textContent!=='waiting'",timeout=15000)
      state=await frame.evaluate("({imageWidth:document.querySelector('#asset').naturalWidth,color:getComputedStyle(document.body).color,background:getComputedStyle(document.querySelector('.box')).backgroundImage,script:document.querySelector('#script').textContent,data:document.querySelector('#data').textContent,isolated:probe.isolated,external:document.querySelector('#external').getAttribute('href')})")
      state['workspace']=ws;state['parent_control_width']=1
      try:
       await frame.wait_for_function("window.moduleReady && document.querySelector('#literal-module').textContent!=='waiting' && document.querySelector('#json-module').textContent!=='waiting'",timeout=5000)
       await frame.get_by_role('button',name='Load module',exact=True).click();await frame.wait_for_function("(ws)=>document.querySelector('#dynamic-module').textContent==='dynamic:'+ws+':1:1' && window.dynamicSettled===1",arg=ws)
       await frame.get_by_role('button',name='Load module',exact=True).click();await frame.wait_for_function("(ws)=>document.querySelector('#dynamic-module').textContent==='dynamic:'+ws+':1:1' && window.dynamicSettled===2",arg=ws)
      except Exception:pass
      state['modules']=await frame.evaluate("({main:document.querySelector('#module').textContent,inline:document.querySelector('#inline-module').textContent,literal:document.querySelector('#literal-module').textContent,json:document.querySelector('#json-module').textContent,meta:document.querySelector('#module-meta').textContent,dynamic:document.querySelector('#dynamic-module').textContent})")
      if state['data']==ws+':1':
       await frame.get_by_role('button',name='Refresh data').click();await frame.wait_for_function("(ws) => document.querySelector('#data').textContent===ws+':2'",arg=ws);state['refreshed']=True
      else:state['refreshed']=False
      rows.append(state)
     await frame.get_by_role('button',name='Check denied').click();await frame.wait_for_function("document.querySelector('#denials').textContent==='refused'")
     boundaries['read_only_thread_route']=not forbidden_hits
     await frame.get_by_role('button',name='Check modules',exact=True).click();await frame.wait_for_function("document.querySelector('#module-denials').textContent==='refused'")
     boundaries['module_refusal_and_mime']=not forbidden_hits and await frame.evaluate("!window.wrongMime")
     await frame.get_by_role('button',name='Hold module',exact=True).click()
     assert await asyncio.to_thread(held_module_started.wait,5),"held module did not start"
     old_url=await page.locator('iframe[title="Artifact preview"]').get_attribute('src')
     await frame.get_by_role('button',name='Hold data').click()
     assert await asyncio.to_thread(held_started.wait,5),"held read did not start"
     await page.get_by_role('button',name='Hide report',exact=True).click()
     await page.wait_for_function("!document.querySelector('iframe').getAttribute('src')")
     boundaries['retired_bootstrap_revoked']=await page.evaluate("async url=>{try{await fetch(url);return false;}catch{return true;}}",old_url)
     await page.get_by_role('button',name='Show report',exact=True).click()
     handle=await page.locator('iframe[title="Artifact preview"]').element_handle();frame=await handle.content_frame()
     await frame.wait_for_function("(ws)=>document.querySelector('#data')?.textContent===ws+':3'",arg=T,timeout=15000)
     await asyncio.sleep(0.05)
     boundaries['held_transport_aborted']=any('hold=1' in url for url in failed_requests)
     boundaries['held_module_transport_aborted']=any('/modules/slow.js' in url for url in failed_requests)
     await frame.wait_for_function("window.moduleReady && document.querySelector('#json-module').textContent!=='waiting'",timeout=15000)
     boundaries['new_module_document_survives']=await frame.evaluate("(ws)=>document.querySelector('#module').textContent==='module:'+ws+':ab' && window.valueLoads===1",T)
     boundaries['new_document_survives']=await frame.locator('#data').inner_text()==T+':3'
    except Exception as e:
     failure=str(e)
     try:errors.append((await page.locator('#root').inner_text(timeout=1500))[:1000])
     except Exception:pass
    passed=not errors and len(rows)==2 and len(boundaries)==7 and all(boundaries.values()) and all(x['modules']=={'main':'module:'+x['workspace']+':ab','inline':'inline:'+x['workspace'],'literal':'literal:'+x['workspace'],'json':x['workspace'],'meta':x['workspace'],'dynamic':'dynamic:'+x['workspace']+':1:1'} and x['imageWidth']==1 and x['color']=='rgb(12, 34, 56)' and x['background'].startswith('url("blob:') and x['script']=='script:'+x['workspace'] and x['data']==x['workspace']+':1' and x['refreshed'] and x['isolated'] and x['external']=='https://example.test/source' for x in rows)
    print(json.dumps({"status":"main_passed" if passed else "main_failed","browser_version":browser.version,"rows":rows,"boundaries":boundaries,"forbidden_hits":forbidden_hits,"requests":requests,"errors":errors,"console_errors":console_errors[-20:],"inflight":list(inflight.values())[-20:],"failure":failure,"scope":"actual native React ArtifactFilePreview/Auth/Workspace/REST against cookie/scope HTTP fixtures and navigation/env build doubles; not Next/Gateway/SQL acceptance","network":"none","models_called":False}),flush=True)
    return passed
   finally:await browser.close()
 finally:server.shutdown();server.server_close()
raise SystemExit(0 if asyncio.run(main()) else 1)
"""


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
        compile_script = "set -eu\nmkdir -p /tmp/tenant-source/frontend\ntar xzf /run/source.tar.gz -C /tmp/tenant-source\nln -s /deps/node_modules /tmp/tenant-source/frontend/node_modules\ncat > /tmp/fixture-env.js <<'JS'\nexport const env = {NEXT_PUBLIC_STATIC_WEBSITE_ONLY: \"false\"};\nJS\ncat > /tmp/fixture-navigation.js <<'JS'\nexport const useRouter=()=>({push(){},replace(){}});\nexport const usePathname=()=>\"/artifacts/view\";\nexport const useSearchParams=()=>new URLSearchParams(location.search);\nJS\nnode --input-type=module - <<'JS'\nimport fs from 'node:fs';import path from 'node:path';\nconst deps='/deps/node_modules/.pnpm';const name=fs.readdirSync(deps).find(x=>x.startsWith('@rspack+core@2.0.8'));\nif(!name)throw new Error('Pinned existing Rspack not found');\nconst {rspack}=await import(path.join(deps,name,'node_modules/@rspack/core/dist/index.js'));\nconst root='/tmp/tenant-source/frontend';\nconst compiler=rspack({mode:'production',context:root,target:'web',devtool:false,\n entry:path.join(root,'tests/browser-fixtures/html-preview.tsx'),\n output:{path:'/tmp/compiled',filename:'app.js',chunkFilename:'[name].[contenthash].js',publicPath:'/compiled/'},\n resolve:{extensions:['.tsx','.ts','.jsx','.js','.mjs','.json'],alias:{'@/env$':'/tmp/fixture-env.js','next/navigation$':'/tmp/fixture-navigation.js','@':path.join(root,'src')},conditionNames:['browser','import','module','default'],fallback:{fs:false,path:false,crypto:false}},\n module:{rules:[{test:/\\.[jt]sx?$/,exclude:/node_modules/,use:{loader:'builtin:swc-loader',options:{jsc:{parser:{syntax:'typescript',tsx:true},transform:{react:{runtime:'automatic'}},target:'es2022'}}}},{test:/\\.css$/,type:'asset/source'},{test:/\\.(woff2?|ttf|png|svg|wasm)$/,type:'asset/resource'}]},\n optimization:{minimize:false},performance:{hints:false},plugins:[new rspack.DefinePlugin({'process.env.NODE_ENV':JSON.stringify('production')})]\n});\nawait new Promise((resolve,reject)=>compiler.run((error,stats)=>{if(error)return reject(error);if(stats.hasErrors())return reject(new Error(stats.toString({all:false,errors:true})));resolve();}));\nawait new Promise((resolve,reject)=>compiler.close(error=>error?reject(error):resolve()));\nJS\npython3 - <<'INNER'\nfrom pathlib import Path\nimport json,base64\nroot=Path('/tmp/compiled')\nprint(json.dumps({str(p.relative_to(root)):base64.b64encode(p.read_bytes()).decode() for p in root.rglob('*') if p.is_file()}))\nINNER\n"
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
                "2g",
                "--memory-swap",
                "2g",
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
            timeout=180,
        )
        if compiled.returncode:
            raise RuntimeError(compiled.stderr[-2000:])
        module = compiled.stdout.encode()
        assert 0 < len(module) < 128 * 1024 * 1024
        script = BROWSER_SCRIPT.replace(
            "FILES_BASE64", repr(base64.b64encode(module).decode()), 1
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
                "1g",
                "--memory-swap",
                "1g",
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
            timeout=120,
        )
        if not run.stdout.strip():
            raise RuntimeError(run.stderr[-2500:])
        result = json.loads(run.stdout)
        result.update(
            native_source_sha256=hashlib.sha256(native_source).hexdigest(),
            module_sha256=hashlib.sha256(module).hexdigest(),
            images={"compiler": CI_IMAGE, "browser": BROWSER_IMAGE},
        )
        print(json.dumps(result))
        if run.returncode:
            raise SystemExit(run.returncode)
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
