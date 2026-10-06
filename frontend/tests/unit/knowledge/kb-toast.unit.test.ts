/**
 * 知识库中栏作用域 toast（2026-09-08）：sonner 2.x 按 toasterId 分流——带 id 的
 * Toaster 只渲染同 id 的 toast，无 id 的全局 Toaster 只渲染无 id 的。本模块是
 * 知识库树内唯一的 toast 调用面，四个方法一律注入 KB_TOASTER_ID，通知才能落在
 * 中栏（panels-shell documents 列）内的 absolute scoped Toaster 上，而不是视口
 * 右下角压住会话栏输入框。
 */
import { describe, expect, it, rs } from "@rstest/core";

import { KB_TOASTER_ID, toast } from "@/components/workspace/knowledge/kb-toast";

const sonnerMock = rs.hoisted(() => ({
  error: rs.fn(),
  info: rs.fn(),
  success: rs.fn(),
  warning: rs.fn(),
}));

rs.mock("sonner", () => ({ toast: sonnerMock }));

describe("kb-toast（中栏作用域分流）", () => {
  it("injects the middle-column toaster id on every call", () => {
    toast.info("中栏通知");
    expect(sonnerMock.info).toHaveBeenCalledWith("中栏通知", { toasterId: KB_TOASTER_ID });

    toast.success("已保存");
    expect(sonnerMock.success).toHaveBeenCalledWith("已保存", { toasterId: KB_TOASTER_ID });

    toast.warning("注意");
    expect(sonnerMock.warning).toHaveBeenCalledWith("注意", { toasterId: KB_TOASTER_ID });

    toast.error("失败");
    expect(sonnerMock.error).toHaveBeenCalledWith("失败", { toasterId: KB_TOASTER_ID });
  });

  it("preserves caller options alongside the scoped id", () => {
    toast.error("失败", { duration: 1000, description: "详情" });
    expect(sonnerMock.error).toHaveBeenCalledWith("失败", {
      duration: 1000,
      description: "详情",
      toasterId: KB_TOASTER_ID,
    });
  });
});
