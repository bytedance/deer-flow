/**
 * About brand markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
export const aboutMarkdown = `# [About {{brandName}}]({{githubUrl}})

> **Sovereign, Adaptive, and Secure**

{{brandName}} is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

---

## 🚀 Core Features

* **Skills & Tools**: With built-in and extensible skills and tools, {{brandName}} can do almost anything.
* **Agent Sawrms**: Agent Sawrms help the main agent to do the tasks that are too complex to be done by the main agent.
* **Sandbox & File System**: Safely execute code and manipulate files in the sandbox.
* **Context Engineering**: Isolated sub-agent context, summarization to keep the context window sharp.
* **Long-Term Memory**: Keep recording the user's profile, top of mind, and conversation history.

---

## 🌐 Official Website

Visit the official website of {{brandName}}: [{{websiteUrl}}]({{websiteUrl}})

## 📧 Support

If you have any questions or need help, please contact us at [{{supportEmail}}](mailto:{{supportEmail}}).

---

## 🙌 Acknowledgments

We extend our heartfelt gratitude to all the future investors and clients who have made {{brandName}} a reality. We truly stand on the shoulders of giants.

`;
