from __future__ import annotations

import argparse
import asyncio
import json

from common import ROOT, LiveClient, digest, write_json
from task_eval import evaluate_case


def prepare():
    source=json.loads((ROOT/"task-manifest.json").read_text())["test"]
    chosen=[e for e in source if e["id"].endswith(("-00","-01"))]
    entries=[]
    for entry in chosen:
        old=entry["id"];new="known-"+old
        case=json.loads((ROOT/"cases/tasks"/f"{old}.json").read_text())
        gold=json.loads((ROOT/"gold/tasks"/f"{old}.json").read_text())
        case.update(id=new,split="known_goal",original_case=old)
        case["goal"]="Current persistent objective: "+case["question"]+" Collect the approved values during the work and preserve their sources."
        case["records"][0]["content"]=case["goal"]
        for record in case["records"]:
            if record["content"].startswith("Day ") and "handoff:" in record["content"]:
                record["content"]="Handoff: continue the same current objective. "+case["goal"]+" Retain previous corrections and verification results."
        gold["id"]=new
        write_json(ROOT/"cases/tasks"/f"{new}.json",case)
        write_json(ROOT/"gold/tasks"/f"{new}.json",gold)
        entries.append({"id":new,"original_case":old,"family":entry["family"],"history_hash":digest(case["records"])})
    write_json(ROOT/"known-goal-manifest.json",entries)
    return entries


async def run(args):
    entries=prepare()
    client=LiveClient(args.endpoints,concurrency=4)
    sem=asyncio.Semaphore(2)
    async def one(entry):
        async with sem:
            try:
                result=await evaluate_case(entry,client)
                result["original_case"]=entry["original_case"]
                result["diagnostic_protocol_hash"]=digest(json.loads((ROOT/"known-goal-protocol.json").read_text()))
                write_json(ROOT/"results/tasks"/f"{entry['id']}.json",result)
                return result
            except Exception as exc:
                error={"id":entry["id"],"error_type":type(exc).__name__,"message":str(exc)}
                write_json(ROOT/"results/known_goal_failures"/f"{entry['id']}.json",error)
                print("known_goal_failed "+entry["id"],flush=True)
                return error
    try:
        rows=await asyncio.gather(*(one(e) for e in entries))
        write_json(ROOT/"results/known-goal-run.json",{"rows":rows,"calls":client.calls})
    finally:
        await client.close()


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--endpoints",required=True)
    asyncio.run(run(p.parse_args()))
