export default {
  apiVersion: 1,
  module: "office-preview",
  artifactPreviews: [
    {
      id: "office",
      extensions: ["xlsx", "docx", "pptx"],
      mount(root, context) {
        const controller = new AbortController();
        const abort = () => controller.abort();
        context.signal.addEventListener("abort", abort, { once: true });
        if (context.signal.aborted) abort();
        let dispose = () => {};
        import("./office.js")
          .then(async ({ mountOffice }) => {
            if (controller.signal.aborted) return;
            dispose = await mountOffice(root, {
              ...context,
              signal: controller.signal,
            });
            if (controller.signal.aborted) dispose();
          })
          .catch(() => {
            if (!controller.signal.aborted) context.onError();
          });
        return {
          dispose() {
            controller.abort();
            context.signal.removeEventListener("abort", abort);
            dispose();
            root.replaceChildren();
          },
        };
      },
    },
  ],
};
