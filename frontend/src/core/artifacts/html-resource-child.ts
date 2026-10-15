/** Runs only inside the existing opaque sandbox; the parent owns authorization. */
export const HTML_ARTIFACT_CHILD = String.raw`
(() => {
  const nonce = __DEERFLOW_NONCE__;
  const pending = new Map();
  const blobs = new Set();
  const cache = new Map();
  const nativeFetch = window.fetch.bind(window);
  let port, baseURL, nextId = 0, stopped = false;
  const close = () => {
    if (stopped) return;
    stopped = true;
    for (const waiter of pending.values()) waiter.reject(new DOMException("Document retired", "AbortError"));
    pending.clear();
    for (const url of blobs) URL.revokeObjectURL(url);
    blobs.clear(); cache.clear();
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
    try {return new URL(reference,from).origin === new URL(baseURL).origin;} catch {return true;}
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
    port = event.ports[0];baseURL = event.data.plan.baseURL;
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
        let value=entry.css ? await stylesheet(entry.css,baseURL,[]) : await resource(entry.reference,entry.kind,baseURL);
        if (entry.css && value.startsWith("x{")) value=value.slice(2,-1);
        return [entry.token,entry.attribute ? value.replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;") : value];
      }));
      if (stopped) return;
      for (const [token,value] of replacements) html=html.replaceAll(token,()=>value);
      const resumeName="__deerflow_resume_"+nonce;
      window[resumeName]=() => {window.fetch=fetchResource;window.addEventListener("pagehide",close,{once:true});delete window[resumeName];};
      // document.open clears listeners. Reinstall before parser-executed author scripts.
      html=html.replace("<head>","<head><script>window["+JSON.stringify(resumeName)+"]();<"+"/script>");
      document.open();document.write(html);document.close();
    } catch {close();document.body.textContent="Unable to load report resources";}
  };
  window.addEventListener("message",connect);
  window.addEventListener("pagehide",close,{once:true});
  parent.postMessage({type:"deerflow-html-ready",nonce},"*");
})();
`;
