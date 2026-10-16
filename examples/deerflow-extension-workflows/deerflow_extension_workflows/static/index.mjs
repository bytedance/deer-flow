function node(tag, text = '', attrs = {}) {
  const element = document.createElement(tag);
  element.textContent = text;
  Object.assign(element, attrs);
  return element;
}
function mount(root, context) {
  const t = (en, zh) => context.locale?.startsWith('zh') ? zh : en;
  let disposed = false, selected = null, generation = 0, timer;
  const sheet = node('link', '', {rel:'stylesheet',href:new URL('./style.css',import.meta.url).href});
  const panel = node('section','',{className:'script-workflows'});
  const notice = node('p','',{role:'status'}), navigation = node('nav'), detail = node('div');
  const script = node('textarea', '', {rows:12,ariaLabel:t('Script','脚本')});
  script.value = "const result = await agent({stepId:'check',agentRef:'lead_agent',task:args.task});\nreturn result.output;";
  const args = node('textarea','',{rows:3,ariaLabel:t('JSON arguments','JSON 参数')});
  args.value = '{"task":"Write a short checklist"}';
  const form = node('form');
  const submit = node('button',t('Launch workflow','启动工作流'),{type:'submit'});
  form.append(node('label',t('Inspectable JavaScript script','可检查的 JavaScript 脚本')),script,node('label',t('Arguments (JSON object)','参数（JSON 对象）')),args,submit);
  panel.append(node('h2',t('Script workflows','脚本工作流')),node('p',t('Phase 1: bounded background Agent calls. No resume, human sign-off, restart replay or hard monetary budget. Cancellation preserves child checkpoints and does not undo side effects.','第一阶段：有界后台 Agent 调用。不支持恢复、成果审批、重启回放或金额硬上限。取消保留子对话检查点，不撤销副作用。')),notice,form,navigation,detail);
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
    detail.replaceChildren(node('h3',`${run.run_id} · ${run.status}`));
    if(run.error)detail.append(node('p',run.error));
    detail.append(node('h4',t('Script','脚本')),node('pre',run.script),node('h4',t('Arguments and execution limits','参数和执行上限')),node('pre',JSON.stringify({args:run.args,limits:run.limits,script_hash:run.script_hash,args_hash:run.args_hash},null,2)));
    for(const step of run.steps){
      const row=node('div',`${step.step_id} · ${step.agent_ref} · ${step.status}`);
      if(step.thread_id && context.openConversation) row.append(button(t('Open child conversation','打开子对话'),()=>context.openConversation(step.thread_id)));
      row.append(node('code',step.run_id||t('Run admission pending','等待 run admission')));detail.append(row);
    }
    detail.append(node('h4',t('Progress','进度')),node('pre',run.logs.join('\n')),node('h4',t('Final result','最终结果')),node('pre',JSON.stringify(run.result,null,2)));
    if(['queued','running','cancelling'].includes(run.status)){
      detail.append(button(t('Cancel workflow','取消工作流'),async()=>{await call('cancel',{run_id:id});await show();}));
      clearTimeout(timer);timer=setTimeout(()=>show().catch(e=>{if(!disposed)notice.textContent=e.message;}),2000);
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
    event.preventDefault();submit.disabled=true;notice.textContent='';
    try{
      const value=JSON.parse(args.value);
      if(!value || Array.isArray(value)||typeof value!=='object')throw Error(t('Arguments must be an object','参数必须是对象'));
      const content=JSON.stringify({script:script.value,args:value});
      if(pendingRequest?.content!==content)pendingRequest={content,id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('')};
      const result=await call('launch',{request_id:pendingRequest.id,script:script.value,args:value});
      // Keep the identity for unchanged input, including after accepted-launch
      // refresh failures. Refresh retries must never submit another launch.
      selected=result.run_id;generation++;clearTimeout(timer);await inspectAccepted(result.run_id);
    }catch(e){if(!disposed)notice.textContent=e.message;}finally{submit.disabled=false;}
  };
  list().catch(e=>{if(!disposed)notice.textContent=e.message;});
  return {dispose(){disposed=true;generation++;clearTimeout(timer);sheet.remove();panel.remove();}};
}
export default {apiVersion:1,module:'workflows.v1',surfaces:[{id:'runs',slot:'page',title:'Script workflows',navigation:{label:'Script workflows',labelZh:'脚本工作流'},mount}]};
