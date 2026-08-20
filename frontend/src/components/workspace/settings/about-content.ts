/**
 * About DeerFlow markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
import { APP_VERSION } from "@/version";

export const aboutMarkdownEnUS = `# 🦌 [About DeerFlow ${APP_VERSION}](https://github.com/bytedance/deer-flow)

> **From Open Source, Back to Open Source**

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

---

## 🚀 Core Features

* **Skills & Tools**: With built-in and extensible skills and tools, DeerFlow can do almost anything.
* **Sub-Agents**: Sub-Agents help the main agent to do the tasks that are too complex to be done by the main agent.
* **Sandbox & File System**: Safely execute code and manipulate files in the sandbox.
* **Context Engineering**: Isolated sub-agent context, summarization to keep the context window sharp.
* **Long-Term Memory**: Keep recording the user's profile, top of mind, and conversation history.

---

## 🌟 GitHub Repository

![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)

Explore DeerFlow on GitHub: [github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow)

## 🌐 Official Website

Visit the official website of DeerFlow: [deerflow.tech](https://deerflow.tech/)

## 📧 Support

If you have any questions or need help, please contact us at [support@deerflow.tech](mailto:support@deerflow.tech).

---

## 📜 License

DeerFlow is proudly open source and distributed under the **MIT License**.

---

## 🙌 Acknowledgments

We extend our heartfelt gratitude to the open source projects and contributors who have made DeerFlow a reality. We truly stand on the shoulders of giants.

### Core Frameworks
- **[LangChain](https://github.com/langchain-ai/langchain)**: A phenomenal framework that powers our LLM interactions and chains.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Enabling sophisticated multi-agent orchestration.
- **[Next.js](https://nextjs.org/)**: A cutting-edge framework for building web applications.

### UI Libraries
- **[Shadcn](https://ui.shadcn.com/)**: Minimalistic components that power our UI.
- **[SToneX](https://github.com/stonexer)**: For his invaluable contribution to token-by-token visual effects.

These outstanding projects form the backbone of DeerFlow and exemplify the transformative power of open source collaboration.

### Special Thanks
Finally, we want to express our heartfelt gratitude to the core authors of DeerFlow 1.0 and 2.0:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Without their vision, passion and dedication, \`DeerFlow\` would not be what it is today.
`;

export const aboutMarkdownZhCN = `# 🦌 [关于 DeerFlow ${APP_VERSION}](https://github.com/bytedance/deer-flow)

> **源于开源，回馈开源**

DeerFlow（**D**eep **E**xploration and **E**fficient **R**esearch **Flow**，深度探索与高效研究流程）是一个开源的**超级智能体框架**。它通过编排**子智能体**、**记忆**与**沙箱**，并借助**可扩展的技能**，几乎可以完成任何任务。

---

## 🚀 核心特性

* **技能与工具**：借助内置和可扩展的技能与工具，DeerFlow 几乎可以完成任何任务。
* **子智能体**：子智能体帮助主智能体处理那些过于复杂、难以靠主智能体独自完成的任务。
* **沙箱与文件系统**：在沙箱中安全地执行代码并操作文件。
* **上下文工程**：隔离子智能体上下文，通过摘要让上下文窗口保持精简。
* **长期记忆**：持续记录用户的画像、近期关注与对话历史。

---

## 🌟 GitHub 仓库

![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)

在 GitHub 上探索 DeerFlow：[github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow)

## 🌐 官方网站

访问 DeerFlow 官方网站：[deerflow.tech](https://deerflow.tech/)

## 📧 支持

如有任何疑问或需要帮助，请通过 [support@deerflow.tech](mailto:support@deerflow.tech) 联系我们。

---

## 📜 许可证

DeerFlow 自豪地开源，并遵循 **MIT License** 分发。

---

## 🙌 致谢

我们衷心感谢那些让 DeerFlow 成为现实的开源项目与贡献者。我们真正站在巨人的肩膀上。

### 核心框架
- **[LangChain](https://github.com/langchain-ai/langchain)**：一个出色的框架，为我们的 LLM 交互与链路提供支撑。
- **[LangGraph](https://github.com/langchain-ai/langgraph)**：实现复杂的多智能体编排。
- **[Next.js](https://nextjs.org/)**：一个前沿的 Web 应用构建框架。

### UI 库
- **[Shadcn](https://ui.shadcn.com/)**：极简组件，支撑我们的界面。
- **[SToneX](https://github.com/stonexer)**：感谢他为逐 token 渲染特效做出的宝贵贡献。

这些杰出的项目构成了 DeerFlow 的骨干，展现了开源协作的变革力量。

### 特别感谢
最后，我们衷心感谢 DeerFlow 1.0 与 2.0 的核心作者：

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

没有他们的远见、热情与奉献，就不会有今天的 \`DeerFlow\`。
`;
