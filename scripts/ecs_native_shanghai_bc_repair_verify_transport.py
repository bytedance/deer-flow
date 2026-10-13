"""Jenkins read-only receipt recovery for completed #35; no admission or models."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT=Path('/data/jenkins-agent/deerflow/native-task6b-56636cebddc6')
SHA='f1e70d0dce7ae167f9529a14ff8b4572be0e55ce3b384100ee591afb999f51bb'
REMOTE='/srv/deerflow-native-task6b/56636cebddc6/bootstrap/ecs_native_shanghai_bc_repair_verify.py'

def main():
 helper=ROOT/'scripts/ecs_native_shanghai_bootstrap.py';assert hashlib.sha256(helper.read_bytes()).hexdigest()=='8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a'
 spec=importlib.util.spec_from_file_location('fixed_bootstrap',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.copy_public('192.168.0.190',ROOT/'scripts/ecs_native_shanghai_bc_repair_verify.py',REMOTE,SHA)
 r=subprocess.run(['ssh',*m.OPTIONS,'root@192.168.0.190','python3',REMOTE],capture_output=True,text=True,timeout=180)
 receipts=[]
 for line in r.stdout.splitlines():
  try:value=json.loads(line)
  except json.JSONDecodeError:continue
  if value.get('bc_main')=='PASS' or value.get('bc_existing_trial_verification_failed'):
   receipts.append(value);print(json.dumps(value),flush=True)
 assert r.returncode==0 and len(receipts)==1 and receipts[0]['bc_main']=='PASS' and receipts[0]['models_invoked_by_verifier'] is False
 fd=os.open(ROOT/'proof/bc-repair-verification.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(receipts[0],f)

if __name__=='__main__':
 try:main()
 except Exception:raise SystemExit('Read-only existing BC verification failed; retain same trial, no model retry') from None
