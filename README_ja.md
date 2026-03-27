# 🦌 DeerFlow - 2.0

[English](./README.md) | [中文](./README_zh.md) | 日本語 | [Français](./README_fr.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> 2026年2月28日、バージョン2のリリースに伴い、DeerFlowはGitHub Trendingで🏆 第1位を獲得しました。素晴らしいコミュニティの皆さん、ありがとうございます！💪🔥

DeerFlow（**D**eep **E**xploration and **E**fficient **R**esearch **Flow**）は、**サブエージェント**、**メモリ**、**サンドボックス**を統合し、**拡張可能なスキル**によってあらゆるタスクを実行できるオープンソースの**スーパーエージェントハーネス**です。

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0はゼロからの完全な書き直しです。** v1とコードを共有していません。オリジナルのDeep Researchフレームワークをお探しの場合は、[`1.x`ブランチ](https://github.com/bytedance/deer-flow/tree/main-1.x)で引き続きメンテナンスされています。現在の開発は2.0に移行しています。

## 公式ウェブサイト

[<img width="2880" height="1600" alt="image" src="https://github.com/user-attachments/assets/a598c49f-3b2f-41ea-a052-05e21349188a" />](https://deerflow.tech)

**実際のデモ**は[**公式ウェブサイト**](https://deerflow.tech)でご覧いただけます。

## ByteDance Volcengine のコーディングプラン

<img width="4808" height="2400" alt="英文方舟" src="https://github.com/user-attachments/assets/2ecc7b9d-50be-4185-b1f7-5542d222fb2d" />

- DeerFlowの実行には、Doubao-Seed-2.0-Code、DeepSeek v3.2、Kimi 2.5の使用を強く推奨します
- [詳細はこちら](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陸の開発者はこちらをクリック](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlowは、BytePlusが独自に開発したインテリジェント検索・クローリングツールセット「[InfoQuest（無料オンライン体験対応）](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)」を新たに統合しました。

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## 目次

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [公式ウェブサイト](#公式ウェブサイト)
  - [InfoQuest](#infoquest)
  - [目次](#目次)
  - [Coding Agent に一文でセットアップを依頼](#coding-agent-に一文でセットアップを依頼)
  - [クイックスタート](#クイックスタート)
    - [設定](#設定)
    - [アプリケーションの実行](#アプリケーションの実行)
      - [オプション1: Docker（推奨）](#オプション1-docker推奨)
      - [オプション2: ローカル開発](#オプション2-ローカル開発)
    - [詳細設定](#詳細設定)
      - [サンドボックスモード](#サンドボックスモード)
      - [MCPサーバー](#mcpサーバー)
      - [IMチャネル](#imチャネル)
      - [LangSmithトレーシング](#langsmithトレーシング)
  - [Deep Researchからスーパーエージェントハーネスへ](#deep-researchからスーパーエージェントハーネスへ)
  - [コア機能](#コア機能)
    - [スキルとツール](#スキルとツール)
      - [Claude Code連携](#claude-code連携)
    - [サブエージェント](#サブエージェント)
    - [サンドボックスとファイルシステム](#サンドボックスとファイルシステム)
    - [コンテキストエンジニアリング](#コンテキストエンジニアリング)
    - [長期メモリ](#長期メモリ)
  - [推奨モデル](#推奨モデル)
  - [組み込みPythonクライアント](#組み込みpythonクライアント)
  - [ドキュメント](#ドキュメント)
  - [⚠️ セキュリティに関する注意](#️-セキュリティに関する注意)
  - [コントリビュート](#コントリビュート)
  - [ライセンス](#ライセンス)
  - [謝辞](#謝辞)
    - [主要コントリビューター](#主要コントリビューター)
  - [Star History](#star-history)

## Coding Agent に一文でセットアップを依頼

Claude Code、Codex、Cursor、Windsurf などの coding agent を使っているなら、次の一文をそのまま渡せます。

```text
DeerFlow がまだ clone されていなければ先に clone してから、https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md に従ってローカル開発環境を初期化してください
```

このプロンプトは coding agent 向けです。必要なら先にリポジトリを clone し、Docker が使える場合は Docker を優先して初期セットアップを行い、最後に次の起動コマンドと不足している設定項目だけを返します。

## クイックスタート

### 設定

1. **DeerFlowリポジトリをクローン**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **ローカル設定ファイルの生成**

   プロジェクトルートディレクトリ（`deer-flow/`）から以下を実行します：

   ```bash
   make config
   ```

   このコマンドは、提供されたテンプレートに基づいてローカル設定ファイルを作成します。

3. **使用するモデルの設定**

   `config.yaml`を編集し、少なくとも1つのモデルを定義します：

   ```yaml
   models:
     - name: gpt-4                       # 内部識別子
       display_name: GPT-4               # 表示名
       use: langchain_openai:ChatOpenAI  # LangChainクラスパス
       model: gpt-4                      # API用モデル識別子
       api_key: $OPENAI_API_KEY          # APIキー（推奨：環境変数を使用）
       max_tokens: 4096                  # リクエストあたりの最大トークン数
       temperature: 0.7                  # サンプリング温度

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENAI_API_KEY          # OpenRouterもここではOpenAI互換のフィールド名を使用
       base_url: https://openrouter.ai/api/v1
   ```

   OpenRouterやOpenAI互換のゲートウェイは、`langchain_openai:ChatOpenAI`と`base_url`で設定します。プロバイダー固有の環境変数名を使用したい場合は、`api_key`でその変数を明示的に指定してください（例：`api_key: $OPENROUTER_API_KEY`）。

4. **設定したモデルのAPIキーを設定**

   以下のいずれかの方法を選択してください：

- オプションA：プロジェクトルートの`.env`ファイルを編集（推奨）

   ```bash
   TAVILY_API_KEY=your-tavily-api-key
   OPENAI_API_KEY=your-openai-api-key
   # OpenRouterもlangchain_openai:ChatOpenAI + base_url使用時はOPENAI_API_KEYを使用します。
   # 必要に応じて他のプロバイダーキーを追加
   INFOQUEST_API_KEY=your-infoquest-api-key
   ```

- オプションB：シェルで環境変数をエクスポート

   ```bash
   export OPENAI_API_KEY=your-openai-api-key
   ```

- オプションC：`config.yaml`を直接編集（本番環境には非推奨）

   ```yaml
   models:
     - name: gpt-4
       api_key: your-actual-api-key-here  # プレースホルダーを置換
   ```

### アプリケーションの実行

#### オプション1: Docker（推奨）

**開発環境**（ホットリロード、ソースマウント）：

```bash
make docker-init    # サンドボックスイメージをプル（初回またはイメージ更新時のみ）
make docker-start   # サービスを開始（config.yamlからサンドボックスモードを自動検出）
```

`make docker-start`は、`config.yaml`がプロビジョナーモード（`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider`と`provisioner_url`）を使用している場合にのみ`provisioner`を起動します。

**本番環境**（ローカルでイメージをビルドし、ランタイム設定とデータをマウント）：

```bash
make up     # イメージをビルドして全本番サービスを開始
make down   # コンテナを停止して削除
```

> [!NOTE]
> LangGraphエージェントサーバーは現在`langgraph dev`（オープンソースCLIサーバー）経由で実行されます。

アクセス: http://localhost:2026

詳細なDocker開発ガイドは[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。

#### オプション2: ローカル開発

サービスをローカルで実行する場合：

前提条件：上記の「設定」手順を先に完了してください（`make config`とモデルAPIキー）。`make dev`には有効な設定ファイルが必要です（デフォルトはプロジェクトルートの`config.yaml`。`DEER_FLOW_CONFIG_PATH`で上書き可能）。

1. **前提条件の確認**：
   ```bash
   make check  # Node.js 22+、pnpm、uv、nginxを検証
   ```

2. **依存関係のインストール**：
   ```bash
   make install  # バックエンド＋フロントエンドの依存関係をインストール
   ```

3. **（オプション）サンドボックスイメージの事前プル**：
   ```bash
   # Docker/コンテナベースのサンドボックス使用時に推奨
   make setup-sandbox
   ```

4. **サービスの開始**：
   ```bash
   make dev
   ```

5. **アクセス**: http://localhost:2026

### 詳細設定
#### サンドボックスモード

DeerFlowは複数のサンドボックス実行モードをサポートしています：
- **ローカル実行**（ホストマシン上で直接サンドボックスコードを実行）
- **Docker実行**（分離されたDockerコンテナ内でサンドボックスコードを実行）
- **KubernetesによるDocker実行**（プロビジョナーサービス経由でKubernetesポッドでサンドボックスコードを実行）

Docker開発では、サービスの起動は`config.yaml`のサンドボックスモードに従います。ローカル/Dockerモードでは`provisioner`は起動されません。

お好みのモードの設定については[サンドボックス設定ガイド](backend/docs/CONFIGURATION.md#sandbox)をご覧ください。

#### MCPサーバー

DeerFlowは、機能を拡張するための設定可能なMCPサーバーとスキルをサポートしています。
HTTP/SSE MCPサーバーでは、OAuthトークンフロー（`client_credentials`、`refresh_token`）がサポートされています。
詳細な手順は[MCPサーバーガイド](backend/docs/MCP_SERVER.md)をご覧ください。

#### IMチャネル

DeerFlowはメッセージングアプリからのタスク受信をサポートしています。チャネルは設定時に自動的に開始されます。いずれもパブリックIPは不要です。

| チャネル | トランスポート | 難易度 |
|---------|-----------|------------|
| Telegram | Bot API（ロングポーリング） | 簡単 |
| Slack | Socket Mode | 中程度 |
| Feishu / Lark | WebSocket | 中程度 |

**`config.yaml`での設定：**

```yaml
channels:
  # LangGraphサーバーURL（デフォルト: http://localhost:2024）
  langgraph_url: http://localhost:2024
  # Gateway API URL（デフォルト: http://localhost:8001）
  gateway_url: http://localhost:8001

  # オプション: 全モバイルチャネルのグローバルセッションデフォルト
  session:
    assistant_id: lead_agent
    config:
      recursion_limit: 100
    context:
      thinking_enabled: true
      is_plan_mode: false
      subagent_enabled: false

  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-...（Socket Mode）
    allowed_users: []               # 空 = 全員許可

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    allowed_users: []               # 空 = 全員許可

    # オプション: チャネル/ユーザーごとのセッション設定
    session:
      assistant_id: mobile_agent
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip_agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true
```

対応するAPIキーを`.env`ファイルに設定します：

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret
```

**Telegramのセットアップ**

1. [@BotFather](https://t.me/BotFather)とチャットし、`/newbot`を送信してHTTP APIトークンをコピーします。
2. `.env`に`TELEGRAM_BOT_TOKEN`を設定し、`config.yaml`でチャネルを有効にします。

**Slackのセットアップ**

1. [api.slack.com/apps](https://api.slack.com/apps)でSlackアプリを作成 → 新規アプリ作成 → 最初から作成。
2. **OAuth & Permissions**で、Botトークンスコープを追加：`app_mentions:read`、`chat:write`、`im:history`、`im:read`、`im:write`、`files:write`。
3. **Socket Mode**を有効化 → `connections:write`スコープのApp-Levelトークン（`xapp-…`）を生成。
4. **Event Subscriptions**で、ボットイベントを購読：`app_mention`、`message.im`。
5. `.env`に`SLACK_BOT_TOKEN`と`SLACK_APP_TOKEN`を設定し、`config.yaml`でチャネルを有効にします。

**Feishu / Larkのセットアップ**

1. [Feishu Open Platform](https://open.feishu.cn/)でアプリを作成 → **ボット**機能を有効化。
2. 権限を追加：`im:message`、`im:message.p2p_msg:readonly`、`im:resource`。
3. **イベント**で`im.message.receive_v1`を購読し、**ロングコネクション**モードを選択。
4. App IDとApp Secretをコピー。`.env`に`FEISHU_APP_ID`と`FEISHU_APP_SECRET`を設定し、`config.yaml`でチャネルを有効にします。

**コマンド**

チャネル接続後、チャットから直接DeerFlowと対話できます：

| コマンド | 説明 |
|---------|-------------|
| `/new` | 新しい会話を開始 |
| `/status` | 現在のスレッド情報を表示 |
| `/models` | 利用可能なモデルを一覧表示 |
| `/memory` | メモリを表示 |
| `/help` | ヘルプを表示 |

> コマンドプレフィックスのないメッセージは通常のチャットとして扱われ、DeerFlowがスレッドを作成して会話形式で応答します。

#### LangSmithトレーシング

DeerFlowには[LangSmith](https://smith.langchain.com)による可観測性が組み込まれています。有効にすると、すべてのLLM呼び出し、エージェント実行、ツール実行がトレースされ、LangSmithダッシュボードで確認できます。

`.env`ファイルに以下を追加します：

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

Dockerデプロイでは、トレーシングはデフォルトで無効です。`.env`で`LANGSMITH_TRACING=true`と`LANGSMITH_API_KEY`を設定して有効にします。

## Deep Researchからスーパーエージェントハーネスへ

DeerFlowはDeep Researchフレームワークとして始まり、コミュニティがそれを大きく発展させました。リリース以来、開発者たちはリサーチを超えて活用してきました：データパイプラインの構築、スライドデッキの生成、ダッシュボードの立ち上げ、コンテンツワークフローの自動化。私たちが予想もしなかったことです。

これは重要なことを示していました：DeerFlowは単なるリサーチツールではなかったのです。それは**ハーネス**——エージェントが実際に仕事をこなすためのインフラを提供するランタイムでした。

そこで、ゼロから再構築しました。

DeerFlow 2.0は、もはやつなぎ合わせるフレームワークではありません。バッテリー同梱、完全に拡張可能なスーパーエージェントハーネスです。LangGraphとLangChainの上に構築され、エージェントが必要とするすべてを標準搭載しています：ファイルシステム、メモリ、スキル、サンドボックス実行、そして複雑なマルチステップタスクのためのプランニングとサブエージェントの生成機能。

そのまま使うもよし。分解して自分のものにするもよし。

## コア機能

### スキルとツール

スキルこそが、DeerFlowを*ほぼ何でもできる*ものにしています。

標準的なエージェントスキルは構造化された機能モジュールです——ワークフロー、ベストプラクティス、サポートリソースへの参照を定義するMarkdownファイルです。DeerFlowにはリサーチ、レポート生成、スライド作成、Webページ、画像・動画生成などの組み込みスキルが付属しています。しかし、真の力は拡張性にあります：独自のスキルを追加し、組み込みスキルを置き換え、複合ワークフローに組み合わせることができます。

スキルはプログレッシブに読み込まれます——タスクが必要とする時にのみ、一度にすべてではありません。これによりコンテキストウィンドウを軽量に保ち、トークンに敏感なモデルでもDeerFlowがうまく動作します。

Gateway経由で`.skill`アーカイブをインストールする際、DeerFlowは`version`、`author`、`compatibility`などの標準的なオプショナルフロントマターメタデータを受け入れ、有効な外部スキルを拒否しません。

ツールも同じ哲学に従います。DeerFlowにはコアツールセット——Web検索、Webフェッチ、ファイル操作、bash実行——が付属し、MCPサーバーやPython関数によるカスタムツールをサポートしています。何でも入れ替え可能、何でも追加可能です。

Gatewayが生成するフォローアップ提案は、プレーン文字列のモデル出力とブロック/リスト形式のリッチコンテンツの両方をJSON配列レスポンスの解析前に正規化するため、プロバイダー固有のコンテンツラッパーが提案をサイレントにドロップすることはありません。

```
# サンドボックスコンテナ内のパス
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← あなたのカスタムスキル
```

#### Claude Code連携

`claude-to-deerflow`スキルを使えば、[Claude Code](https://docs.anthropic.com/en/docs/claude-code)から直接、実行中のDeerFlowインスタンスと対話できます。リサーチタスクの送信、ステータスの確認、スレッドの管理——すべてターミナルから離れずに実行できます。

**スキルのインストール**：

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

DeerFlowが実行中であることを確認し（デフォルトは`http://localhost:2026`）、Claude Codeで`/claude-to-deerflow`コマンドを使用します。

**できること**：
- DeerFlowにメッセージを送信してストリーミングレスポンスを取得
- 実行モードの選択：flash（高速）、standard、pro（プランニング）、ultra（サブエージェント）
- DeerFlowのヘルスチェック、モデル/スキル/エージェントの一覧表示
- スレッドと会話履歴の管理
- 分析用ファイルのアップロード

**環境変数**（オプション、カスタムエンドポイント用）：

```bash
DEERFLOW_URL=http://localhost:2026            # 統合プロキシベースURL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

完全なAPIリファレンスは[`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md)をご覧ください。

### サブエージェント

複雑なタスクは単一のパスに収まりません。DeerFlowはそれを分解します。

リードエージェントはオンザフライでサブエージェントを生成できます——それぞれ独自のスコープ付きコンテキスト、ツール、終了条件を持ちます。サブエージェントは可能な限り並列で実行され、構造化された結果を報告し、リードエージェントがすべてを一貫した出力に統合します。

これがDeerFlowが数分から数時間かかるタスクを処理する方法です：リサーチタスクが十数のサブエージェントに展開され、それぞれが異なる角度を探索し、1つのレポート——またはWebサイト——または生成されたビジュアル付きのスライドデッキに収束します。1つのハーネス、多くの手。

### サンドボックスとファイルシステム

DeerFlowは物事を*語る*だけではありません。自分のコンピューターを持っています。

各タスクは、完全なファイルシステムを持つ分離されたDockerコンテナ内で実行されます——スキル、ワークスペース、アップロード、出力。エージェントはファイルの読み書き・編集を行います。bashコマンドを実行し、コーディングを行います。画像を表示します。すべてサンドボックス化され、すべて監査可能で、セッション間の汚染はゼロです。

これが、ツールアクセスのあるチャットボットと、実際の実行環境を持つエージェントの違いです。

```
# サンドボックスコンテナ内のパス
/mnt/user-data/
├── uploads/          ← あなたのファイル
├── workspace/        ← エージェントの作業ディレクトリ
└── outputs/          ← 最終成果物
```

### コンテキストエンジニアリング

**分離されたサブエージェントコンテキスト**：各サブエージェントは独自の分離されたコンテキストで実行されます。これにより、サブエージェントはメインエージェントや他のサブエージェントのコンテキストを見ることができません。これは、サブエージェントが目の前のタスクに集中し、メインエージェントや他のサブエージェントのコンテキストに気を取られないようにするために重要です。

**要約化**：セッション内で、DeerFlowはコンテキストを積極的に管理します——完了したサブタスクの要約、中間結果のファイルシステムへのオフロード、もはや直接関係のないものの圧縮。これにより、コンテキストウィンドウを超えることなく、長いマルチステップタスク全体を通じてシャープさを維持します。

### 長期メモリ

ほとんどのエージェントは、会話が終わるとすべてを忘れます。DeerFlowは記憶します。

セッションをまたいで、DeerFlowはあなたのプロフィール、好み、蓄積された知識の永続的なメモリを構築します。使えば使うほど、あなたのことをよく知るようになります——あなたの文体、技術スタック、繰り返されるワークフロー。メモリはローカルに保存され、あなたの管理下にあります。

メモリ更新は適用時に重複するファクトエントリをスキップするようになり、繰り返される好みやコンテキストがセッションをまたいで際限なく蓄積されることはありません。

## 推奨モデル

DeerFlowはモデルに依存しません——OpenAI互換APIを実装する任意のLLMで動作します。とはいえ、以下をサポートするモデルで最高のパフォーマンスを発揮します：

- **長いコンテキストウィンドウ**（10万トークン以上）：深いリサーチとマルチステップタスク向け
- **推論能力**：適応的なプランニングと複雑な分解向け
- **マルチモーダル入力**：画像理解と動画理解向け
- **強力なツール使用**：信頼性の高いファンクションコーリングと構造化された出力向け

## 組み込みPythonクライアント

DeerFlowは、完全なHTTPサービスを実行せずに組み込みPythonライブラリとして使用できます。`DeerFlowClient`は、すべてのエージェントとGateway機能へのプロセス内直接アクセスを提供し、HTTP Gateway APIと同じレスポンススキーマを返します：

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# チャット
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# ストリーミング（LangGraph SSEプロトコル：values、messages-tuple、end）
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])

# 設定＆管理 — Gateway準拠のdictを返す
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
```

すべてのdict返却メソッドはCIでGateway Pydanticレスポンスモデルに対して検証されており（`TestGatewayConformance`）、組み込みクライアントがHTTP APIスキーマと同期していることを保証します。完全なAPIドキュメントは`backend/packages/harness/deerflow/client.py`をご覧ください。

## ドキュメント

- [コントリビュートガイド](CONTRIBUTING.md) - 開発環境のセットアップとワークフロー
- [設定ガイド](backend/docs/CONFIGURATION.md) - セットアップと設定の手順
- [アーキテクチャ概要](backend/CLAUDE.md) - 技術的なアーキテクチャの詳細
- [バックエンドアーキテクチャ](backend/README.md) - バックエンドアーキテクチャとAPIリファレンス

## ⚠️ セキュリティに関する注意

### 不適切なデプロイはセキュリティリスクを引き起こす可能性があります

DeerFlowは**システムコマンドの実行、リソース操作、ビジネスロジックの呼び出し**などの重要な高権限機能を備えており、デフォルトでは**ローカルの信頼できる環境（127.0.0.1のループバックアクセスのみ）にデプロイされる設計**になっています。信頼できないLAN、公開クラウドサーバー、または複数のエンドポイントからアクセス可能なネットワーク環境にエージェントをデプロイし、厳格なセキュリティ対策を講じない場合、以下のようなセキュリティリスクが生じる可能性があります：

- **不正な違法呼び出し**：エージェントの機能が権限のない第三者や悪意のあるインターネットスキャナーに発見され、システムコマンドやファイル読み書きなどの高リスク操作を実行する不正な一括リクエストが引き起こされ、重大なセキュリティ上の問題が発生する可能性があります。
- **コンプライアンスおよび法的リスク**：エージェントがサイバー攻撃やデータ窃取などの違法行為に不正使用された場合、法的責任やコンプライアンス上のリスクが生じる可能性があります。

### セキュリティ推奨事項

**注意：DeerFlowはローカルの信頼できるネットワーク環境にデプロイすることを強く推奨します。** クロスデバイス・クロスネットワークのデプロイが必要な場合は、以下のような厳格なセキュリティ対策を実装する必要があります：

- **IPホワイトリストの設定**：`iptables`を使用するか、ハードウェアファイアウォール / ACL機能付きスイッチをデプロイして**IPホワイトリストルールを設定**し、他のすべてのIPアドレスからのアクセスを拒否します。
- **前置認証**：リバースプロキシ（nginxなど）を設定し、**強力な前置認証を有効化**して、認証なしのアクセスをブロックします。
- **ネットワーク分離**：可能であれば、エージェントと信頼できるデバイスを**同一の専用VLAN**に配置し、他のネットワークデバイスから隔離します。
- **アップデートを継続的に確認**：DeerFlowのセキュリティ機能のアップデートを継続的にフォローしてください。

## コントリビュート

コントリビューションを歓迎します！開発環境のセットアップ、ワークフロー、ガイドラインについては[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。

回帰テストのカバレッジには、`backend/tests/`でのDockerサンドボックスモード検出とプロビジョナーkubeconfig-pathハンドリングテストが含まれます。

## ライセンス

このプロジェクトはオープンソースであり、[MITライセンス](./LICENSE)の下で提供されています。

## 謝辞

DeerFlowはオープンソースコミュニティの素晴らしい成果の上に構築されています。DeerFlowを可能にしてくれたすべてのプロジェクトとコントリビューターに深く感謝いたします。まさに、巨人の肩の上に立っています。

以下のプロジェクトの貴重な貢献に心からの感謝を申し上げます：

- **[LangChain](https://github.com/langchain-ai/langchain)**：その優れたフレームワークがLLMのインタラクションとチェーンを支え、シームレスな統合と機能を実現しています。
- **[LangGraph](https://github.com/langchain-ai/langgraph)**：マルチエージェントオーケストレーションへの革新的なアプローチが、DeerFlowの洗練されたワークフローの実現に大きく貢献しています。

これらのプロジェクトはオープンソースコラボレーションの変革的な力を体現しており、その基盤の上に構築できることを誇りに思います。

### 主要コントリビューター

`DeerFlow`のコア著者に心からの感謝を捧げます。そのビジョン、情熱、献身がこのプロジェクトに命を吹き込みました：

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

揺るぎないコミットメントと専門知識が、DeerFlowの成功の原動力です。この旅の先頭に立ってくださっていることを光栄に思います。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
