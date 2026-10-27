from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

root=Path(__file__).resolve().parent
data=json.loads((root/"results/summary.json").read_text())
if not data.get("evaluation_finished"):
    raise ValueError("Refuse to plot before evaluation finishes")
groups=[("public","Historical QA",f"LongMemEval-S; {data['public']['completed']} valid / 42 selected"),
        ("continued_tasks","Retrospective handoff","24 tasks; extended execution budget"),
        ("continued_known_goal","Known-goal continuation","12 tasks; extended execution budget")]
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False})
fig,axs=plt.subplots(1,3,figsize=(13.2,4.6),sharey=True)
colors=["#9AA6B2","#6387A3","#278A88","#D99632"]
for ax,(key,title,subtitle) in zip(axs,groups):
    result=data[key]
    if result is None:
        raise ValueError("Missing comparison")
    values=[result["arms"][a]["accuracy_completed"]*100 for a in "ABCD"]
    lows=[result["arms"][a]["wilson95_completed"][0]*100 for a in "ABCD"]
    highs=[result["arms"][a]["wilson95_completed"][1]*100 for a in "ABCD"]
    ax.bar(range(4),values,color=colors,width=.62,zorder=3)
    ax.errorbar(range(4),values,yerr=[np.maximum(0,np.array(values)-lows),np.maximum(0,np.array(highs)-values)],fmt="none",ecolor="#334155",capsize=4,linewidth=1.2,zorder=4)
    for i,a in enumerate("ABCD"):
        v=result["arms"][a]
        ax.text(i, min(110,highs[i]+4),f"{v['correct']}/{result['completed']}",ha="center",fontweight="bold",fontsize=10)
    ax.set_xticks(range(4),["A\nSummary","B\n+ Notes","C\n+ Keyword","D\n+ Hybrid"])
    ax.set_title(title+"\n"+subtitle,fontsize=11,pad=15)
    ax.set_ylim(0,117)
    ax.set_yticks([0,25,50,75,100])
    ax.grid(axis="y",alpha=.18,zorder=0)
axs[0].set_ylabel("Correct / valid cases (%)")
fig.suptitle("Session continuity: results under forced context compression",fontsize=15,fontweight="bold",y=.99)
failed=len(data.get("public_operational_failures",[]))
fig.text(.5,.015,f"Qwen3.8-Flash-Next + Qwen3-Embedding-0.6B | QA provider failures: {failed}, reported separately from quality bars\nResearch prototype. Wilson intervals are descriptive; template variants are correlated. Original scores retained in report.",ha="center",fontsize=9,color="#52606D")
fig.tight_layout(rect=[0,.10,1,.94])
fig.savefig(root/"results/comparison.png",dpi=180,bbox_inches="tight",facecolor="white")
fig.savefig(root/"results/comparison.svg",bbox_inches="tight",facecolor="white")
print(root/"results/comparison.png")
