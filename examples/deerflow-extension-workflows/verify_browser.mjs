// Self-contained loopback browser fixture; never a deployed Gateway.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE ?? '../../frontend/node_modules/@playwright/test/index.mjs');
const directory=new URL('./deerflow_extension_workflows/static/',import.meta.url);
const server=createServer(async(req,res)=>{
  if(req.url==='/index.mjs'||req.url==='/style.css'){
    res.setHeader('Content-Type',req.url.endsWith('.mjs')?'text/javascript':'text/css');
    res.end(await readFile(new URL(req.url.slice(1),directory)));return;
  }
  res.setHeader('Content-Type','text/html');
  res.end(`<!doctype html><html><head><title>Workflow test</title></head><body><main></main><script type="module">
    import plugin from '/index.mjs';
    window.calls=[];window.opened=[];window.state='running';window.hidden=false;window.failList=0;window.failGet=0;window.loseLaunch=0;window.identities=new Set();
    let saved;
    window.view=plugin.surfaces[0].mount(document.querySelector('main'),{locale:'en',signal:new AbortController().signal,
      openConversation:async id=>window.opened.push(id),
      callBackend:async(action,payload)=>{
        calls.push({action,payload});
        if(action==='launch'){saved=payload;identities.add(payload.request_id);if(window.loseLaunch-- > 0)throw Error('Launch response lost');return {run_id:'fixture-run',status:'queued'};}
        if(action==='list' && window.failList-- > 0)throw Error('List refresh failed');
        if(action==='get' && window.failGet-- > 0)throw Error('Inspection refresh failed');
        if(action==='list')return {runs:saved&&!window.hidden?[{run_id:'fixture-run',status:window.state}]:[]};
        if(action==='cancel'){window.state='cancelled';return {status:'cancelling'};}
        if(action==='delete'){window.hidden=true;return {deleted:true};}
        if(action==='get')return {run_id:'fixture-run',status:window.state,script:saved.script,args:saved.args,script_hash:'script-version',args_hash:'args-version',limits:{concurrency:2,max_calls:8},steps:[{step_id:'check',agent_ref:'lead_agent',status:window.state,thread_id:'child-thread',run_id:'child-run'}],logs:['Checking'],result:'<img src=x onerror=alert(1)>'};
      }});
  </script></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
try{
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.getByRole('button',{name:'Launch workflow',exact:true}).click();
  await page.getByRole('heading',{name:'fixture-run · running',exact:true}).waitFor();
  const launch=await page.evaluate(()=>calls.find(c=>c.action==='launch'));
  assert.equal(launch.payload.request_id.length,32);
  assert.match(launch.payload.script,/await agent/);
  await page.getByRole('button',{name:'Open child conversation',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>opened),['child-thread']);
  assert.equal(await page.locator('img').count(),0);
  await page.getByRole('button',{name:'Cancel workflow',exact:true}).click();
  await page.getByRole('heading',{name:'fixture-run · cancelled',exact:true}).waitFor();
  await page.getByRole('button',{name:'Delete retained record',exact:true}).click();
  await page.waitForFunction(()=>window.hidden);
  for(const failure of ['failList','failGet','loseLaunch']){
    await page.reload();
    await page.waitForFunction(()=>calls.some(c=>c.action==='list'));
    await page.evaluate(key=>window[key]=1,failure);
    await page.getByRole('button',{name:'Launch workflow',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('button[type=submit]').disabled);
    if(failure!=='loseLaunch'){
      assert.match(await page.getByRole('status').textContent(),/fixture-run/);
      await page.getByRole('button',{name:'Retry inspection',exact:true}).click();
    }else{
      await page.getByRole('button',{name:'Launch workflow',exact:true}).click();
    }
    await page.getByRole('heading',{name:'fixture-run · running',exact:true}).waitFor();
    // Resubmitting unchanged accepted input also keeps its launch identity.
    await page.getByRole('button',{name:'Launch workflow',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('button[type=submit]').disabled);
    assert.equal(await page.evaluate(()=>identities.size),1,failure);
    await page.getByLabel('Script',{exact:true}).fill('return 43;');
    await page.getByRole('button',{name:'Launch workflow',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('button[type=submit]').disabled);
    assert.equal(await page.evaluate(()=>identities.size),2,failure);
  }
  await page.evaluate(()=>view.dispose());
  assert.equal(await page.locator('.script-workflows').count(),0);
  assert.deepEqual(errors,[]);
  console.log('Browser checks passed: launch, versioned inspection, child navigation, cancellation, escaped output, deletion and disposal.');
}finally{
  await browser.close();await new Promise(resolve=>server.close(resolve));
}
