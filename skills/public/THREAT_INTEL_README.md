# Threat Intel Skills（threat-intel-collector / curator / analyst）

把字节系黑灰产情报系统封装成 deer-flow 的三个自定义 skill，按工作流阶段切分：

| skill | 职责 | 关键 action | 触碰 Telegram |
|---|---|---|---|
| **threat-intel-collector** | 采集+清洗+落库 | crawl / crawl-bot / crawl-twitter / discover / add-group | 是 |
| **threat-intel-curator** | 候选池治理 | stats / verify / llm-crawl | 是 |
| **threat-intel-analyst** | 分析研判+报告 | list-sources / trends / top-groups / top-entities / keyword-heat / query / report | 否（只读） |

每个 skill 是 deer-flow 标准结构：`SKILL.md`（frontmatter + Workflow）+ `scripts/`（argparse CLI）。

## 依赖的底层项目（已随本仓库一起分发）

三个 skill 是底层 **`tg-intel-crawler`** 项目的薄封装。**采集代码已集成进本仓库**
（仓库根目录的 `tg-intel-crawler/`），所以 agent 部署到任何环境都自带 Telegram/Twitter
采集能力，无需再单独获取代码。

**不进仓库的只有**（通过 `.gitignore` 排除，部署方各自提供/生成）：
- `tg-intel-crawler/config/config.yaml` — 真实凭证（api_id/api_hash/phone/api_key）
- `tg-intel-crawler/config/*.session` — Telegram 登录态
- `tg-intel-crawler/output/` — 运行数据（intel.db 等，部署后自己采集生成）
- `tg-intel-crawler/config/discovered_groups.yaml` — 候选池（采集时生成）

### 部署步骤（在 agent 运行环境上执行一次）

```bash
# 1. 安装采集项目（代码已在仓库内）
cd <repo-root>/tg-intel-crawler
pip install -e .
pip install python-socks pysocks            # 代理依赖

# 2. 配置凭证（仓库不含，需自己填）
cp config/config.example.yaml config/config.yaml
#   编辑 config.yaml 填 api_id/api_hash/phone/llm.api_key/(可选)代理

# 3. 让 skill 找到底层项目
export TG_INTEL_CRAWLER_HOME=<repo-root>/tg-intel-crawler

# 4. 首次登录（生成 *.session，之后免登录）
#    首次运行任一采集命令时按提示输入 Telegram 短信验证码
tg-crawler crawl --mode history --days 1 --joined-only
```

完成后，agent 调用 collector/curator skill 即可在该环境**自主采集** Telegram/Twitter 情报，
数据落到该环境的 `output/intel.db`，analyst skill 直接查询/分析。

> 说明：凭证（api_key/session）本就**不能硬编码进任何仓库**——这是安全底线，与"功能集成"
> 不冲突。功能（采集代码）已集成；凭证由每个部署环境各自提供一次，是所有涉及账号的系统的通用做法。


## 全链路示例

```bash
H=/abs/path/to/tg-intel-crawler; export TG_INTEL_CRAWLER_HOME=$H

# 采集
python threat-intel-collector/scripts/collect.py --action crawl --days 3 --joined-only
python threat-intel-collector/scripts/collect.py --action crawl-bot --keywords "抖音 买号"

# 治理
python threat-intel-curator/scripts/curate.py --action verify --max 80 --interval 3
python threat-intel-curator/scripts/curate.py --action llm-crawl --days 3 --min-confidence high --dry-run

# 分析
python threat-intel-analyst/scripts/analyze.py --action trends --day-from 2026-06-01
python threat-intel-analyst/scripts/analyze.py --action report --day-from 2026-06-01
```

## 安全

- **绝不**把底层项目的 `config/config.yaml`、`*.session`、`output/` 提交到任何仓库。
- collector/curator 触碰 Telegram，有 FloodWait/加群风险；analyst 全只读零风险。
- 仅用于安全研究与风险监控等合法用途。
