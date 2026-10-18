function node(tag, text = '', attrs = {}) {
  const element = document.createElement(tag);
  element.textContent = text;
  Object.assign(element, attrs);
  return element;
}
function mount(root, context) {
  const t = (en, zh) => context.locale?.startsWith('zh') ? zh : en;
  let disposed = false, selected = null, generation = 0, timer;
  const blobUrls = new Set();
  function releaseFiles(){for(const url of blobUrls)URL.revokeObjectURL(url);blobUrls.clear();}
  const sheet = node('link', '', {rel:'stylesheet',href:new URL('./style.css',import.meta.url).href});
  const panel = node('section','',{className:'script-workflows'});
  const notice = node('p','',{role:'status'}), navigation = node('nav'), detail = node('div');
  const script = node('textarea', '', {rows:12,ariaLabel:t('Script','脚本')});
  script.value = "const result = await agent({stepId:'check',agentRef:'lead_agent',task:args.task});\nreturn result.output;";
  const args = node('textarea','',{rows:3,ariaLabel:t('JSON arguments','JSON 参数')});
  args.value = '{"task":"Write a short checklist"}';
  let definition = null, libraryGeneration = 0, definitionBlocked = false;
  const definitions = node('select','',{ariaLabel:t('Saved workflow version','已保存工作流版本')});
  const definitionName = node('input','',{ariaLabel:t('Workflow name','工作流名称'),placeholder:'inspection'});
  const library = node('div');
  async function loadDefinitions() {
    const result = await call('definitions',{});
    definitions.replaceChildren(node('option',t('New script','新脚本'),{value:''}));
    for(const item of result.definitions) definitions.append(node('option',`${item.name} · ${item.version.slice(0,12)}`,{value:JSON.stringify(item)}));
  }
  definitions.onchange=async()=>{
    const version=++libraryGeneration, chosen=definitions.value?JSON.parse(definitions.value):null;
    definition=null;definitionBlocked=Boolean(chosen);submit.disabled=true;
    try {
      if(chosen){
        const item=await call('get_definition',chosen);
        if(version!==libraryGeneration)return;
        script.value=item.script;definitionName.value=item.name;definition=chosen;definitionBlocked=false;
      }
    } catch(e){if(version===libraryGeneration)notice.textContent=e.message;}
    finally{if(version===libraryGeneration)submit.disabled=definitionBlocked;}
  };
  script.oninput=()=>{libraryGeneration++;definition=null;definitions.value='';definitionBlocked=false;submit.disabled=false;};
  library.append(definitions,definitionName,button(t('Save workflow version','保存工作流版本'),async()=>{
    const version=libraryGeneration, source=script.value;
    const saved=await call('save_definition',{name:definitionName.value,script:source});
    await loadDefinitions();
    if(version===libraryGeneration && script.value===source){definition=saved;definitionBlocked=false;submit.disabled=false;definitions.value=JSON.stringify(saved);}
    notice.textContent=t(`Saved ${saved.name} · ${saved.version}`,`已保存 ${saved.name} · ${saved.version}`);
  }));
  const form = node('form');
  const submit = node('button',t('Launch workflow','启动工作流'),{type:'submit'});
  form.append(node('label',t('Inspectable JavaScript script','可检查的 JavaScript 脚本')),script,node('label',t('Arguments (JSON object)','参数（JSON 对象）')),args,submit);
  panel.append(node('h2',t('Script workflows','脚本工作流')),node('p',t('Versioned workflows with live-process resume and authenticated output review. Restart ends resumability; no hard monetary budget. File approval covers a verified immutable snapshot; linked files require explicit capture.','版本化工作流支持同进程恢复和登录用户成果确认。重启后不能恢复；无金额硬上限。文件确认针对经过哈希验证的不可覆盖快照；链接文件需显式捕获。')),notice,library,form,navigation,detail);
  root.append(sheet,panel);
  const alive = version => !disposed && !context.signal?.aborted && version === generation;
  async function call(action,payload) {
    const value=await context.callBackend(action,payload);
    if(disposed || context.signal?.aborted) throw Error('View closed');
    return value;
  }
  function button(text, action) {
    const b=node('button',text,{type:'button'});
    b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){if(!disposed)notice.textContent=e.message;}finally{b.disabled=false;}};
    return b;
  }
  async function list() {
    const version=generation;
    const result=await call('list',{});
    if(!alive(version))return;
    navigation.replaceChildren(node('h3',t('Recent workflows','最近工作流')));
    for(const run of result.runs) navigation.append(button(`${run.run_id.slice(0,8)} · ${run.status}`,async()=>{selected=run.run_id;generation++;clearTimeout(timer);await show();}));
  }
  async function show() {
    const version=generation, id=selected;
    if(!id)return;
    const run=await call('get',{run_id:id});
    if(!alive(version)||id!==selected)return;
    releaseFiles();
    detail.replaceChildren(node('h3',`${run.run_id} · ${run.status}`));
    if(['paused','waiting_approval'].includes(run.status))detail.append(button(t('Refresh checkpoint','刷新检查点'),()=>show()),node('p',t('Gateway restart ends this live checkpoint.','Gateway 重启后此检查点不能继续。')));
    if(run.error)detail.append(node('p',run.error));
    detail.append(node('h4',t('Script','脚本')),node('pre',run.script),node('h4',t('Arguments and execution limits','参数和执行上限')),node('pre',JSON.stringify({definition:run.definition,configuration_revision:run.configuration_revision,args:run.args,limits:run.limits,script_hash:run.script_hash,args_hash:run.args_hash},null,2)));
    for(const step of run.steps){
      const row=node('div',`${step.step_id} · ${step.agent_ref} · ${step.status}`);
      if(step.thread_id && context.openConversation) row.append(button(t('Open child conversation','打开子对话'),()=>context.openConversation(step.thread_id)));
      if(step.status==='completed') row.append(button(t('Inspect retained output','查看保留输出'),async()=>{
        const value=await call('get_step',{run_id:id,step_id:step.step_id});
        if(alive(version)&&id===selected)row.append(node('pre',JSON.stringify(value,null,2)));
      }));
      row.append(node('code',step.run_id||t('Run admission pending','等待 run admission')));detail.append(row);
    }
    for(const checkpoint of run.checkpoints||[]) {
      const review=node('section','',{className:'checkpoint'});
      review.append(node('h4',`${checkpoint.step_id} · ${checkpoint.status}`),node('pre',JSON.stringify(checkpoint,null,2)));
      detail.append(review);
      const canDecide=checkpoint.status==='pending' && run.status==='waiting_approval';
      if(checkpoint.status==='pending' && checkpoint.kind==='pause' && run.status==='paused'){
        review.append(button(t('Resume this checkpoint','继续此检查点'),async()=>{
          await call('resume',{run_id:id,step_id:checkpoint.step_id,attempt:checkpoint.attempt,fingerprint:run.fingerprint});await show();
        }));
      }
      if(checkpoint.kind==='humanCheckpoint'){
        review.append(button(t('Review exact output','审阅确切输出'),async()=>{
          const output=await call('get_step',{run_id:id,step_id:checkpoint.source_step_id});
          if(!alive(version)||id!==selected)return;
          if(output.artifact_version!==checkpoint.artifact_version)throw Error(t('Artifact version changed','成果版本已变化'));
          if(output.kind==='file') {
            if(!Number.isInteger(output.size)||output.size<0||output.size>2097152)throw Error('Invalid file size');
            const bytes=new Uint8Array(output.size);
            let offset=0;
            do {
              const chunk=await call('get_artifact',{run_id:id,version:output.artifact_version,offset});
              if(!alive(version)||id!==selected||!review.isConnected)return;
              if(chunk.version!==output.artifact_version||chunk.sha256!==output.sha256||chunk.offset!==offset)throw Error('File version mismatch');
              const part=Uint8Array.from(atob(chunk.content_base64),c=>c.charCodeAt(0));
              if(offset+part.length>bytes.length)throw Error('Invalid file chunk');
              bytes.set(part,offset);offset+=part.length;
              if(chunk.next_offset===null){if(offset!==bytes.length)throw Error('Incomplete file');break;}
              if(!part.length||chunk.next_offset!==offset)throw Error('Invalid file offset');
            }while(true);
            const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
            if(hash!==output.sha256)throw Error('File hash mismatch');
            if(!alive(version)||id!==selected||!review.isConnected)return;
            const ext=output.name.split('.').pop().toLowerCase();
            const mime=({png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',pdf:'application/pdf'})[ext]||'application/octet-stream';
            const url=URL.createObjectURL(new Blob([bytes],{type:mime}));blobUrls.add(url);
            review.append(node('p',`${output.name} · SHA-256 ${hash}`));
            if(['txt','md','json','csv','log','yaml','yml'].includes(ext))review.append(node('pre',new TextDecoder().decode(bytes)));
            else if(mime.startsWith('image/'))review.append(node('img','',{src:url,alt:output.name}));
            else if(ext==='pdf'){const frame=node('iframe','',{src:url,title:output.name});frame.setAttribute('sandbox','');review.append(frame);}
            review.append(node('a',t('Download this exact version','下载此确切版本'),{href:url,download:output.name}));
          } else review.append(node('pre',JSON.stringify(output.output,null,2)));
          if(canDecide)for(const decision of ['approve','reject'])review.append(button(decision==='approve'?t('Approve this version','确认此版本'):t('Reject this version','拒绝此版本'),async()=>{
            await call('decide',{run_id:id,step_id:checkpoint.step_id,attempt:checkpoint.attempt,artifact_version:checkpoint.artifact_version,decision});await show();
          }));
        }));
      }
    }
    detail.append(node('h4',t('Progress','进度')),node('pre',run.logs.join('\n')),node('h4',t('Final result','最终结果')),node('pre',JSON.stringify(run.result,null,2)));
    if(['queued','running','cancelling','paused','waiting_approval'].includes(run.status)){
      detail.append(button(t('Cancel workflow','取消工作流'),async()=>{await call('cancel',{run_id:id});await show();}));
      clearTimeout(timer);if(['queued','running','cancelling'].includes(run.status))timer=setTimeout(()=>show().catch(e=>{if(!disposed)notice.textContent=e.message;}),2000);
    }else{
      detail.append(button(t('Delete retained record','删除保留记录'),async()=>{await call('delete',{run_id:id});selected=null;generation++;detail.replaceChildren();await list();}));
      await list();
    }
  }
  let pendingRequest=null;
  async function inspectAccepted(id) {
    const version=generation;
    notice.replaceChildren(node('span',t(`Workflow accepted: ${id}`,`工作流已接受：${id}`)));
    try {await list();await show();}
    catch(e) {
      if(!alive(version)||selected!==id)return;
      notice.append(node('span',` · ${e.message}`),button(t('Retry inspection','重试检查'),()=>inspectAccepted(id)));
    }
  }
  form.onsubmit=async event=>{
    event.preventDefault();
    if(definitionBlocked)return;
    submit.disabled=true;notice.textContent='';
    try{
      const value=JSON.parse(args.value);
      if(!value || Array.isArray(value)||typeof value!=='object')throw Error(t('Arguments must be an object','参数必须是对象'));
      const source=definition?{definition}:{script:script.value};
      const content=JSON.stringify({...source,args:value});
      if(pendingRequest?.content!==content)pendingRequest={content,id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('')};
      const result=await call('launch',{request_id:pendingRequest.id,...source,args:value});
      // Keep the identity for unchanged input, including after accepted-launch
      // refresh failures. Refresh retries must never submit another launch.
      selected=result.run_id;generation++;clearTimeout(timer);await inspectAccepted(result.run_id);
    }catch(e){if(!disposed)notice.textContent=e.message;}finally{submit.disabled=definitionBlocked;}
  };
  loadDefinitions().catch(e=>{if(!disposed)notice.textContent=e.message;});
  list().catch(e=>{if(!disposed)notice.textContent=e.message;});
  return {dispose(){releaseFiles();disposed=true;generation++;clearTimeout(timer);sheet.remove();panel.remove();}};
}
export default {apiVersion:1,module:'workflows.v1',surfaces:[{id:'runs',slot:'page',title:'Script workflows',navigation:{label:'Script workflows',labelZh:'脚本工作流'},mount}]};
