"use client";

/**
 * 合成候选题审核面板（2026-08-28 spec §6.2，plan Task 11；2026-09-07 底部
 * 停靠重设计；2026-09-08 常驻化）：题库视图**底部常驻容器**（检索测试路容器
 * 同款范式）——无候选时收为单行头承载空态/上次合成元信息，有候选时展开与
 * 表格区 2:1 分高（flex-1 ≈ 1/3），候选列表在容器内 ScrollArea 内滚，页面
 * 高度不随候选数增长。
 * 头部（2026-09-08）：Inbox 图标（暂存待办收件盘隐喻——候选落入等待取出/
 * 丢弃，空态即空收件盘；与生成动作的 Sparkles 区分，也不与采纳钮 Check
 * 撞语义）+ semibold 标题与正文区分；计数徽章改琥珀「圆点+文字」胶囊
 * （wiki 待更新同款配方）；右簇 = 丢弃芯片 → ⓘ（ⓘ 钉最右）；**批量动作
 * （全部采纳/全部忽略）收进标题行右键菜单**（wiki-panel 头部右键先例，
 * 头部只留状态不留动作钮）。元信息裸行退役：来源文档标题+相对时间收
 * ⓘ tooltip；丢弃仅 >0 显琥珀芯片（tooltip 承载原因）。候选卡右键菜单
 * 承接行级采纳/忽略（2026-09-08）；卡内按钮保留（双入口）。候选必须人工
 * 审核——采纳经题库唯一写路径入库（accept → add_question），忽略仅移出
 * 暂存；批量动作逐条串行（后端无批量端点——整体替换语义下暂存量小）。
 * 轮询由 useSynthesisStatus 的 refetchInterval 门控（in_progress 时 3s），
 * 本组件只消费数据。
 * B′ 锚定拦截（2026-10-05）：采纳被锚定核验 422 拦下时该候选卡动作行下方
 * 出红块（key = candidate_id），原「采纳」重提恒不带确认（盲双击不绕过），
 * 仅红块内「仍要接受」以 anchor_ack=true 覆盖（missing_chunk 不可覆盖，无
 * 确认钮）；审核面无表单输入，红块留存至该卡被采纳/忽略。
 */
import { Check, Inbox, Info, Loader2, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { formatKnowledgeRelativeTime, refDocIds } from "@/core/knowledge/format";
import {
  useAcceptSynthesisCandidate,
  useDocuments,
  useRejectSynthesisCandidate,
  useSynthesisStatus,
} from "@/core/knowledge/hooks";
import { cn } from "@/lib/utils";

import { AnchorBlockNotice } from "./anchor-block-notice";
import { toast } from "./kb-toast";
import { useAnchorConfirm } from "./use-anchor-confirm";

export interface EvalSynthesisReviewProps {
  kbId: string;
  /** keep-alive 懒门控（与题库查询同开关）。 */
  enabled?: boolean;
}

export function EvalSynthesisReview({ kbId, enabled = true }: EvalSynthesisReviewProps) {
  const { t, locale } = useI18n();
  const etk = t.knowledge.eval;
  const stk = etk.synthesize;
  const qtk = etk.questions;
  const status = useSynthesisStatus(kbId, enabled);
  // 来源文档标题（与参考文档列同 queryKey，缓存命中不新增请求）；取不到回退 id 前 8 位。
  const docsQuery = useDocuments(kbId);
  const accept = useAcceptSynthesisCandidate(kbId);
  const reject = useRejectSynthesisCandidate(kbId);
  // B′ 锚定拦截（2026-10-05）：key = candidate_id，各候选卡独立红块。
  const anchor = useAnchorConfirm();
  // 收起态（2026-09-07）：默认展开（审核是短任务，展开一次审完）；无候选时
  // 强制单行头（常驻空态不白占 1/3 高），collapsed 仅对有候选态生效。
  const [collapsed, setCollapsed] = useState(false);

  const data = status.data;
  const candidates = data?.candidates ?? [];
  const hasCandidates = candidates.length > 0;
  const inProgress = Boolean(data?.in_progress);
  const expanded = hasCandidates && !collapsed;

  // 采纳载荷共用（原按钮与红块确认仅 anchor_ack 不同）：原按钮恒不带确认重提。
  const acceptCandidate = (candidateId: string, ack: boolean) =>
    accept.mutateAsync({ candidate_id: candidateId, anchor_ack: ack });

  const handleAccept = async (candidateId: string) => {
    try {
      const accepted = await anchor.submit(candidateId, (ack) => acceptCandidate(candidateId, ack));
      if (!accepted) return;
      toast.success(qtk.addedToast);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : stk.acceptFailed);
    }
  };

  // 红块内「仍要接受」：anchor_ack=true 覆盖词条级拦截后走正常采纳收尾。
  const handleAcceptConfirmed = async (candidateId: string) => {
    try {
      const accepted = await anchor.confirm(candidateId, (ack) => acceptCandidate(candidateId, ack));
      if (!accepted) return;
      toast.success(qtk.addedToast);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : stk.acceptFailed);
    }
  };

  const handleReject = async (candidateId: string) => {
    try {
      await reject.mutateAsync(candidateId);
      // 该卡退出暂存，其红块一并退场（无表单输入可清）。
      anchor.clear(candidateId);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : stk.rejectFailed);
    }
  };

  const handleRejectAll = async () => {
    for (const candidate of candidates) {
      await handleReject(candidate.candidate_id);
    }
  };

  // 全部采纳（2026-09-08）：逐条 accept；成功只发一条 toast（逐条会刷屏）。
  // B′：逐条走无确认提交——被拦的落各自红块，不发错误 toast。
  const handleAcceptAll = async () => {
    const results = await Promise.allSettled(
      candidates.map((candidate) => anchor.submit(candidate.candidate_id, (ack) => acceptCandidate(candidate.candidate_id, ack))),
    );
    if (results.some((result) => result.status === "rejected")) {
      toast.error(stk.acceptFailed);
    } else if (results.some((result) => result.status === "fulfilled" && result.value)) {
      toast.success(qtk.addedToast);
    }
  };

  // ⓘ tooltip 文案：来源文档标题（≤2 篇全列、更多收「等 N 篇」）+ 相对时间。
  // doc_ids 是暂存级保序并集（跨未审批累加，synthesis 合并语义），审完不缩——
  // 常驻空态下仍承载「上次合成来自哪」的状态信息。
  const docTitle = (docId: string) => docsQuery.data?.find((doc) => doc.id === docId)?.name ?? docId.slice(0, 8);
  const batchDocIds = data?.doc_ids ?? [];
  const docsLine = batchDocIds.length <= 2 ? batchDocIds.map(docTitle).join("、") : `${batchDocIds.slice(0, 2).map(docTitle).join("、")} 等 ${batchDocIds.length} 篇`;
  const metaTip = data?.generated_at != null ? stk.reviewMetaTip(docsLine, formatKnowledgeRelativeTime(data.generated_at, locale)) : null;

  const busy = accept.isPending || reject.isPending;

  return (
    <section
      className={cn(
        "bg-card text-card-foreground mx-4 mt-2 flex flex-col rounded-lg border shadow-xs",
        expanded ? "min-h-0 flex-1" : "shrink-0",
      )}
      data-testid="eval-synthesis-review"
    >
      {/* 容器标题栏（检索测试路容器同款词汇）：有候选时左簇整块点击收起
          （aria-expanded、hover 底色、无 chevron）；无候选时左簇为静态状态行
          （空态/生成中），不挂 toggle。右簇 = 丢弃芯片 → ⓘ（ⓘ 钉最右）；
          批量动作收进本行右键菜单（wiki-panel 头部右键先例）；border-b 仅展开态。 */}
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div className={cn("flex items-center gap-2 px-3 py-2", expanded && "border-b")}>
        {hasCandidates ? (
          <button
            aria-expanded={!collapsed}
            className="hover:bg-muted/50 flex min-w-0 items-center gap-2 rounded-md px-2 py-0.5 text-left transition-colors"
            data-testid="eval-synthesis-review-toggle"
            type="button"
            onClick={() => setCollapsed((current) => !current)}
          >
            <Inbox className="text-muted-foreground size-4 shrink-0" />
            <span className="text-sm font-semibold">{stk.reviewTitle}</span>
            {inProgress ? (
              <span className="text-muted-foreground flex items-center gap-1 text-xs">
                <Loader2 className="size-3 animate-spin" />
                {stk.generating}
              </span>
            ) : (
              /* 待审计数（2026-09-08）：琥珀「圆点+文字」胶囊（wiki 待更新同款
                 配方）——比 muted 灰胶囊更显眼，承载「有事待办」信号。 */
              <Badge className="h-5 shrink-0 gap-1.5 bg-amber-500/15 py-0 text-amber-600 dark:text-amber-500" variant="secondary">
                <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-amber-500" />
                {stk.reviewCount(candidates.length)}
              </Badge>
            )}
          </button>
        ) : (
          /* 常驻空态单行头（2026-09-08）：承载空态/生成中状态，不白占分高。 */
          <span className="flex min-w-0 items-center gap-2 px-2 py-0.5">
            <Inbox className="text-muted-foreground size-4 shrink-0" />
            <span className="text-sm font-semibold">{stk.reviewTitle}</span>
            <span className="text-muted-foreground flex items-center gap-1 text-xs">
              {inProgress ? (
                <>
                  <Loader2 className="size-3 animate-spin" />
                  {stk.generating}
                </>
              ) : (
                stk.empty
              )}
            </span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {/* 丢弃告警：仅 >0 渲染琥珀胶囊，零值不显；原因文案沉 tooltip。 */}
          {Boolean(data && data.dropped > 0) && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="bg-amber-500/15 text-amber-600 dark:text-amber-500 cursor-default rounded-full px-2 py-0.5 text-xs tabular-nums">
                  {stk.droppedChip(data?.dropped ?? 0)}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-60 text-pretty">{stk.metaLine(data?.dropped ?? 0)}</TooltipContent>
            </Tooltip>
          )}
          {metaTip !== null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button aria-label={metaTip} className="text-muted-foreground inline-flex hover:text-foreground" type="button">
                  <Info className="size-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-60 text-pretty">{metaTip}</TooltipContent>
            </Tooltip>
          )}
        </div>
          </div>
        </ContextMenuTrigger>
        {/* 标题行右键菜单（2026-09-08）：批量动作唯一入口（头部只留状态）；
            空态右键给禁用空态项反馈，不落到浏览器默认菜单。 */}
        <ContextMenuContent className="w-40">
          {hasCandidates ? (
            <>
              <ContextMenuItem disabled={busy} onSelect={() => void handleAcceptAll()}>
                <Check className="size-4" />
                {stk.acceptAll}
              </ContextMenuItem>
              <ContextMenuItem disabled={busy} onSelect={() => void handleRejectAll()}>
                <X className="size-4" />
                {stk.rejectAll}
              </ContextMenuItem>
            </>
          ) : (
            <ContextMenuItem disabled>{stk.empty}</ContextMenuItem>
          )}
        </ContextMenuContent>
      </ContextMenu>
      {/* 候选区：容器内 ScrollArea 内滚——页面高度不随候选数增长；收起/空态
          整体卸载（同总览卡收起语义）。 */}
      {expanded && (
        <ScrollArea className="min-h-0 flex-1" scrollHideDelay={2000} type="scroll">
          <div className="flex flex-col gap-2 p-3">
            {candidates.map((candidate) => {
              // 参考切片计数（2026-10-06 列口径改造）：与题库参考切片列同语言
              // （纯数字 = 切片数 + tooltip 列文档名）——候选卡采纳后就是题库
              // 行，采纳前后同一单位；无锚定候选空单元格。
              const docIds = refDocIds(candidate.relevant_chunk_ids);
              // B′：本卡拦截红块（key = candidate_id），渲染在动作行正下方。
              const candidateBlock = anchor.blockFor(candidate.candidate_id);
              /* 候选卡（2026-09-08）：边框加深一档（border-foreground/20，默认
                 --border 在卡容器内边际不清）；右键菜单承接行级采纳/忽略，
                 卡内按钮保留作双入口。 */
              return (
              <ContextMenu key={candidate.candidate_id}>
                <ContextMenuTrigger asChild>
                  <div className="border-foreground/20 flex flex-col gap-1.5 rounded-md border p-2.5">
                <p className="text-sm">{candidate.query}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline">{etk.category[candidate.category]}</Badge>
                  {candidate.expected_paths.map((path) => (
                    <Badge key={path} variant="secondary">
                      {path}
                    </Badge>
                  ))}
                  {docIds.length > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-muted-foreground cursor-default text-xs tabular-nums">
                          {candidate.relevant_chunk_ids.length}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-60 text-pretty whitespace-pre-wrap">
                        {docIds.map(docTitle).join("\n")}
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
                {candidate.reference_answer !== null && (
                  <p className="text-muted-foreground text-xs whitespace-pre-wrap">{candidate.reference_answer}</p>
                )}
                <div className="flex items-center gap-2">
                  <Button disabled={busy} onClick={() => handleAccept(candidate.candidate_id)} size="sm">
                    <Check className="size-3.5" />
                    {stk.accept}
                  </Button>
                  <Button disabled={busy} onClick={() => handleReject(candidate.candidate_id)} size="sm" variant="outline">
                    <X className="size-3.5" />
                    {stk.reject}
                  </Button>
                </div>
                {/* B′ 红块：动作行正下方；原「采纳」保留原文案与无确认重提语义，
                    仅红块内「仍要接受」携 anchor_ack=true。 */}
                {candidateBlock !== null && (
                  <AnchorBlockNotice
                    confirmLabel={etk.anchorBlock.confirmAccept}
                    confirming={busy}
                    detail={candidateBlock}
                    onConfirm={() => void handleAcceptConfirmed(candidate.candidate_id)}
                  />
                )}
                  </div>
                </ContextMenuTrigger>
                <ContextMenuContent className="w-40">
                  <ContextMenuItem disabled={busy} onSelect={() => void handleAccept(candidate.candidate_id)}>
                    <Check className="size-4" />
                    {stk.accept}
                  </ContextMenuItem>
                  <ContextMenuItem disabled={busy} onSelect={() => void handleReject(candidate.candidate_id)}>
                    <X className="size-4" />
                    {stk.reject}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
              );
            })}
          </div>
        </ScrollArea>
      )}
    </section>
  );
}
