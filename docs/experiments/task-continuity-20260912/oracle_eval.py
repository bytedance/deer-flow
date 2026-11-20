from __future__ import annotations

import argparse
import asyncio
import json

from common import PROTOCOL, ROOT, LiveClient, digest, tokens, write_json
from prepare import render_history
from public_eval import READER_SYSTEM, grade


async def run(args):
    entries = json.loads((ROOT/"public-manifest.json").read_text())["test"]
    diagnostic = json.loads((ROOT/"diagnostic-protocol.json").read_text())
    client = LiveClient(args.endpoints, concurrency=2)
    sem = asyncio.Semaphore(2)
    async def one(entry):
        async with sem:
            cid=entry["id"]
            try:
                case=json.loads((ROOT/"cases/public"/f"{cid}.json").read_text())
                gold=json.loads((ROOT/"gold/public"/f"{cid}.json").read_text())
                sessions=set(map(str,gold["evidence_sessions"]))
                history=render_history([r for r in case["records"] if r["session_id"] in sessions])
                messages=[{"role":"system","content":READER_SYSTEM},
                          {"role":"user","content":f"<historical_context>\n{history}\n</historical_context>\n\nQuestion date: {case['question_date']}\nCurrent question: {case['question']}"}]
                answer=await client.chat(messages,max_tokens=PROTOCOL["answer_max_output_tokens"],tag=f"{cid}:oracle_reader")
                prediction=answer["message"].get("content") or ""
                judgement=await grade(case,gold,prediction,client)
                row={"id":cid,"abstention":gold["abstention"],"prediction":prediction,"grade":judgement,
                     "reader_metrics":answer["metrics"],"context_tokens_proxy":tokens(history),
                     "diagnostic_protocol_hash":digest(diagnostic),"reader_request":answer["request_hash"]}
                write_json(ROOT/"results/oracle"/f"{cid}.json",row)
                print(f"oracle_done {cid} {int(judgement['correct'])}",flush=True)
                return row
            except Exception as exc:
                result={"id":cid,"error_type":type(exc).__name__,"message":str(exc)}
                write_json(ROOT/"results/oracle_failures"/f"{cid}.json",result)
                return result
    try:
        rows=await asyncio.gather(*(one(e) for e in entries))
        write_json(ROOT/"results/oracle-run.json",{"rows":rows,"calls":client.calls})
    finally:
        await client.close()


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--endpoints",required=True)
    asyncio.run(run(p.parse_args()))
