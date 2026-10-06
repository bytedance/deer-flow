/**
 * 知识库中栏作用域 toast（2026-09-08）：sonner 默认 Toaster 是视口 fixed 右下角，
 * 在知识库页正好压住会话栏的输入框（用户实测遮挡）。panels-shell 的中栏
 * （documents 列）内挂了一个 `<Toaster id={KB_TOASTER_ID} style={{position:"absolute"}}>`，
 * 通知面收进「知识库详情这栏」的右下角；本模块把调用面按 toasterId 分流过去。
 *
 * sonner 2.x 的分流语义：带 id 的 Toaster 只渲染 `toasterId === id` 的 toast，
 * 无 id 的全局 Toaster 只渲染**没有** toasterId 的 toast——两侧互不重复。
 * 因此知识库树内一律从本模块取 `toast`（import 面与 sonner 同名，调用点零改动），
 * 其余页面/核心 hooks 仍走 sonner 全局面，不受影响。
 *
 * 仅覆盖知识库树内在用的四个方法；promise/custom/loading 等如需使用仍走 sonner
 * 全局面（或在此补同构包装）。
 */
import { toast as globalToast, type ExternalToast } from "sonner";

/** 中栏 scoped Toaster 的 id（挂载点在 panels-shell 的 documents 列）。 */
export const KB_TOASTER_ID = "knowledge-middle";

const scope = (options?: ExternalToast): ExternalToast => ({
  ...options,
  toasterId: KB_TOASTER_ID,
});

export const toast: Pick<typeof globalToast, "error" | "info" | "success" | "warning"> = {
  error: (message, options) => globalToast.error(message, scope(options)),
  info: (message, options) => globalToast.info(message, scope(options)),
  success: (message, options) => globalToast.success(message, scope(options)),
  warning: (message, options) => globalToast.warning(message, scope(options)),
};
