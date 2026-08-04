"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { Button } from "@/components/ui/button";
import {
  loadMarketSkills,
  publishMarketSkill,
  type MarketSkill,
  type MarketSkillDraft,
} from "@/core/skills/market-api";

const blank: MarketSkillDraft = {
  name: "",
  description: "",
  version: "1.0.0",
  content:
    "---\nname: example-skill\ndescription: Describe this skill.\n---\n\n# Instructions\n",
  published: true,
};

export default function SkillsPage() {
  const [items, setItems] = useState<MarketSkill[]>([]);
  const [draft, setDraft] = useState(blank);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    void loadMarketSkills(true)
      .then(setItems)
      .catch(() => setNotice("无法加载技能市场。"));
  }, []);
  useEffect(() => load(), [load]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await publishMarketSkill(draft);
      setNotice("技能已保存；已安装的租户副本不会被自动覆盖。");
      setDraft(blank);
      load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "技能保存失败。");
    }
  };
  return (
    <AdminSection
      title="技能市场"
      description="发布版本化 SKILL.md。普通用户安装后获得独立副本，后续更新仅在其主动更新时覆盖。"
    >
      {notice ? <p className="text-sm">{notice}</p> : null}
      <form className="grid gap-3 border-y py-4 md:grid-cols-2" onSubmit={save}>
        <label className="text-muted-foreground text-xs">
          技能名称
          <input
            className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
            pattern="[a-zA-Z0-9_-]+"
            required
            value={draft.name}
            onChange={(event) =>
              setDraft((value) => ({ ...value, name: event.target.value }))
            }
          />
        </label>
        <label className="text-muted-foreground text-xs">
          版本号
          <input
            className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
            required
            value={draft.version}
            onChange={(event) =>
              setDraft((value) => ({ ...value, version: event.target.value }))
            }
          />
        </label>
        <label className="text-muted-foreground text-xs md:col-span-2">
          简介
          <textarea
            className="text-foreground mt-1 min-h-16 w-full border bg-transparent p-2 text-sm"
            required
            value={draft.description}
            onChange={(event) =>
              setDraft((value) => ({
                ...value,
                description: event.target.value,
              }))
            }
          />
        </label>
        <label className="text-muted-foreground text-xs md:col-span-2">
          SKILL.md 内容
          <textarea
            className="text-foreground mt-1 min-h-48 w-full border bg-transparent p-2 font-mono text-xs"
            required
            value={draft.content}
            onChange={(event) =>
              setDraft((value) => ({ ...value, content: event.target.value }))
            }
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            checked={draft.published}
            type="checkbox"
            onChange={(event) =>
              setDraft((value) => ({
                ...value,
                published: event.target.checked,
              }))
            }
          />
          立即上架
        </label>
        <div className="flex items-end">
          <Button size="sm" type="submit">
            保存技能
          </Button>
        </div>
      </form>
      <div className="divide-y border-y">
        {items.length === 0 ? (
          <p className="text-muted-foreground py-5 text-sm">暂无市场技能。</p>
        ) : (
          items.map((item) => (
            <article
              className="flex justify-between gap-3 py-3 text-sm"
              key={item.id}
            >
              <span>
                {item.name} · {item.version}
              </span>
              <span className="text-muted-foreground">
                {item.published ? "已上架" : "未上架"}
              </span>
            </article>
          ))
        )}
      </div>
    </AdminSection>
  );
}
