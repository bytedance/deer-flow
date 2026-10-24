/** Runs only inside the existing opaque sandbox; the parent owns authorization. */
export const HTML_ARTIFACT_CHILD = String.raw`
(() => {
  const nonce = __DEERFLOW_NONCE__;
  const pending = new Map();
  const blobs = new Set();
  const cache = new Map();
  const modules = new Map();
  const moduleAliases = new Map();
  const publishedModules = new Set();
  const moduleMetas = new WeakSet();
  const moduleHelper = "__deerflow_module_"+nonce;
  let moduleQueue = Promise.resolve();
  let moduleId = 0;
  let rendering = false;
  const nativeFetch = window.fetch.bind(window);
  let port, baseURL, sourceURL, nextId = 0, stopped = false;
  const close = () => {
    if (stopped) return;
    stopped = true;
    for (const waiter of pending.values()) waiter.reject(new DOMException("Document retired", "AbortError"));
    pending.clear();
    for (const url of blobs) URL.revokeObjectURL(url);
    blobs.clear(); cache.clear(); modules.clear();moduleAliases.clear();publishedModules.clear();delete window[moduleHelper];
    port?.postMessage({type:"close"}); port?.close();
  };
  const request = (reference, kind, from = baseURL, signal) => new Promise((resolve,reject) => {
    if (stopped || signal?.aborted) return reject(new DOMException("Document retired", "AbortError"));
    const id = ++nextId;
    const finish = (callback,value) => {pending.delete(id);signal?.removeEventListener("abort",abort);callback(value);};
    const abort = () => {port.postMessage({type:"cancel",id});finish(reject,new DOMException("Read cancelled","AbortError"));};
    pending.set(id,{resolve:value=>finish(resolve,value),reject:error=>finish(reject,error)});
    signal?.addEventListener("abort",abort,{once:true});
    port.postMessage({type:"read",id,reference,baseURL:from,kind});
  });
  const blob = (bytes,type) => {
    const url = URL.createObjectURL(new Blob([bytes],{type}));blobs.add(url);return url;
  };
  const local = (reference,from) => {
    if (!reference || reference.startsWith("#") || /^(?:data|blob):/i.test(reference)) return false;
    try {return new URL(reference,from).origin === new URL(sourceURL).origin;} catch {return true;}
  };
  const stylesheet = async (plan, from, ancestry) => {
    let text = plan.text;
    const edits = await Promise.all(plan.edits.map(async edit => ({...edit,value:JSON.stringify(await resource(edit.reference,edit.kind,from,ancestry))})));
    for (const edit of edits.sort((a,b)=>b.start-a.start)) text=text.slice(0,edit.start)+edit.value+text.slice(edit.end);
    return text;
  };
  const resource = async (reference,kind,from,ancestry = []) => {
    if (!local(reference,from)) return new URL(reference,from).href;
    const key = kind+":"+new URL(reference,from).href;
    if (ancestry.includes(key)) return "data:text/css,";
    if (!cache.has(key)) cache.set(key,(async () => {
      try {
        const result=await request(reference,kind,from);
        if (stopped) throw new DOMException("Document retired","AbortError");
        if (kind === "css") return blob(await stylesheet(result.css,result.url,[...ancestry,key]),"text/css;charset=utf-8");
        return blob(result.bytes,result.contentType)+new URL(result.url).hash;
      } catch {return "data:application/octet-stream,";}
    })());
    return cache.get(key);
  };
  const moduleRecord = (reference,from) => {
    const alias=new URL(reference,from).href;
    if (!moduleAliases.has(alias)) moduleAliases.set(alias,(async()=>{
      const result=await request(reference,"module",from);
      if (stopped) throw new DOMException("Document retired","AbortError");
      if (!modules.has(result.url)) modules.set(result.url,{id:"deerflow-module/"+nonce+"/"+(++moduleId),plan:result.module,baseURL:result.url,metaURL:result.url,contentType:result.contentType,dependencies:[],blobURL:null});
      return modules.get(result.url);
    })());
    return moduleAliases.get(alias);
  };
  const moduleEdits = record => {
    const edits=record.plan.imports.map((entry,index)=>({...entry,value:JSON.stringify(record.dependencies[index])}));
    for (const entry of record.plan.dynamic) {
      edits.push({start:entry.start,end:entry.argumentStart,value:"window["+JSON.stringify(moduleHelper)+"].load("});
      edits.push({start:entry.end-1,end:entry.end,value:(entry.hasOptions ? "" : ",undefined")+","+JSON.stringify(record.baseURL)+")"});
    }
    for (const entry of record.plan.meta) edits.push({...entry,value:"window["+JSON.stringify(moduleHelper)+"].meta(import.meta,"+JSON.stringify(record.metaURL)+")"});
    let text=record.plan.text;
    for (const edit of edits.sort((a,b)=>b.start-a.start)) text=text.slice(0,edit.start)+edit.value+text.slice(edit.end);
    return text;
  };
  const moduleMappings = () => Object.fromEntries([...modules.values()].filter(record=>record.blobURL && !publishedModules.has(record.id)).map(record=>[record.id,record.blobURL]));
  const publishModules = () => {
    const imports=moduleMappings();
    if (!Object.keys(imports).length) return;
    const script=document.createElement("script");script.type="importmap";script.textContent=JSON.stringify({imports});document.head.appendChild(script);
    for (const id of Object.keys(imports)) publishedModules.add(id);
  };
  const prepareModule = (reference,from,inline) => {
    const work=moduleQueue.then(async()=>{
      if (stopped) throw new DOMException("Document retired","AbortError");
      let root;
      if (inline) {
        root={id:"deerflow-module/"+nonce+"/"+(++moduleId),plan:inline,baseURL:from,metaURL:sourceURL,contentType:"text/javascript",dependencies:[],blobURL:null};modules.set(root.id,root);
      } else root=await moduleRecord(reference,from);
      const queue=[root],seen=new Set();
      for (const record of queue) {
        if (seen.has(record.id) || record.blobURL) continue;
        seen.add(record.id);
        for (let index=0;index<record.plan.imports.length;index++) {
          const specifier=record.plan.imports[index].reference;
          // Native import maps continue to own bare package names and public URLs.
          const urlLike=/^(?:\.?\.?\/|\/|[a-z][a-z0-9+.-]*:)/i.test(specifier);
          if (!urlLike) {record.dependencies[index]=specifier;continue;}
          if (!local(specifier,record.baseURL)) {record.dependencies[index]=new URL(specifier,record.baseURL).href;continue;}
          const dependency=await moduleRecord(specifier,record.baseURL);
          record.dependencies[index]=dependency.id;queue.push(dependency);
        }
      }
      if (stopped) throw new DOMException("Document retired","AbortError");
      // Every cycle edge has a stable import-map ID before any module executes.
      for (const record of queue) if (!record.blobURL) record.blobURL=blob(moduleEdits(record),record.contentType);
      if (rendering) publishModules();
      return root.blobURL;
    });
    moduleQueue=work.catch(()=>{});
    return work;
  };
  const loadModule = async (reference,options,from) => {
    const specifier=String(reference);
    if (!/^(?:\.?\.?\/|\/|[a-z][a-z0-9+.-]*:)/i.test(specifier)) return import(specifier,options);
    if (!local(specifier,from)) return import(new URL(specifier,from).href,options);
    const url=await prepareModule(specifier,from);
    if (stopped) throw new DOMException("Document retired","AbortError");
    return import(url,options);
  };
  const moduleMeta = (meta,url) => {
    if (!moduleMetas.has(meta)) {
      const resolve=meta.resolve?.bind(meta);
      meta.url=url;
      if (resolve) meta.resolve=specifier=>/^(?:\.?\.?\/|\/|[a-z][a-z0-9+.-]*:)/i.test(String(specifier)) ? new URL(specifier,url).href : resolve(specifier);
      moduleMetas.add(meta);
    }
    return meta;
  };
  const fetchResource = async (input,options) => {
    const reference = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!local(reference,baseURL)) return nativeFetch(input,options);
    const method = (options?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (method !== "GET" || options?.body != null) throw new TypeError("Artifact preview supports read-only file requests");
    const signal = options?.signal ?? (input instanceof Request ? input.signal : undefined);
    const result = await request(reference,"asset",baseURL,signal);
    const response = new Response(result.bytes,{status:result.status,headers:{"Content-Type":result.contentType}});
    Object.defineProperty(response,"url",{value:result.url});
    return response;
  };
  const connect = async (event) => {
    if (event.source !== parent || event.data?.type !== "deerflow-html-connect" || event.data.nonce !== nonce || !event.ports[0] || port) return;
    window.removeEventListener("message",connect);
    port = event.ports[0];baseURL = event.data.plan.baseURL;sourceURL=event.data.plan.sourceURL;
    port.onmessage = message => {
      const data=message.data;
      if (data?.type === "dispose") {close();return;}
      const waiter=pending.get(data?.id);if (!waiter || stopped) return;
      if (data.type === "resource") waiter.resolve(data);
      else if (data.type === "error") waiter.reject(new TypeError("Artifact resource unavailable"));
    };
    port.start();
    try {
      const plan=event.data.plan;
      let html=plan.html;
      const replacements=await Promise.all(plan.resources.map(async entry => {
        let value;
        if (entry.kind === "module") {
          try {value=await prepareModule(entry.reference,baseURL,entry.module);}
          catch {value=blob('throw new TypeError("Artifact module unavailable");',"text/javascript");}
        } else value=entry.css ? await stylesheet(entry.css,baseURL,[]) : await resource(entry.reference,entry.kind,baseURL);
        if (entry.css && value.startsWith("x{")) value=value.slice(2,-1);
        return [entry.token,entry.attribute ? value.replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;") : value];
      }));
      if (stopped) return;
      for (const [token,value] of replacements) html=html.replaceAll(token,()=>value);
      const resumeName="__deerflow_resume_"+nonce;
      window[resumeName]=() => {rendering=true;window[moduleHelper]={load:loadModule,meta:moduleMeta};window.fetch=fetchResource;window.addEventListener("pagehide",close,{once:true});delete window[resumeName];};
      // document.open clears listeners. Reinstall before parser-executed author scripts.
      const imports=moduleMappings();for (const id of Object.keys(imports)) publishedModules.add(id);
      const mapScript="<script type=importmap>"+JSON.stringify({imports}).replaceAll("<","\\u003c")+"<"+"/script>";
      html=html.replace("<head>","<head><script>window["+JSON.stringify(resumeName)+"]();<"+"/script>"+mapScript);
      document.open();document.write(html);document.close();
    } catch {close();document.body.textContent="Unable to load report resources";}
  };
  window.addEventListener("message",connect);
  window.addEventListener("pagehide",close,{once:true});
  parent.postMessage({type:"deerflow-html-ready",nonce},"*");
})();
`;
