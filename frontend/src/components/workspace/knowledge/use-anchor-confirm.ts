"use client";

/**
 * B′ 锚定拦截共享状态（2026-10-05）：三个入题面（添加/存为考题 dialog、
 * 合成审核面板）共用的 keyed 拦截状态机——首击「保存/采纳」不带确认提交，
 * 后端 422 结构化锚定 detail（AnchorBlockError）落成红块；原按钮重提恒不带
 * 确认（盲双击/重试不绕过），只有红块内「仍要入库/仍要接受」才以
 * anchor_ack=true 重提。missing_chunk 不可覆盖，确认后仍 422 时红块保留。
 * 其他错误原样上抛（调用方保留 toast 旧行为）。
 */
import { useCallback, useState } from "react";

import { AnchorBlockError } from "@/core/knowledge/api";
import type { AnchorBlockDetail } from "@/core/knowledge/types";

export interface UseAnchorConfirm {
  /** 当前 key 的拦截详情（无拦截返回 null）。 */
  blockFor: (key: string) => AnchorBlockDetail | null;
  /** 无确认提交（ack=false）：被拦返回 false 并落红块；成功返回 true；其他错误上抛。 */
  submit: (key: string, run: (ack: boolean) => Promise<unknown>) => Promise<boolean>;
  /** 确认提交（ack=true）：成功清红块；missing_chunk 仍被拦时重落红块返回 false。 */
  confirm: (key: string, run: (ack: boolean) => Promise<unknown>) => Promise<boolean>;
  /** 手动清红块（表单锚定输入变更时调用，下一次保存即全新机器核验）。 */
  clear: (key: string) => void;
}

export function useAnchorConfirm(): UseAnchorConfirm {
  const [blocks, setBlocks] = useState<Record<string, AnchorBlockDetail | undefined>>({});

  const clear = useCallback((key: string) => {
    setBlocks((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  const runGuarded = useCallback(
    async (key: string, ack: boolean, run: (ack: boolean) => Promise<unknown>) => {
      try {
        await run(ack);
      } catch (error) {
        if (error instanceof AnchorBlockError) {
          setBlocks((current) => ({ ...current, [key]: error.detail }));
          return false;
        }
        throw error;
      }
      clear(key);
      return true;
    },
    [clear],
  );

  const submit = useCallback(
    (key: string, run: (ack: boolean) => Promise<unknown>) => runGuarded(key, false, run),
    [runGuarded],
  );

  const confirm = useCallback(
    (key: string, run: (ack: boolean) => Promise<unknown>) => runGuarded(key, true, run),
    [runGuarded],
  );

  const blockFor = useCallback((key: string) => blocks[key] ?? null, [blocks]);

  return { blockFor, submit, confirm, clear };
}
