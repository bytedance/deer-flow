import { mountBookmarks } from "./chunks/bookmarks.mjs";

export default {
  apiVersion: 1,
  module: "bookmarks.v1",
  icon: "bookmark",
  surfaces: [
    {
      id: "library",
      slot: "page",
      title: "Bookmarks",
      navigation: {
        label: "My bookmarks",
        labelZh: "我的书签",
        icon: "bookmark",
      },
      mount: mountBookmarks,
    },
  ],
  conversationActions(_t, locale = "en") {
    const zh = locale.startsWith("zh");
    return {
      label: zh ? "书签" : "Bookmarks",
      icon: "bookmark",
      actions: [
        {
          id: "save-answer",
          label: zh ? "收藏最后一条回答" : "Save last answer",
          icon: "bookmark",
          available: (settings) => settings.enabled === true,
          async execute(context, services) {
            const answer = await services.latestVisibleAnswer(context);
            if (!answer) {
              services.showMessage(
                zh ? "暂无可收藏的回答" : "No visible answer to save",
              );
              return;
            }
            if (answer.text.length > 12000) {
              services.showMessage(
                zh
                  ? "回答超过 12,000 字符，暂不支持收藏。"
                  : "Answers longer than 12,000 characters cannot be bookmarked yet.",
              );
              return;
            }
            await services.callBackend("save", {
              thread_id: context.thread.thread_id,
              message_id: answer.id,
              label: answer.text.replace(/\s+/g, " ").trim().slice(0, 80),
              text: answer.text,
            });
            services.showMessage(
              zh
                ? "已收藏，可从侧边栏打开“我的书签”查看"
                : "Saved. Open My bookmarks in the sidebar.",
            );
          },
        },
      ],
    };
  },
};
