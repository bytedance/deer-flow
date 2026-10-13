"""One installed native HTTP/WSS control sequence through the existing owner session."""

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
INNER = """import sys,json,ssl,hashlib,time,httpx
from pathlib import PurePosixPath
from urllib.parse import quote
from websockets.sync.client import connect
p=json.load(sys.stdin)
base='https://192.168.0.190:2026'
context=ssl.create_default_context(cafile='/run/operator/ca.crt')
headers={'Cookie':p['cookie'],'Origin':base,'X-CSRF-Token':p['csrf']}
thread=p['thread'];route='/api/threads/'+thread
with httpx.Client(base_url=base,verify=context,headers=headers,timeout=60,trust_env=False) as client:
 me=client.get('/api/v1/auth/me');assert me.status_code==200 and me.json()['id']==p['owner']
 if p['action']=='prepare':
  r=client.post('/api/threads',json={'thread_id':thread});assert r.status_code in (200,201)
  r=client.post(route+'/browser/navigate',json={'url':'https://example.com'});assert r.status_code==200
  v=r.json();assert v['title']=='Example Domain' and v['screenshot']
  screenshot=v['screenshot'];path=PurePosixPath(screenshot)
  assert screenshot.startswith('/mnt/user-data/') and '..' not in path.parts and chr(92) not in screenshot
  with client.stream('GET',route+'/artifacts/'+quote(screenshot.lstrip('/'),safe='/')) as delivery:
   assert delivery.status_code==200 and delivery.headers.get('content-type','').split(';',1)[0]=='image/jpeg'
   chunks=[];size=0
   for chunk in delivery.iter_bytes():
    size+=len(chunk);assert size<=8*1024**2;chunks.append(chunk)
   body=b''.join(chunks)
  assert body.startswith(bytes.fromhex('ffd8ff')) and body.endswith(bytes.fromhex('ffd9')) and len(body)>1000
  value={'native_http_navigate':True,'title':v['title'],'screenshot_delivered':True,'screenshot_format':'jpeg','screenshot_bytes':len(body),'screenshot_sha256':hashlib.sha256(body).hexdigest()}
 elif p['action']=='live':
  url=base.replace('https://','wss://')+route+'/browser/stream?frame_format=binary'
  destination='https://example.com/#'+thread
  def receive(live,expected=None):
   deadline=time.monotonic()+45;frame=None;location=expected is None
   while time.monotonic()<deadline:
    try:item=live.recv(timeout=min(10,deadline-time.monotonic()))
    except TimeoutError:continue
    if isinstance(item,bytes):
     assert item.startswith(bytes.fromhex('ffd8')) and len(item)>1000
     frame=hashlib.sha256(item).hexdigest()
    else:
     message=json.loads(item)
     if message.get('type')=='url' and message.get('url')==expected:location=True
     if message.get('type')=='tabs' and any(t.get('active') and t.get('url')==expected for t in message.get('tabs',[])):location=True
    if frame and location:return frame
   raise AssertionError('Native frame/location did not settle')
  with connect(url,ssl=context,origin=base,additional_headers={'Cookie':p['cookie']},open_timeout=15,max_size=12*1024**2) as live:
   first=receive(live)
   live.send(json.dumps({'type':'navigate','url':destination}))
   changed=receive(live,destination)
  with connect(url,ssl=context,origin=base,additional_headers={'Cookie':p['cookie']},open_timeout=15,max_size=12*1024**2) as resumed:
   retained=receive(resumed,destination)
  value={'strict_wss':True,'input_effect_verified':True,'reconnect_without_seed':True,'same_fragment_retained':True,'fragment_sha256':hashlib.sha256(destination.encode()).hexdigest(),'first_frame_sha256':first,'mutated_frame_sha256':changed,'reconnected_frame_sha256':retained}
 else:
  r=client.delete(route);assert r.status_code in (200,204,404)
  value={'owned_thread_delete':True,'delete_status':r.status_code}
 print(json.dumps(value),flush=True)
"""


def private(path):
    assert all(not p.is_symlink() for p in [path, *path.parents])
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return path


def main(action, thread, image):
    assert os.getuid() == 0 and re.fullmatch(
        r"native-browser-installed-[0-9a-f]{32}", thread
    )
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    result = subprocess.run(
        ["docker", "inspect", "deer-native-820d7a3429d9-controller-gateway-1"],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    gateway = json.loads(result.stdout)[0]
    assert (
        gateway["Image"] == image and gateway["State"]["Health"]["Status"] == "healthy"
    )
    assert (
        gateway["Config"]["Labels"]["com.docker.compose.project"]
        == "deer-native-820d7a3429d9-controller"
    )
    assert gateway["Config"]["Labels"]["com.docker.compose.service"] == "gateway"
    assert not any(m["Source"] == "/var/run/docker.sock" for m in gateway["Mounts"])
    jar = http.cookiejar.MozillaCookieJar(str(private(OPERATOR / "owner.cookies")))
    jar.load(ignore_discard=True, ignore_expires=False)
    cookies = [c for c in jar if not c.is_expired()]
    csrf = [c.value for c in cookies if c.name == "csrf_token"]
    assert len(csrf) == 1
    payload = {
        "action": action,
        "thread": thread,
        "cookie": "; ".join(c.name + "=" + c.value for c in cookies),
        "csrf": csrf[0],
        "owner": json.loads(private(OPERATOR / "owner.json").read_text())["owner_id"],
    }
    result = subprocess.run(
        ["docker", "exec", "-i", gateway["Id"], "python", "-c", INNER],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=140,
    )
    if result.returncode:
        directory = OPERATOR.lstat()
        assert (
            stat.S_ISDIR(directory.st_mode)
            and directory.st_uid == 0
            and stat.S_IMODE(directory.st_mode) == 0o700
        )
        assert all(not p.is_symlink() for p in [OPERATOR, *OPERATOR.parents])
        diagnostic = OPERATOR / (
            "browser-control-repair-" + thread + "-" + action + ".stderr.log"
        )
        fd = os.open(
            diagnostic, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(result.stderr)
    assert result.returncode == 0, (
        "Owned native control failed; private output withheld"
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    print(json.dumps(value), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "live", "delete"])
    p.add_argument("thread")
    p.add_argument("image")
    a = p.parse_args()
    try:
        main(a.action, a.thread, a.image)
    except Exception as e:
        print(
            json.dumps(
                {
                    "browser_control_failed": True,
                    "action": a.action,
                    "exception_class": type(e).__name__,
                    "models_called": False,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Owned native control refused; private output withheld"
        ) from None
