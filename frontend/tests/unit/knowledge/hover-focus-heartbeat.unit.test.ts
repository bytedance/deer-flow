/**
 * hover 聚焦心跳控制器（3D mouseout 不派发 bug 的修复，2026-08-15 诊断）：
 * echarts-gl 在「散点 → 空白」时不派发 mouseout，hover 聚焦会永久卡住。
 * 修复：zr mousemove（全画布恒派发）武装定时器，chart mousemove hit（每次
 * 派发）复位——移到空白后定时器到期清除聚焦；在点上慢移不会误清。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { createHoverFocusHeartbeat } from "@/components/workspace/knowledge/vector-canvas";

describe("createHoverFocusHeartbeat 心跳清除", () => {
  beforeEach(() => {
    rs.useFakeTimers();
  });
  afterEach(() => {
    rs.useRealTimers();
  });

  it("fires onClear after the delay when only armed (moved to blank)", () => {
    const onClear = rs.fn();
    const hb = createHoverFocusHeartbeat(onClear, 150);
    hb.arm(); // 画布内移动
    rs.advanceTimersByTime(149);
    expect(onClear).not.toHaveBeenCalled();
    rs.advanceTimersByTime(1);
    expect(onClear).toHaveBeenCalledTimes(1);
    hb.dispose();
  });

  it("does not fire while hits keep feeding (slow move across a point)", () => {
    const onClear = rs.fn();
    const hb = createHoverFocusHeartbeat(onClear, 150);
    // 模拟在点上连续移动：arm 与 hit 交替，心跳不断复位
    for (let i = 0; i < 5; i++) {
      hb.arm();
      hb.feedHit();
      rs.advanceTimersByTime(100);
    }
    expect(onClear).not.toHaveBeenCalled();
    hb.dispose();
  });

  it("rearms after a hit: moving to blank clears again", () => {
    const onClear = rs.fn();
    const hb = createHoverFocusHeartbeat(onClear, 150);
    hb.arm();
    hb.feedHit(); // 命中
    rs.advanceTimersByTime(300); // 停在点上不动：无事件，不应误清
    expect(onClear).not.toHaveBeenCalled();
    hb.arm(); // 移到空白
    rs.advanceTimersByTime(150);
    expect(onClear).toHaveBeenCalledTimes(1);
    hb.dispose();
  });

  it("dispose silences a pending timer", () => {
    const onClear = rs.fn();
    const hb = createHoverFocusHeartbeat(onClear, 150);
    hb.arm();
    hb.dispose();
    rs.advanceTimersByTime(300);
    expect(onClear).not.toHaveBeenCalled();
  });
});
