import { mountReview } from "./review.mjs";

export default {
  apiVersion: 1,
  module: "batch-review.v1",
  icon: "layers",
  surfaces: [{
    id: "results",
    slot: "page",
    title: "Batch result review",
    navigation: { label: "Batch reports", labelZh: "批任务报告", icon: "layers" },
    mount: mountReview,
  }],
  conversationActions(_t, locale = "en") {
    const zh = locale.startsWith("zh");
    return {
      label: zh ? "批任务报告" : "Batch reports",
      icon: "layers",
      actions: [{
        id: "review",
        label: zh ? "审阅本会话结果" : "Review this conversation's results",
        icon: "layers",
        available: (settings) => settings.enabled === true,
        async execute(context, services) {
          if (!services.openPluginPage) {
            services.showMessage(zh ? "宿主不支持会话页面导航，请从侧边栏打开批任务报告。" : "Open Batch reports from the sidebar; this host lacks page navigation.");
            return;
          }
          services.openPluginPage("results", context.thread.thread_id);
        },
      }],
    };
  },
};
