# DeerFlow 前端性能修复：流式渲染 DOM 过多导致浏览器卡顿

## 问题诊断

当 Agent 返回大量内容时（长文本回复），浏览器出现卡顿甚至卡死。

### 根因

**`rehypeSplitWordsIntoSpans` 插件导致 DOM 节点爆炸。**

**位置**: `src/core/rehype/index.ts`

**机制**:
- 流式输出时（`thread.isLoading === true`），rehype 插件对**消息中每一个段落、标题、列表项**做逐词拆分
- 每个词包裹为 `<span className="animate-fade-in">`
- 一段 1000 字的消息 ≈ 500+ 个 span DOM 节点
- 随着流式输出内容增长，前端已渲染的稳定内容也在不断被重建为大量 span

```
修复前的 DOM 结构：
<p><span>第</span><span>一</span><span>段</span>...</p>   ← 200 个 span
<p><span>第</span><span>二</span><span>段</span>...</p>   ← 200 个 span
<p><span>正</span><span>在</span><span>输</span>...</p>   ← 100 个 span
                                                          = 500 个 span（且持续增长）
```

### 次要因素

- 每次 token 到达都触发 React 全树重渲染（`useSyncExternalStore` + 无 throttle）
- `groupMessages()` 无缓存，每次渲染 O(n) 遍历
- `Intl.Segmenter` 每次 rehype 处理都 `new` 一个新实例

---

## 修复方案

### 已实施：只对最后一段做逐词动画

**修改文件**: `src/core/rehype/index.ts`

**思路**: 打字机效果只需要体现在"正在被打字输出"的那一段文字上，已经输出完成的段落无需保留逐词 span。将 DOM 节点数从 **O(总字数)** 降为 **O(最后一段字数)**。

**改动内容**:

1. 先收集 AST 中所有块级元素（p, h1-h6, li），只对**最后一个**做逐词拆分
2. 前面的块级元素保持普通文本节点，不做任何处理
3. `Intl.Segmenter` 改为模块级单例，避免每次重建

```
修复后的 DOM 结构：
<p>第一段全部内容...</p>                  ← 1 个 text node
<p>第二段全部内容...</p>                  ← 1 个 text node
<p><span>正</span><span>在</span>...</p>  ← ~50 个 span（仅最后一段）
                                                          = ~50 span + 少量 text node
```

修复后的完整代码见 `src/core/rehype/index.ts`。

### 已实施：流式更新节流

**修改文件**: `src/core/threads/hooks.ts:119`

在 `useStream` 调用中添加 `throttle: 100`，将 100ms 内的多次 token 更新合并为一次渲染，渲染频率从每秒几十次降到最多 10 次。

```typescript
const thread = useStream<AgentThreadState>({
  // ...
  throttle: 100,
  // ...
});
```

---

## 涉及文件清单

| 文件 | 修改内容 |
|------|----------|
| `src/core/rehype/index.ts` | 只对最后一个块级元素做逐词拆分；复用 Segmenter 实例 |
| `src/core/threads/hooks.ts` | 添加 `throttle: 100` |

---

## 验证方式

1. 打开 Chrome DevTools → Performance 面板
2. 发送一条会让 Agent 返回长文本内容的消息（1000 字以上）
3. 录制性能数据，观察 Scripting（黄色）和 Rendering（紫色）耗时
4. 打开 Elements 面板，检查 DOM 节点数量——消息区域内不应出现大量 `<span class="animate-fade-in">`
5. 确认打字机动画仅出现在最后一段文字上，前面内容正常显示
