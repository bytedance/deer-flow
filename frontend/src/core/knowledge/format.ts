/**
 * Shared timestamp rendering for knowledge panels (document table, wiki
 * entries). Locale follows the active i18n locale; unparsable values render
 * verbatim.
 */
export function formatKnowledgeTimestamp(
  value: string,
  locale: string,
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** 相对时间单位阈值（从大到小，匹配第一个满足的单位）。 */
const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 1000 * 60 * 60 * 24 * 365],
  ["month", 1000 * 60 * 60 * 24 * 30],
  ["day", 1000 * 60 * 60 * 24],
  ["hour", 1000 * 60 * 60],
  ["minute", 1000 * 60],
];

/**
 * 相对时间渲染（2026-09-02，方案 Task 2）：列偏好 timeFormat="relative" 时用。
 * Intl.RelativeTimeFormat(numeric:"auto") 输出「昨天/3天前/2小时前」等自然表达；
 * <1 分钟硬编码「刚刚/just now」（Intl 对亚分钟无稳定自然词）。now 可注入便于测试。
 * 不可解析值原样返回（同 formatKnowledgeTimestamp）。
 */
export function formatKnowledgeRelativeTime(
  value: string,
  locale: string,
  now: number = Date.now(),
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const lang = locale === "zh-CN" ? "zh-CN" : "en-US";
  const diffMs = date.getTime() - now; // 负=过去，正=未来
  if (Math.abs(diffMs) < 60_000) {
    return lang === "zh-CN" ? "刚刚" : "just now";
  }
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  for (const [unit, ms] of RELATIVE_UNITS) {
    if (Math.abs(diffMs) >= ms) {
      return rtf.format(Math.round(diffMs / ms), unit);
    }
  }
  // 兜底（理论上 <1min 已拦截，不会到这）：按分钟。
  return rtf.format(Math.round(diffMs / 60_000), "minute");
}

/**
 * 视频时长渲染（spec 2026-09-08 §5，plan Task 9）：列表接口注入的
 * ``duration_ms``（末镜 end_ms）转播放器风格的定长时码。不足一小时
 * 用 ``M:SS``（首位不补零，如 ``12:34``），超一小时进位 ``H:MM:SS``（如
 * ``1:02:34``）——与常见视频平台的时长显示一致，秒级取整。
 */
export function formatVideoDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${minutes}:${pad(seconds)}`;
}

/**
 * 镜头时间码（spec 2026-09-08 §5，plan Task 10）：PTS 毫秒转定长 ``HH:MM:SS``
 * （小时恒两位补零，不同于时长徽章的变长 ``formatVideoDuration``）——切片抽屉
 * 芯片需逐位对齐的等宽时间码，与后端镜头卡 ``format_timecode`` 同口径（去毫秒）。
 */
export function formatShotTimecode(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

/** 镜头时间码区间 ``HH:MM:SS–HH:MM:SS``（en dash，对齐 spec §5 芯片文案）。 */
export function formatTimecodeRange(startMs: number, endMs: number): string {
  return `${formatShotTimecode(startMs)}–${formatShotTimecode(endMs)}`;
}

/**
 * 剥掉摘要开头的 markdown 一级标题行（2026-09-03）。
 * 后端 summary = content[:120]（knowledge_service.list_wiki_entries），而 content 由提示词
 * 强制以「# 实体名」H1 开头（wiki/generator.py WIKI_SYSTEM_PROMPT），故列表摘要会以原始
 * markdown「# 标题」起头。标题已在行内单独渲染，这里只剥掉这行 H1、保留正文；正文首段常
 * 再含标题（"DeerFlow 是一个…"），那是有语义的定义句，按用户口径保留、不去重。
 * 非 # 开头原样返回（人工卡片内容通常无 H1）。
 */
export function stripSummaryHeading(summary: string): string {
  return summary.replace(/^#{1,6}[^\n]*\n?/, "").trim();
}

/**
 * 切片单行预览文本（2026-09-05，刻度轨弹窗与检索测试行共用）：
 * 取切片最深层标题，否则首非空行并剥掉 markdown 标记。
 */
export function chunkPreview(chunk: {
  heading_path?: string[];
  text: string;
}): string {
  const heading = chunk.heading_path?.at(-1)?.trim();
  if (heading) return heading;
  const line =
    chunk.text
      .split("\n")
      .map((value) => value.trim())
      .find(Boolean) ?? "";
  return line.replace(/^[#>*+-]+\s*/, "");
}

/**
 * 正文前 N 非空行（2026-09-05）：剥 markdown 行首标记、内联 html 标签与
 * 星号/反引号后空格连接。检索测试行预览用 maxLines=1——正文首行够长
 * 能填满行宽（标题做预览会因标题过短留大片空白，2026-09-05 回退定案）。
 */
export function textLead(text: string, maxLines = 2): string {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, maxLines)
    .map((line) =>
      line
        .replace(/<[^>]+>/g, " ")
        .replace(/^[#>*+-]+\s*/, "")
        .replace(/[*`]/g, "")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter(Boolean)
    .join(" ");
}

/**
 * 参考文档去重计数源（2026-09-08 上提共享）：relevant_chunk_ids 的 `#` 前
 * doc_id 前缀去重（同文档多切片算 1 篇）；无锚定返回空数组。题库参考文档
 * 列与合成候选卡共用——行/卡级计数统一「篇」语言，切片级分解属下钻层。
 */
export function refDocIds(chunkIds: string[]): string[] {
  const seen: string[] = [];
  for (const chunkId of chunkIds) {
    const docId = chunkId.split("#")[0];
    if (docId && !seen.includes(docId)) seen.push(docId);
  }
  return seen;
}
