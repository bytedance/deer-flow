import { mountCenter } from "./center.mjs";

export default {
  apiVersion: 1,
  module: "knowledge-center.v1",
  icon: "book-open",
  surfaces: [
    {
      id: "library",
      slot: "page",
      title: "Knowledge center",
      navigation: {
        label: "Knowledge center",
        labelZh: "知识中心",
        icon: "book-open",
      },
      mount: mountCenter,
    },
  ],
};
