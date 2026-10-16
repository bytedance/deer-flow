> 用户已于 2026-10-16 明确要求继续，当前已恢复，最新验证见文末 #116。下面暂停段为历史记录；完整 M0–M11 目标继续保留。

# 2026-10-16 暂停与恢复检查点

以下为先前用户要求暂停时保存的历史快照。用户已于 2026-10-16 明确要求继续；当前执行状态以文首及文末恢复检查点为准，完整 M0–M11 目标保留，不能把当前子项当作总目标。

- 工作树：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`。
- 分支：`codex/tenant-workspaces-plan`；环境默认的 `1d28/deerflow2` 是另一棵 checkout，不要在那边修改。
- 最后完整验证并提交的代码：`3fb8ed75`，上海 `deerflow-tenant-frontend #100 SUCCESS`。原生预览图片、嵌套 CSS、普通脚本和 GET 数据主干、必要退役/只读边界，40 项原有回归及完整 pnpm check 通过。
- 本次新增模块加载代码按 **WIP** 保存，**尚未验收、未格式化、未运行完整 lint/类型检查**。Git WIP 提交只作恢复快照，不代表通过。

## 当前 WIP 与结果

新增 `frontend/src/core/artifacts/html-module-plan.ts`，用已有缓存版本 `@babel/parser@7.29.9` 解析导入、重导出、动态导入与 import.meta。原生 HTML 计划区分模块脚本、把内联模块接入同一通道；父页面仍用已有同线程 GET 字节读取。子页面用稳定 import-map ID、原生浏览器执行和自身 Blob 装配模块图及循环，动态导入复用模块实例。普通资源主干未宣布新增验收范围；这套模块实现还需要调试和验证。

- `#101 FAILURE` 是实际浏览器 RED：两个空间的图片/CSS/普通脚本/数据刷新正常；相对模块导入报 `Invalid relative url or base scheme isn't hierarchical`，模块内容停在 waiting。说明缺的是 Blob 模块的依赖解析。
- `#102 FAILURE`：已打包新增实现并启动浏览器，但 `page.wait_for_load_state("networkidle")` 在 30000ms 超时；模块主干断言尚未执行，`-html.json` 为空。不能认为模块已跑通，也不能只延长超时来掩盖根因。
- #101/#102 均已终止；按专属 label 核实容器和网络为空。没有留下运行中的 DeerFlow 构建，未处理其他 Jenkins 项目。
- 构建终态、归档摘要、WIP 源文件摘要在 progress JSON 的 `frontend_html_module_wip`。#102 归档与此 WIP 的八个代码/依赖/夹具文件逐字节相同。

## 下次接续

1. 先读此文件和 `docs/tenant-workspaces-progress.json`，核对 Git 状态及 Jenkins 当前状态；不要因观察超时而重启旧构建。
2. 调查 #102：在初始 networkidle 等待失败前收集 pageerror、浏览器请求及模块图/端口情况，确定卡在何处。现有探针的这次超时在结果捕获 try 之外，因而丢失了主干 JSON；先改善失败观测，再修实际根因。
3. 先跑通同一 P/T 模块主干：静态/循环/重导出、内联模块、字面量/计算式动态导入、模块实例复用、import.meta 相对数据请求。之后只补必要的模块拒绝和退役边界。
4. 云端格式、定向 lint、完整 tsc 和 pnpm check 通过后再更新验收。解析器使用缓存中的锁定版本；不要在本机运行 Node/应用/浏览器/pytest 或 Docker Desktop。
5. 剩余 HTML 资源行为、Next/真实 Gateway/主体与双标签页、原生 shell/selector、M4–M11 等仍须推进。全部父项保持未验收，`_WORKSPACE_RUNTIME_INTEGRATED = False`。

## 上海执行约束

Jenkins：`106.14.210.163`，只管理 DeerFlow 专属任务。SSH 密钥位置沿用现有配置。Jenkins 密码只允许在服务器本机内存使用，不输出、不复制。固定镜像沿用 #100 的 compiler/browser IDs，不拉新镜像。只清理本项目精确 label，不做全局 prune、不触碰 assetforge。

无部署、远程推送、模型调用或本地应用运行。当前停在可恢复 WIP，不是功能完成点。


M3 scoped module checkpoint (2026-10-16): resume from WIP 216ac886. #103 records
initial networkidle timeout with no outstanding requests and no main assertions.
Keep production code unchanged, use existing confirmed-space/resource/module
output assertions for readiness: #104 SUCCESS (P/T module main, 16 regressions).
Only then extend the same browser fixture with JSON options and module refusal/
MIME/held-read retirement/reopen: #105 SUCCESS, 40 existing regressions/five files.
A temporary formatter found Next's reserved local variable `module`; rename it
modulePlan while preserving the DTO key. #106 SUCCESS: same main/boundaries,
40 existing regressions, five-file format/target lint, early full tsc and required
full pnpm check. No new Rstest cases. Repeated-import checks now wait for both
async actions to settle. Exact source/archive/image/terminal/empty resources:
frontend_html_modules in progress JSON; earlier #101/#102 pause evidence retained.

Babel plans module source ranges; child import-map IDs/Blobs and a canonical URL
registry leave execution, cycles, top-level await, JSON attributes and instance
caching to the browser. Parent same-thread captured byte reader is unchanged.
Import.meta retains native object identity with logical source URL/resolution.
MIME remains authoritative: text/plain module body does not execute. Dynamic
module reads cannot proxy ordinary APIs/foreign threads. Hidden report aborts
held module and data transport; old bootstrap is revoked; fresh same-space
module/data preview survives. Sandbox/Cookie policy and activation gate stay.

Proof is native React/Auth/Workspace/REST/iframe in pinned Chromium against an
HttpOnly Cookie/scope server and env/router build doubles; not compiled Next,
Gateway/JWT/SQL/NAS, live principal/two-tab or physical proof. Native DOM paragraph/
div and KaTeX diagnostics remain; expected MIME/revoked-Blob console errors belong
to negative probes, page errors are empty. General HTML/import-map/dynamic media/
CSS compatibility remains unaccepted. Next prioritize the approved native space
switcher/shell and actual backend upload/chat/download main; retain these HTML
and other M3/principal/physical requirements. All M0-M11 parent gates unchecked,
M3 partial, activation false. No deployment, push, model call or local app runtime.


M3 native switcher checkpoint (2026-10-16, #113 SUCCESS): actual existing
WorkspaceHeader/Sidebar/Dropdown now selects server-confirmed personal/team
spaces through WorkspaceSession. Only confirmed names display. Pending removes
private report content and keeps the menu usable. Denial has explicit retry,
personal confirmation and sign-in controls; retry retains target, no silent
personal fallback. #108 is actual missing-control RED after #107 fixture setup
repair; #109 main passes before adding two workflow boundaries. #110/#111 reveal
fixture windows-1252 decoding; only fixture UTF-8 response corrected for #112.
#113 final native browser main/all twelve observations, existing Context three
tests (no new Rstest cases), six-file format/target lint, early full tsc and full
pnpm check pass. Exact receipts/source hashes/empty owned resources recorded in
frontend_native_switcher in progress JSON.

This proves the actual control under opted-in native Context plus HTTP auth/scope
fixtures and navigation/env build doubles; actual WorkspaceContent/layout
bootstrap, compiled Next, real Gateway/JWT/SQL/NAS/principal/two-tab and physical
acceptance remain open. Next wire native shell then real backend main. Remaining
HTML/UI/global state and M4-M11 requirements are retained; all M0-M11 parent gates
remain unchecked, M3 partial and runtime activation false. No deployments, pushes,
model calls or local application/browser/Docker tests.


M3 native shell/bootstrap checkpoint (2026-10-16, #116 SUCCESS): WorkspaceContent
uses the server capability before mounting WorkspaceShell; unknown/unavailable
capability fails closed, explicit legacy disabled still works. One confirmed
lifetime QueryClient serves sidebar and page. Mount-only WorkspaceContentBoundary
keeps activity/delete owner/private sidebar/footer and page/extensions/commands/
settings/deep-link features out until confirmation, while Header/switcher remain
available. Account preference synchronizer is legacy-only pending scoped policy.
#114 records two actual pre-confirmation/unknown-capability legacy-mount REDs.
#115 main plus existing context/cache regressions pass before final checks.
#116 final eight tests (only two new cases), five-file format/target lint, early
full tsc and required full pnpm check pass. Retained native control/rich-report
browser main/all twelve observations pass; it does not exercise the new shell.
Exact terminal/source/archive/empty-resource evidence: frontend_native_shell in
progress JSON. Initial formatter-only RequestInfo stringification lint was
corrected in the fixture; no production behavior change from that correction.

Shell DOM proof uses actual root/native Sidebar/Header/Auth/Workspace/cache but
server cookies/capability/navigation and private feature leaves are doubles. It
is not compiled Next/hydration, real feature HTTP/JWT/SQL/NAS/backend business,
principal/two-tab or physical proof. Next handle workspace route/deep-link and
switch-from-private-thread semantics, then compiled Next and backend main.
Actual private clients/global settings/store/title/focus/live WSS, remaining HTML
and M4-M11 remain required. All parent gates unchecked; M3 partial, activation
false. No deployment, remote push, model calls or local application tests.
