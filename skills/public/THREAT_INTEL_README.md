# Threat Intel Skills（threat-intel-collector / curator / analyst）

把字节系黑灰产情报系统封装成 deer-flow 的三个自定义 skill，按工作流阶段切分：

| skill | 职责 | 关键 action | 触碰 Telegram |
|---|---|---|---|
| **threat-intel-collector** | 采集+清洗+落库 | crawl / crawl-bot / crawl-twitter / discover / add-group | 是 |
| **threat-intel-curator** | 候选池治理 | stats / verify / llm-crawl | 是 |
| **threat-intel-analyst** | 分析研判+报告 | list-sources / trends / top-groups / top-entities / keyword-heat / query / report | 否（只读） |

每个 skill 是 deer-flow 标准结构：`SKILL.md`（frontmatter + Workflow）+ `scripts/`（argparse CLI）。

## 依赖的底层项目（不在本仓库内）

三个 skill 是底层 **`tg-intel-crawler`** 项目的薄封装，**底层项目不随 deer-flow 仓库一起分发**
（它含 `*.session` 登录凭证、`config.yaml` 真实 api_key、153M 爬取数据，均不应入库）。

### 部署步骤

1. 在部署机上准备底层项目并安装：

   ```bash
   git clone <tg-intel-crawler-repo>          # 或拷贝你的本地副本
   cd tg-intel-crawler
   pip install -e .
   pip install python-socks pysocks           # 代理依赖
   cp config/config.example.yaml config/config.yaml   # 填好凭证、首次登录生成 session
   ```

2. 让 skill 找到底层项目（**必需**）：

   ```bash
   export TG_INTEL_CRAWLER_HOME=/abs/path/to/tg-intel-crawler
   ```

   - collector/curator 的脚本据此调用 `tg-crawler` CLI；
   - analyst 据此定位 `output/intel.db`、`config/config.yaml`（LLM 配置）、`output/reports/`。

3. analyst 多数据源：编辑 `threat-intel-analyst/scripts/federation.yaml`
   （`path: AUTO` 即自动用 `$TG_INTEL_CRAWLER_HOME/output/intel.db`；队友的库按
   `threat-intel-analyst/SCHEMA_CONTRACT.md` 建好后加一行注册）。

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
