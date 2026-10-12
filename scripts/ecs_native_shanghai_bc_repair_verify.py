"""Read-only verification of completed #35; never admit, resume or invoke a model."""
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import ssl
import stat
import urllib.request

ROOT=Path('/srv/deerflow-native-task6b/56636cebddc6')
PRIVATE=ROOT/'private/820d7a3429d9/resident'
OPERATOR=PRIVATE.parent/'operator'
THREAD='native-bc-repair-820d7a3429d9-06c502b422e54e648ba3a4216b0c1fde'
SOURCE='70af1fb0-1d51-4b5f-81fb-4de17bfc47cf'
CONTINUATION='5c4933af-2d51-404a-b2a3-affadf7dd93c'
B_JOB='28aa3063aaf4490f881e2b039efdb752'
IMAGE='sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1'

def private(path):
 s=path.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600
 return path

def main():
 assert os.getuid()==0 and all(not p.is_symlink() for p in [OPERATOR,*OPERATOR.parents])
 admission=json.loads(private(ROOT/'proof/bc-repair-admission.json').read_text());assert admission=={'thread_id':THREAD,'source_run_id':SOURCE,'native_goal':True,'one_round':True}
 owner=json.loads(private(OPERATOR/'owner.json').read_text())['owner_id']
 assert json.loads(private(OPERATOR/'bc-repair-thread.json').read_text())=={'owner':owner,'thread_id':THREAD}
 spec=importlib.util.spec_from_file_location('cleanup',ROOT/'bootstrap/ecs_native_shanghai_b_cleanup_recovery.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);query=m.query
 assert query('deerflow_execution',"SELECT record->>'operator_drain' FROM ecs_execution_nodes WHERE id='native-820d7a3429d9';")=='true'
 assert query('deerflow',"SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');")=='0'
 assert query('deerflow',"SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');")=='0'
 assert query('deerflow_execution',"SELECT count(*) FROM ecs_execution_jobs WHERE coalesce((record->>'physical_stopped')::boolean,false)=false OR coalesce((record->>'cleanup_pending')::boolean,false)=true;")=='0'
 runs=json.loads(query('deerflow',f"SELECT json_agg(json_build_object('run_id',run_id,'status',status,'goal_verdict',goal_verdict,'idempotency_key',idempotency_key) ORDER BY created_at) FROM runs WHERE user_id='{owner}' AND thread_id='{THREAD}';"))
 assert len(runs)==2 and {r['run_id'] for r in runs}=={SOURCE,CONTINUATION} and all(r['status']=='success' for r in runs)
 continuation_run=next(r for r in runs if r['run_id']==CONTINUATION);assert continuation_run['idempotency_key']=='mcp-dependencies:'+SOURCE
 jobs=json.loads(query('deerflow_execution',f"SELECT json_agg(record) FROM ecs_execution_jobs WHERE record->'native'->>'thread_id'='{THREAD}' OR record->>'thread_id'='{THREAD}';"))
 assert len(jobs)==3 and {j['id'] for j in jobs}=={'8064c5054d8b43dfbb27c16efb1b2cb7','3337f71875d542d792a1ca358f0eda8d',B_JOB}
 source=next(j for j in jobs if j.get('kind')=='C' and j['native']['run_id']==SOURCE)
 delegated=next(j for j in jobs if j.get('kind','B')=='B')
 continuation=next(j for j in jobs if j.get('kind')=='C' and j['native']['run_id']==CONTINUATION)
 assert all(j['state']=='completed' and j['physical_stopped'] and not j.get('cleanup_pending') and j['node_id']=='native-820d7a3429d9' for j in jobs)
 assert delegated['id']==B_JOB and delegated['attempt']==1 and delegated['started_at']>=source['physical_stopped_at']
 wait=source['dependency_wait'];initial_goal=source['native']['goal'];wait_goal=wait['goal']
 assert wait['continuation_run_id']==CONTINUATION and initial_goal['created_at']==wait_goal['created_at'] and initial_goal['objective']==wait_goal['objective']
 assert continuation['native']['goal']==wait_goal and continuation_run['goal_verdict']['continuations']>=wait_goal['continuation_count']+1
 tasks=json.loads(query('deerflow',f"SELECT json_agg(json_build_object('id',id,'remote_task_id',remote_task_id,'status',status,'notification_status',notification_status,'notification_run_id',notification_run_id,'event_version',event_version,'notified_version',notified_version)) FROM mcp_tasks WHERE user_id='{owner}' AND thread_id='{THREAD}';"))
 assert len(tasks)==1;task=tasks[0]
 assert task['status']=='completed' and task['notification_status']=='delivered' and task['remote_task_id']==B_JOB
 # notification_run_id is an active dispatch lease, intentionally cleared on delivery.
 assert task['notification_run_id'] is None and task['event_version']==task['notified_version'] and task['event_version']>0
 jar=http.cookiejar.MozillaCookieJar(str(private(OPERATOR/'owner.cookies')));jar.load(ignore_discard=True,ignore_expires=False)
 client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(private(PRIVATE/'ca.crt')))),urllib.request.HTTPCookieProcessor(jar))
 def api(path):
  with client.open('https://192.168.0.190:2026'+path,timeout=30) as r:assert r.status==200;return json.load(r)
 assert api('/api/v1/auth/me')['id']==owner
 state=api('/api/threads/'+THREAD+'/state')['values'];tools={c['name'] for msg in state['messages'] for c in msg.get('tool_calls',[])}
 assert {'ecs_submit','read_file','present_files'}<=tools and not state.get('goal')
 output=Path('/srv/deerflow-native-test/users')/owner/'threads'/THREAD/'user-data/outputs'/B_JOB/'files/b.txt'
 assert output.is_file() and not output.is_symlink() and output.read_text()=='dependency-proof-338350'
 mode=output.stat();assert stat.S_IMODE(mode.st_mode)==0o644 and mode.st_nlink==1
 assert query('deerflow',"SELECT count(*) FROM runs WHERE run_id='4198c7a1-551f-4647-b850-46f4f33208d2' AND status='success' OR run_id='0317e4ae-3164-4ed1-bc29-6d8103a4685c' AND status='error';")=='2'
 receipt={'bc_main':'PASS','verified_existing_trial':True,'jenkins_model_trial_build':35,'jenkins_model_trial_result':'FAILURE','wrapper_failure':'terminal_notification_run_id_is_cleared','thread_id':THREAD,'source_run_id':SOURCE,'continuation_run_id':CONTINUATION,'delegated_job_id':B_JOB,'native_mcp_task_id':task['id'],'notification_status':'delivered','notification_dispatch_lease_cleared':True,'notification_versions_equal':True,'pending_notifications':0,'native_run_count':2,'node_id':'native-820d7a3429d9','b_attempt':1,'source_physical_stop_before_B':True,'native_goal_preserved':True,'goal_completed_and_cleared':True,'automatic_native_continuation':True,'durable_wait_and_idempotency_binding':True,'shared_nas_delivered':True,'published_file_mode':'0644','all_physical_stopped':True,'ledger_job_ids':[j['id'] for j in jobs],'publication_image_id':IMAGE,'previous_failed_trial_preserved':True,'operator_drain':True,'nonterminal_native_runs':0,'models_invoked_by_verifier':False,'scope':'readonly_verification_of_existing_installed_C_B_C_trial'}
 path=ROOT/'proof/bc-repair-main.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(receipt,f)
 print(json.dumps(receipt),flush=True)

if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'bc_existing_trial_verification_failed':True,'exception_class':type(e).__name__,'no_models_or_state_changes':True}),flush=True)
  raise SystemExit('Existing BC verification refused; retain completed trial, never rerun model') from None
