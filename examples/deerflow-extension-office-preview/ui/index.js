export default {
  apiVersion: 1,
  module: "office-preview",
  artifactPreviews: [{
    id: "office",
    extensions: ["xlsx", "docx", "pptx"],
    mount(root, context) {
      let dispose = () => {};
      import("./office.js").then(async ({ mountOffice }) => {
        if (context.signal.aborted) return;
        dispose = await mountOffice(root, context);
        if (context.signal.aborted) dispose();
      }).catch(() => { if (!context.signal.aborted) context.onError(); });
      return { dispose() { dispose(); root.replaceChildren(); } };
    },
  }],
};
