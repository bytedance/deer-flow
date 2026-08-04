"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import {
  installMarketSkill,
  loadMarketSkills,
  type MarketSkill,
  uninstallMarketSkill,
} from "@/core/skills/market-api";

export function SkillMarketPage() {
  const [skills, setSkills] = useState<MarketSkill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);

  const reload = async () => {
    try {
      setError(null);
      setSkills(await loadMarketSkills());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "技能市场加载失败");
    }
  };
  const uninstall = async (skill: MarketSkill) => {
    setWorkingId(skill.id);
    try {
      await uninstallMarketSkill(skill.id);
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "技能移除失败");
    } finally {
      setWorkingId(null);
    }
  };
  useEffect(() => void reload(), []);

  const install = async (skill: MarketSkill, update: boolean) => {
    setWorkingId(skill.id);
    try {
      await installMarketSkill(skill.id, update);
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "技能安装失败");
    } finally {
      setWorkingId(null);
    }
  };

  if (error) return <p className="text-destructive text-sm">{error}</p>;
  if (skills.length === 0)
    return <p className="text-muted-foreground text-sm">暂无已发布的技能。</p>;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-sm">
        市场技能会安装到你的独立技能空间。已安装版本不会自动覆盖，可自行选择更新。
      </p>
      {skills.map((skill) => {
        const installed = skill.installed_version !== null;
        const updateAvailable =
          installed && skill.installed_version !== skill.version;
        return (
          <Item className="w-full" key={skill.id} variant="outline">
            <ItemContent>
              <ItemTitle>{skill.name}</ItemTitle>
              <ItemDescription className="whitespace-pre-wrap">
                {skill.description}
              </ItemDescription>
              <p className="text-muted-foreground mt-2 text-xs">
                最新版本 {skill.version}
                {installed ? ` · 已安装 ${skill.installed_version}` : ""}
              </p>
            </ItemContent>
            <ItemActions>
              {!installed ? (
                <Button
                  disabled={workingId === skill.id}
                  onClick={() => void install(skill, false)}
                  size="sm"
                >
                  安装
                </Button>
              ) : updateAvailable ? (
                <div className="flex items-center gap-2">
                  <Button
                    disabled={workingId === skill.id}
                    onClick={() => void install(skill, true)}
                    size="sm"
                  >
                    更新到最新
                  </Button>
                  <Button
                    disabled={workingId === skill.id}
                    onClick={() => void uninstall(skill)}
                    size="sm"
                    variant="outline"
                  >
                    移除
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground text-sm">已安装</span>
                  <Button
                    disabled={workingId === skill.id}
                    onClick={() => void uninstall(skill)}
                    size="sm"
                    variant="outline"
                  >
                    移除
                  </Button>
                </div>
              )}
            </ItemActions>
          </Item>
        );
      })}
    </div>
  );
}
