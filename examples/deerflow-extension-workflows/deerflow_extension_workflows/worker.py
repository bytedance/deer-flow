"""Isolated, capability-free JavaScript worker. Only bounded JSON crosses stdio."""

import json
import math
import sys

import quickjs

MAX_FRAME = 48 * 1024

BOOT = r"""
(() => {
  const encode=JSON.stringify.bind(JSON), decode=JSON.parse.bind(JSON);
  const requests=[], pending=new Map(); let serial=0, final=null;
  const clone=value=>decode(encode(value));
  const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
  Object.defineProperty(globalThis,'agent',{value:Object.freeze(payload=>new Promise((resolve,reject)=>{
    if(pending.size>=64){reject(new Error('Pending call limit'));return;}
    const id=++serial; requests.push({type:'agent',id,payload:clone(payload)});pending.set(id,{resolve,reject});
  })),writable:false,configurable:false});
  for(const name of ['pause','humanCheckpoint','captureArtifact','readArtifact']) {
    Object.defineProperty(globalThis,name,{value:Object.freeze(payload=>new Promise((resolve,reject)=>{
      if(pending.size>=64){reject(new Error('Pending call limit'));return;}
      const id=++serial; requests.push({type:name,id,payload:clone(payload)});pending.set(id,{resolve,reject});
    })),writable:false,configurable:false});
  }
  Object.defineProperty(globalThis,'parallel',{value:Object.freeze(tasks=>{
    if(!Array.isArray(tasks)||tasks.length>64) throw new Error('Parallel item limit');
    return Promise.all(tasks.map(task=>task()));
  }),writable:false,configurable:false});
  Object.defineProperty(globalThis,'log',{value:Object.freeze(text=>{
    if(requests.length>=64)throw new Error('Message limit');requests.push({type:'log',text:String(text)});
  }),writable:false,configurable:false});
  return {
    launch:(source,args)=>{
      Object.defineProperty(globalThis,'args',{value:freeze(decode(args)),writable:false,configurable:false});
      const run=(0,eval)('(async()=>{"use strict";\n'+source+'\n})()');
      run.then(value=>{final=encode({type:'result',value:value===undefined?null:value});},
               error=>{final=encode({type:'error',message:String(error)});});
    },
    take:()=>encode(requests.splice(0)), result:()=>final,
    deliver:raw=>{const m=decode(raw),p=pending.get(m.id);if(!p)throw new Error('Unknown response');
      pending.delete(m.id);m.error?p.reject(new Error(m.error)):p.resolve(m.value);}
  };
})()
"""


def read():
    line = sys.stdin.buffer.readline(MAX_FRAME + 1)
    if not line or len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise ValueError("Invalid IPC frame")
    return json.loads(line)


def write(value):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode() + b"\n"
    if len(raw) > MAX_FRAME:
        raise ValueError("IPC output limit")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main():
    request = read()
    # No generated Python, callbacks, imports, environment or OS bindings are exposed.
    # OS limits complement the JS engine; parent wall deadlines work on all hosts.
    try:
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (math.ceil(request["cpu_seconds"]), math.ceil(request["cpu_seconds"]) + 1),
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except ImportError:
        pass
    ctx = quickjs.Context()
    ctx.set_memory_limit(request["memory_bytes"])
    ctx.set_max_stack_size(256 * 1024)
    ctx.set_time_limit(0.05)
    ctx.eval("globalThis.__bridge = " + BOOT)
    launch = ctx.eval("__bridge.launch")
    take = ctx.eval("__bridge.take")
    result = ctx.eval("__bridge.result")
    deliver = ctx.eval("__bridge.deliver")
    ctx.eval("delete globalThis.__bridge")
    launch(request["script"], json.dumps(request["args"]))
    while True:
        # Bound each JS turn and require a parent round trip between batches.
        for _ in range(64):
            if not ctx.execute_pending_job():
                break
        messages = json.loads(take())
        outcome = result()
        write({"messages": messages, "outcome": json.loads(outcome) if outcome else None})
        if outcome:
            return
        response = read()
        for message in response["responses"]:
            deliver(json.dumps(message))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # Never return a Python traceback or worker environment to generated code.
        write(
            {
                "messages": [],
                "outcome": {
                    "type": "error",
                    "message": "Script failed or exceeded worker limits",
                },
            }
        )
        sys.exit(1)
