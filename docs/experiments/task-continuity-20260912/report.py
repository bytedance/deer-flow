from __future__ import annotations

import collections
import copy
import json
import math
import random
import statistics
from pathlib import Path

from common import PROTOCOL, ROOT, digest, write_json


def paired(a, b):
    pairs = list(zip(a, b, strict=True))
    if not pairs:
        return None
    differences = [int(y)-int(x) for x,y in pairs]
    rng = random.Random(PROTOCOL["seed"])
    boots = sorted(sum(rng.choice(differences) for _ in pairs)/len(pairs) for _ in range(10000))
    wins = sum(not x and y for x,y in pairs)
    losses = sum(x and not y for x,y in pairs)
    n = wins+losses
    p = min(1., 2*sum(math.comb(n,k) for k in range(min(wins,losses)+1))/2**n) if n else 1.
    return {"difference_pp": 100*sum(differences)/len(pairs), "ci95_pp": [100*boots[249],100*boots[9749]],
            "wins": wins, "losses": losses, "n": len(pairs), "mcnemar_exact_p": p}


def wilson(successes, total):
    if not total:
        return [0.,0.]
    p=successes/total;z=1.95996398454
    center=(p+z*z/(2*total))/(1+z*z/total)
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [center-half, center+half]


def load_rows(kind):
    manifest=json.loads((ROOT/("public-manifest.json" if kind=="public" else "task-manifest.json")).read_text())
    rows=[];missing=[]
    for entry in manifest["test"]:
        path=ROOT/"results"/kind/f"{entry['id']}.json"
        if path.exists():
            row=json.loads(path.read_text())
            if row.get("protocol_hash") != digest(PROTOCOL):
                raise ValueError(f"Protocol mismatch in {entry['id']}")
            rows.append(row)
        else:
            missing.append(entry["id"])
    return rows,missing,len(manifest["test"])


def summarize(kind,rows,missing,total):
    key="stratum" if kind=="public" else "family"
    def ok(row,arm):
        return bool(row["arms"][arm]["grade"]["correct"] and row["arms"][arm]["grade"]["valid"]) if kind=="public" else bool(row["arms"][arm]["verified_completion"] and not row["arms"][arm]["constraint_violations"])
    result={"selected":total,"completed":len(rows),"missing":missing,"arms":{},"paired":{},"by_group":{}}
    for arm in "ABCD":
        count=sum(ok(r,arm) for r in rows)
        reader_key="reader_metrics" if kind=="public" else "actor_cost"
        total_prompt=0;total_completion=0
        for r in rows:
            summary=r["summary_cost"];notes=r["notes_cost"]
            usage=r["arms"][arm][reader_key]
            usage=usage.get("usage",{}) if kind=="public" else usage
            total_prompt+=summary["prompt_tokens"]+usage.get("prompt_tokens",0)+(notes["prompt_tokens"] if arm!="A" else 0)
            total_completion+=summary["completion_tokens"]+usage.get("completion_tokens",0)+(notes["completion_tokens"] if arm!="A" else 0)
        result["arms"][arm]={"correct":count,"accuracy_selected":count/total,"accuracy_completed":count/len(rows) if rows else None,
                              "wilson95":wilson(count,total),"wilson95_completed":wilson(count,len(rows)),"logical_llm_prompt_tokens":total_prompt,"logical_llm_completion_tokens":total_completion,
                              "avg_context_tokens":statistics.mean(r["arms"][arm]["context_tokens_proxy"] for r in rows) if rows else None}
        if kind=="tasks":
            result["arms"][arm].update({"constraint_violations":sum(r["arms"][arm]["constraint_violations"] for r in rows),
                "failed_validations":sum(r["arms"][arm]["failed_validations"] for r in rows),
                "search_calls":sum(r["arms"][arm]["search_calls"] for r in rows),
                "read_calls":sum(r["arms"][arm]["read_calls"] for r in rows),
                "correct_artifacts":sum(r["arms"][arm]["correct_artifact"] for r in rows),
                "validation_only_incomplete":sum(r["arms"][arm]["correct_artifact"] and not r["arms"][arm]["verified_completion"] for r in rows),
                "context_budget_stops":sum(any(e.get("reason")=="cumulative_context_budget" for e in r["arms"][arm]["events"]) for r in rows),
                "field_accuracy":sum(sum(r["arms"][arm]["field_correct"].values()) for r in rows)/sum(len(r["arms"][arm]["field_correct"]) for r in rows) if rows else None})
    for a,b in [("A","B"),("B","C"),("C","D"),("A","D")]:
        result["paired"][f"{b}-{a}"]=paired([ok(r,a) for r in rows],[ok(r,b) for r in rows])
    for group in sorted({r[key] for r in rows}):
        selected=[r for r in rows if r[key]==group]
        result["by_group"][group]={"n":len(selected),**{a:sum(ok(r,a) for r in selected) for a in "ABCD"}}
    result["summary_truncations"]=sum(r["summary_cost"]["truncated_generations"] for r in rows)
    result["notes_truncations"]=sum(r["notes_cost"]["truncated_generations"] for r in rows)
    result["compaction_count"]=sum(r["compactions"] for r in rows)
    if kind=="public":
        result["retrieval"]={}
        for mode in ["keyword","hybrid","dense"]:
            metrics=[r["retrieval"][mode]["metrics"] for r in rows if not r["abstention"]]
            result["retrieval"][mode]={k:statistics.mean(m[k] for m in metrics if m[k] is not None) if metrics else None
                for k in ["session_recall","all_evidence_sessions","record_recall","any_evidence_record","context_tokens"]}
            times=[r["retrieval"][mode]["metrics"]["seconds"] for r in rows]
            result["retrieval"][mode]["median_search_seconds"]=statistics.median(times) if times else None
        result["invalid_note_refs"]=sum(r["invalid_note_refs"] for r in rows)
        result["invalid_judge_outputs"]=sum(not r["arms"][a]["grade"]["valid"] for r in rows for a in "ABCD")
        result["reader_truncations"]={a:sum(r["arms"][a]["reader_metrics"]["finish_reason"] == "length" for r in rows) for a in "ABCD"}
        result["embedding_proxy_tokens"]=sum(r.get("embedding_proxy_tokens",0) for r in rows)
    return result


def pct(n):
    return "—" if n is None else f"{100*n:.1f}%"


def emit_table(result):
    labels={"A":"滚动摘要＋近期消息","B":"A＋来源笔记","C":"B＋关键词回查","D":"B＋向量混合回查"}
    if result["completed"] != result["selected"]:
        lines=["| 方案 | 正确/有效样本 | 有效样本正确率 | 按全部选定样本计的保守成功率 | 平均初始记忆上下文 token |",
               "|---|---:|---:|---:|---:|"]
        for a in "ABCD":
            v=result["arms"][a]
            context="—" if v["avg_context_tokens"] is None else f"{v['avg_context_tokens']:.0f}"
            lines.append(f"| {a}：{labels[a]} | {v['correct']}/{result['completed']} | {pct(v['accuracy_completed'])} | {pct(v['accuracy_selected'])} | {context} |")
        return lines
    lines=["| 方案 | 正确/选定样本 | 成功率 | 平均初始记忆上下文 token |", "|---|---:|---:|---:|"]
    for a in "ABCD":
        v=result["arms"][a]
        n=v["avg_context_tokens"]
        lines.append(f"| {a}：{labels[a]} | {v['correct']}/{result['selected']} | {pct(v['accuracy_selected'])} | {n:.0f} |" if n is not None else f"| {a}：{labels[a]} | 0/{result['selected']} | 0.0% | — |")
    return lines


def continued_rows(rows):
    updated = copy.deepcopy(rows)
    info = {"processed_cases": 0, "continued_arms": 0, "newly_verified": 0, "added_model_calls": 0,
            "added_prompt_tokens": 0, "added_completion_tokens": 0, "failures": []}
    for row in updated:
        path = ROOT / "results/continued" / f"{row['id']}.json"
        if not path.exists():
            continue
        ext = json.loads(path.read_text())
        assert ext["original_result_hash"] == digest(row)
        info["processed_cases"] += 1
        info["failures"].extend({"id": row["id"], **f} for f in ext["failures"])
        for arm, v in ext["continued_arms"].items():
            info["continued_arms"] += 1
            info["newly_verified"] += not row["arms"][arm]["verified_completion"] and v["result"]["verified_completion"]
            for key in ["added_model_calls", "added_prompt_tokens", "added_completion_tokens"]:
                info[key] += v[key]
            row["arms"][arm] = v["result"]
    return updated, info


def make_report():
    public,p_missing,p_total=load_rows("public")
    tasks,t_missing,t_total=load_rows("tasks")
    p=summarize("public",public,p_missing,p_total)
    t=summarize("tasks",tasks,t_missing,t_total)
    known_entries=json.loads((ROOT/"known-goal-manifest.json").read_text()) if (ROOT/"known-goal-manifest.json").exists() else []
    known=[];k_missing=[]
    for entry in known_entries:
        path=ROOT/"results/tasks"/f"{entry['id']}.json"
        if path.exists():
            known.append(json.loads(path.read_text()))
        else:
            k_missing.append(entry["id"])
    k=summarize("tasks",known,k_missing,len(known_entries)) if known_entries else None
    continued_t, tc_info = continued_rows(tasks)
    continued_k, kc_info = continued_rows(known)
    tc = summarize("tasks", continued_t, t_missing, t_total)
    kc = summarize("tasks", continued_k, k_missing, len(known_entries)) if known_entries else None
    oracle=[json.loads(f.read_text()) for f in (ROOT/"results/oracle").glob("*.json")]
    o={"completed":len(oracle),"selected":p_total,"correct":sum(r["grade"]["correct"] and r["grade"]["valid"] for r in oracle),
       "answerable_n":sum(not r["abstention"] for r in oracle),
       "answerable_correct":sum(not r["abstention"] and r["grade"]["correct"] for r in oracle)}
    public_run_path = ROOT / "results/public-test-run.json"
    public_run = json.loads(public_run_path.read_text()) if public_run_path.exists() else {}
    selected_ids = {r["id"] for r in public} | set(p_missing)
    public_failed_ids = {r["id"] for r in public_run.get("failures", [])}
    public_failed_ids |= {json.loads(f.read_text())["id"] for f in (ROOT / "results/public_failures").glob("*.json")}
    public_failed_ids &= selected_ids
    unresolved_failures = set(p_missing) & public_failed_ids
    public_settled = not p_missing or bool(public_run) and set(p_missing) <= public_failed_ids
    recovery_path = ROOT / "recovery-state.json"
    recovery_settled = json.loads(recovery_path.read_text())["closed"] if recovery_path.exists() else True
    continuation_settled = tc_info["processed_cases"] == t_total and kc_info["processed_cases"] == len(known_entries)
    complete = public_settled and recovery_settled and not t_missing and not k_missing and len(oracle) == p_total and continuation_settled
    result={"protocol_hash":digest(PROTOCOL),"public":p,"tasks":t,"known_goal":k,"oracle_diagnostic":o,
            "continued_tasks":tc,"continued_known_goal":kc,"continuation_tasks_info":tc_info,
            "continuation_known_info":kc_info,"evaluation_finished":complete,"public_operational_failures":sorted(unresolved_failures),
            "public_initial_failure_ids":sorted(public_failed_ids)}
    write_json(ROOT/"results/summary.json",result)
    lines=["# DeerFlow 任务接续增强：真实模型对照实验", "", "作者：Aari", "",
           "**状态：实验仍在运行，本文件为进度快照，不能当最终成绩。**" if not complete else "**状态：实验及预算续跑已结束；运行失败与模型质量分开列示。**", "",
           "本报告评估一个独立的回放与接续原型，未修改或部署 DeerFlow 生产运行时。A 沿用本地指定 commit 所安装 LangChain 的默认摘要提示词；压缩阈值、输出预算和保留范围按本实验设置，不能把其分数称为生产 DeerFlow 的默认性能。",
           "",f"完成度：公开样本 {len(public)}/{p_total}；受控执行任务 {len(tasks)}/{t_total}。质量统计使用完成样本；另列以全部选定样本为分母、将运行失败计为未成功的保守值。缺失 ID 另见 JSON。", "",
           "## 1. 公开历史问答", "", "固定版本的 LongMemEval-S cleaned，七个分层各六例，开发样本与测试样本不重叠。按数据集给定的 session 顺序处理历史，保留原日期，最后揭示问题；笔记和摘要均不能访问考题、答案、has_answer 或证据标签。", "",
           "公开测试集中 16/42 例的给定 session 顺序并非日期单调递增；本实验保持数据集原顺序，没有事后重排。它是历史问答回放，不能直接视为按真实时间产生的任务轨迹；受控任务另用三阶段顺序历史。", ""]
    lines+=emit_table(p)
    if public_failed_ids:
        lines += ["", f"截至此刻，{len(public_failed_ids)} 例出现过接口失败；其中 {len(public_failed_ids - unresolved_failures)} 例已通过缓存恢复产生有效结果，{len(unresolved_failures)} 例尚无完整结果。原失败记录保留在 results/public_failures/，不会因为恢复成功而删除。"]
    if p_missing:
        lines += ["", "尚无有效四组结果的公开样本：" + ", ".join(p_missing) + "。选定样本成功率将它们对四组统一按未成功计入；配对增益只使用完成的样本，分母需区分。"]
    lines += ["", "## 2. 三次压缩后的受控执行", "", "自建六类合成任务模板，每类四个变体，共 24 例，涵盖纠正、失败方案、单位转换、精确产物、约束和来源追溯。固定历史前缀经过三次压缩后，模型使用原生工具调用写出真实 JSON 文件并通过独立校验。环境为受控模拟，不代表开放式软件开发、浏览器操作或生产故障恢复的完整验收。", ""]
    lines+=emit_table(t)
    if k:
        lines += ["", "### 目标从开始就明确的接续对照", "",
                  "另取每个任务类型的 00、01 变体，共 12 例；把最终目标提前放入最初用户请求及每次交接消息，其他事实、干扰信息、纠正、工具和预算相同。此条件更贴近持续完成一个已知工作目标。它与上述 24 例回顾式交接任务分开统计。", ""]
        lines += emit_table(k)
    lines += ["",f"阅读诊断：只提供官方标注的正确来源 session，完成 {o['completed']}/{p_total}，答对 {o['correct']} 例；其中有答案问题 {o['answerable_correct']}/{o['answerable_n']}。这利用了 oracle 来源选择，只用于识别阅读/评分局限，不能算作可部署检索方案或向量收益。", ""]
    lines += ["", "### 产物正确与完成验证分开统计", "", "主指标要求写出正确文件、调用校验通过，并且没有被禁止的写入动作。以下同时报告文件本身正确的数量，以区分事实错误与工具步骤未收尾。", "", "| 条件 | 方案 | 产物正确 | 完成验证 | 文件正确但未完成验证 | 上下文预算停止 | 禁止动作次数 |", "|---|---|---:|---:|---:|---:|---:|"]
    for name,r in [("回顾式交接",t)]+([("已知目标接续",k)] if k else []):
        for a,v in r["arms"].items():
            lines.append(f"| {name} | {a} | {v['correct_artifacts']}/{r['selected']} | {v['correct']}/{r['selected']} | {v['validation_only_incomplete']} | {v['context_budget_stops']} | {v['constraint_violations']} |")
    lines += ["", "### 用户要求放宽预算后的接续结果", "",
              "保留上述原始成绩。对所有方案中因 8 步或累计 48,000 token 代理预算停止的样本，恢复完全相同的缓存轨迹，再继续到最多 24 步、192,000 token 代理预算。成功样本及主动结束的样本不重跑；连续四次重复已见操作，或没有新历史证据却连续四次校验失败时停止。检索次数、提示词、模型和验收标准保持不变。这是看到预算问题后按用户要求新增的续跑条件，不能冒充原始预注册结果。", ""]
    lines += ["回顾式交接：", ""] + emit_table(tc)
    if kc:
        lines += ["", "已知目标接续：", ""] + emit_table(kc)
    for name, info in [("回顾式交接", tc_info), ("已知目标接续", kc_info)]:
        lines += ["", f"{name}已处理 {info['processed_cases']} 例；续跑 {info['continued_arms']} 条方案轨迹，新增验收成功 {info['newly_verified']} 条；最终保留轨迹相较原预算增加 {info['added_model_calls']} 次逻辑模型调用，输入 {info['added_prompt_tokens']:,} token、输出 {info['added_completion_tokens']:,} token。续跑运行错误 {len(info['failures'])} 条。"]
    lines += ["", "## 3. 配对增益", "", "下表单位是绝对百分点，区间为按样本配对 bootstrap 的 95% 区间；小样本探索性分析，不作总体保证。合成任务的同模板变体具有相关性，这些区间不能当作真实任务总体的显著性证据。如果所有配对差值为零，经验 bootstrap 会退化为 [0, 0]，这不代表已经证明总体收益恰好为零。D−C 才是向量混合检索的额外贡献。", "",
              "| 测试 | 比较 | 增益（百分点） | 95% 区间 | 新增正确 / 新增错误 |", "|---|---|---:|---|---|"]
    for name,r in [("公开问答",p),("回顾式交接原预算",t),("回顾式交接放宽后",tc)]+([("已知目标原预算",k),("已知目标放宽后",kc)] if k else []):
        for comparison,v in r["paired"].items():
            if v:
                lines.append(f"| {name} | {comparison} | {v['difference_pp']:+.1f} | [{v['ci95_pp'][0]:+.1f}, {v['ci95_pp'][1]:+.1f}] | {v['wins']} / {v['losses']} |")
    lines += ["", "## 4. 分类型结果", "", "| 测试类型 | n | A 正确 | B 正确 | C 正确 | D 正确 |", "|---|---:|---:|---:|---:|---:|"]
    for source in [p,t]:
        for name,v in source["by_group"].items():
            lines.append(f"| {name} | {v['n']} | {v['A']} | {v['B']} | {v['C']} | {v['D']} |")
    lines += ["", "## 5. 检索、成本与边界", "", "检索指标使用官方证据 session/turn 标签；命中一个带答案的原始 turn 不保证返回的局部 chunk 包含了全部答案。另在 gpt4_68e94288 核对到 turn 标签缺口：C/D 都返回了正确活动原文，但该 turn 未被 has_answer 标记，自动 turn 召回为 0。保留官方标签原值，这些指标只作诊断，最终质量还需问答、实际证据及任务验收共同判断。dense 复用了 query embedding 缓存，因此不比较其耗时。", "",
              "| 检索方式 | 证据 session 平均召回 | 找齐证据 session | 证据 turn 平均召回 | 中位查询耗时 |", "|---|---:|---:|---:|---:|"]
    for mode,v in p.get("retrieval",{}).items():
        seconds="—" if mode=="dense" or v["median_search_seconds"] is None else f"{1000*v['median_search_seconds']:.0f} ms"
        lines.append(f"| {mode} | {pct(v['session_recall'])} | {pct(v['all_evidence_sessions'])} | {pct(v['record_recall'])} | {seconds} |")
    lines += ["", f"已完成公开样本的向量索引输入共 {p['embedding_proxy_tokens']:,} 个代理 token（只计索引，不含查询）。混合检索还需要查询向量；索引可在后续回查中复用。查询耗时含本次服务与运行环境因素，不代表生产延迟保证。"]
    lines += ["", "所有组使用同一模型、温度、历史和硬上限。A/B/C 消耗的上下文长度不同，因此 B−A 不等于严格 token 等量条件下的纯表示收益；C/D 的原始索引、分块、返回预算相同。以下逻辑成本给每个方案完整计入其所需摘要、笔记和回答/执行调用，共享缓存不会把成本虚构为零。评分器成本不计入产品执行成本。", "",
              "| 测试 | 方案 | LLM 输入 token | LLM 输出 token |", "|---|---|---:|---:|"]
    for name,r in [("公开问答",p),("回顾式交接",t)]+([("已知目标接续",k)] if k else []):
        for a,v in r["arms"].items():
            lines.append(f"| {name} | {a} | {v['logical_llm_prompt_tokens']:,} | {v['logical_llm_completion_tokens']:,} |")
    groups = [("公开", p), ("回顾式受控任务", t)] + ([("已知目标", k)] if k else [])
    summary_limits = "，".join(f"{name} {r['summary_truncations']}/{r['compaction_count']} 次" for name,r in groups)
    notes_limits = "，".join(f"{name} {r['notes_truncations']}/{r['compaction_count']} 次" for name,r in groups)
    lines += ["", f"摘要触及生成上限：{summary_limits}；笔记触及上限：{notes_limits}。这些结果保留并计入成绩，没有用标准答案修复。",
              "", "公开最终回答触及生成上限的次数：" + ", ".join(a + "=" + str(n) for a,n in p["reader_truncations"].items()) + "。原回答及 finish_reason 均保留；执行任务的预算续跑不修改公开问答的生成条件。",
              "", "模型：qwen3.8-flash-next；向量：Qwen3-Embedding-0.6B，1024 维，查询使用英文检索任务指令并作 L2 归一化。端点与令牌只位于实验目录外的临时私有配置中。",
              "", "公开 QA 使用官方评判提示词，但评判模型换成同一个授权 Qwen 模型，因此不与官方 GPT-4o leaderboard 分数直接比较。受控任务用确定性文件校验，不依赖 LLM 裁判。",
              "", "成本为返回有效 usage 的逻辑调用用量。服务端断连或中止调度时，供应商未返回用量的在途工作无法计入；早期无进展检测调整中未进入最终轨迹的缓存调用也不在方案逻辑成本内。因此不能把此表当作整个实验的供应商计费总账。并发调整记录在 operational-events.json。",
              "", "## 6. 复现文件", "", "- protocol.json：测试前固定的方法与预算。", "- public-manifest.json / task-manifest.json：开发与测试 ID。", "- memory/：每一步摘要、笔记、来源引用和调用元数据。", "- results/public/、results/tasks/：逐样本答案、工具轨迹、检索命中和成绩。", "- results/summary.json：机器可读汇总与配对统计。", "- workspaces/：模型实际写出的任务产物。", "- cache/：按完整请求哈希记录的响应，可断点复现；不含端点或鉴权头。", "- continuation-protocol.json / results/continued/：放宽预算的规则及续跑结果。", "- CASE_NOTES.md：已核对案例，区分预算、记忆信息与阅读行为问题。", "- results/audit.json：文件、缓存、输入顺序和结果身份核对。", "",
              "参考：[LongMemEval](https://github.com/xiaowu0162/LongMemEval)、[LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2)、[OpenClaw session search](https://docs.openclaw.ai/concepts/session-search)、[Codex 实验配置](https://learn.chatgpt.com/docs/config-file/config-reference)。本轮实际运行的是 LongMemEval-S 与自建受控任务，没有运行 V2 或 LoCoMo。", ""]
    conclusion_path = ROOT / "CONCLUSIONS.md"
    if complete and conclusion_path.exists():
        metadata = json.loads((ROOT / "conclusion-metadata.json").read_text())
        if metadata["summary_hash"] != digest(result):
            raise ValueError("Results changed; regenerate conclusions instead of publishing stale claims")
        lines[5:5] = ["", conclusion_path.read_text(), ""]
    (ROOT/"REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"public":{"completed":len(public),"scores":{a:v['correct'] for a,v in p['arms'].items()}},
                      "tasks":{"completed":len(tasks),"scores":{a:v['correct'] for a,v in t['arms'].items()}}}))
    return result


if __name__=="__main__":
    make_report()
