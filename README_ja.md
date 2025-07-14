# 🦌 DeerFlow

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[English](./README.md) | [简体中文](./README_zh.md) | [日本語](./README_ja.md) | [Deutsch](./README_de.md) | [Español](./README_es.md) | [Русский](./README_ru.md) | [Portuguese](./README_pt.md)

> オープンソースから生まれ、オープンソースに還元する。

**DeerFlow**（**D**eep **E**xploration and **E**fficient **R**esearch **Flow**）は、オープンソースコミュニティの素晴らしい成果の上に構築されたコミュニティ主導の深層研究フレームワークです。私たちの目標は、言語モデルとウェブ検索、クローリング、Python コード実行などの専門ツールを組み合わせながら、これを可能にしたコミュニティに貢献することです。

現在、DeerFlow は火山引擎の FaaS アプリケーションセンターに正式に入居しています。ユーザーは体験リンクを通じてオンラインで体験し、その強力な機能と便利な操作を直感的に感じることができます。同時に、さまざまなユーザーの展開ニーズを満たすため、DeerFlow は火山引擎に基づくワンクリック展開をサポートしています。展開リンクをクリックして展開プロセスを迅速に完了し、効率的な研究の旅を始めましょう。

詳細については[DeerFlow の公式ウェブサイト](https://deerflow.tech/)をご覧ください。

## デモ

### ビデオ

<https://github.com/user-attachments/assets/f3786598-1f2a-4d07-919e-8b99dfa1de3e>

このデモでは、DeerFlowの使用方法を紹介しています：

- MCPサービスとのシームレスな統合
- 深層研究プロセスの実施と画像を含む包括的なレポートの作成
- 生成されたレポートに基づくポッドキャストオーディオの作成

### リプレイ例

- [エッフェル塔は世界一高いビルと比べてどれくらい高い？](https://deerflow.tech/chat?replay=eiffel-tower-vs-tallest-building)
- [GitHub で最も人気のあるリポジトリは？](https://deerflow.tech/chat?replay=github-top-trending-repo)
- [南京の伝統料理に関する記事を書く](https://deerflow.tech/chat?replay=nanjing-traditional-dishes)
- [賃貸アパートの装飾方法は？](https://deerflow.tech/chat?replay=rental-apartment-decoration)
- [公式ウェブサイトでより多くのリプレイ例をご覧ください。](https://deerflow.tech/#case-studies)

---

## 📑 目次

- [🚀 クイックスタート](#クイックスタート)
- [🌟 特徴](#特徴)
- [🏗️ アーキテクチャ](#アーキテクチャ)
- [🛠️ 開発](#開発)
- [🗣️ テキスト読み上げ統合](#テキスト読み上げ統合)
- [📚 例](#例)
- [❓ よくある質問](#よくある質問)
- [📜 ライセンス](#ライセンス)
- [💖 謝辞](#謝辞)
- [⭐ スター履歴](#スター履歴)

## クイックスタート

DeerFlow は Python で開発され、Node.js で書かれた Web UI が付属しています。スムーズなセットアッププロセスを確保するために、以下のツールの使用をお勧めします：

### 推奨ツール

- **[`uv`](https://docs.astral.sh/uv/getting-started/installation/):**
  Python 環境と依存関係の管理を簡素化します。`uv`はルートディレクトリに自動的に仮想環境を作成し、必要なパッケージをすべてインストールします—Python 環境を手動でインストールする必要はありません。

- **[`nvm`](https://github.com/nvm-sh/nvm):**
  複数の Node.js ランタイムバージョンを簡単に管理します。

- **[`pnpm`](https://pnpm.io/installation):**
  Node.js プロジェクトの依存関係をインストールおよび管理します。

### 環境要件

システムが以下の最小要件を満たしていることを確認してください：

- **[Python](https://www.python.org/downloads/):** バージョン `3.12+`
- **[Node.js](https://nodejs.org/en/download/):** バージョン `22+`

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow

# 依存関係をインストール、uvがPythonインタープリタと仮想環境の作成、必要なパッケージのインストールを担当
uv sync

# APIキーで.envを設定
# Tavily: https://app.tavily.com/home
# Brave_SEARCH: https://brave.com/search/api/
# 火山引擎TTS: TTSの資格情報がある場合は追加
cp .env.example .env

# 下記の「サポートされている検索エンジン」と「テキスト読み上げ統合」セクションですべての利用可能なオプションを確認

# LLMモデルとAPIキーのconf.yamlを設定
# 詳細は「docs/configuration_guide.md」を参照
cp conf.yaml.example conf.yaml

# PPT生成用にmarpをインストール
# https://github.com/marp-team/marp-cli?tab=readme-ov-file#use-package-manager
brew install marp-cli
```

オプションで、[pnpm](https://pnpm.io/installation)を使用して Web UI 依存関係をインストール：

```bash
cd deer-flow/web
pnpm install
```

### 設定

詳細については[設定ガイド](docs/configuration_guide.md)を参照してください。

> [!注意]
> プロジェクトを開始する前に、ガイドを注意深く読み、特定の設定と要件に合わせて構成を更新してください。

### コンソール UI

プロジェクトを実行する最も迅速な方法は、コンソール UI を使用することです。

```bash
# bashライクなシェルでプロジェクトを実行
uv run main.py
```

### Web UI

このプロジェクトには Web UI も含まれており、より動的で魅力的なインタラクティブ体験を提供します。

> [!注意]
> 先に Web UI の依存関係をインストールする必要があります。

```bash
# 開発モードでバックエンドとフロントエンドサーバーの両方を実行
# macOS/Linuxの場合
./bootstrap.sh -d

# Windowsの場合
bootstrap.bat -d
```

ブラウザを開き、[`http://localhost:3000`](http://localhost:3000)にアクセスして Web UI を探索してください。

[`web`](./web/)ディレクトリで詳細を確認できます。

## サポートされている検索エンジン

DeerFlow は複数の検索エンジンをサポートしており、`.env`ファイルの`SEARCH_API`変数で設定できます：

- **Tavily**（デフォルト）：AI アプリケーション向けの専門検索 API
  - `.env`ファイルに`TAVILY_API_KEY`が必要
  - 登録先：<https://app.tavily.com/home>

- **DuckDuckGo**：プライバシー重視の検索エンジン
  - APIキー不要

- **Brave Search**：高度な機能を備えたプライバシー重視の検索エンジン
  - `.env`ファイルに`BRAVE_SEARCH_API_KEY`が必要
  - 登録先：<https://brave.com/search/api/>

- **Arxiv**：学術研究用の科学論文検索
  - APIキー不要
  - 科学・学術論文専用

お好みの検索エンジンを設定するには、`.env`ファイルで`SEARCH_API`変数を設定します：

```bash
# 選択肢: tavily, duckduckgo, brave_search, arxiv
SEARCH_API=tavily
```

## 特徴

### コア機能

- 🤖 **LLM統合**
  - [litellm](https://docs.litellm.ai/docs/providers)を通じてほとんどのモデルの統合をサポート
  - Qwenなどのオープンソースモデルをサポート
  - OpenAI互換のAPIインターフェース
  - 異なるタスクの複雑さに対応するマルチティアLLMシステム

### ツールと MCP 統合

- 🔍 **検索と取得**
  - Tavily、Brave Searchなどを通じたWeb検索
  - Jinaを使用したクローリング
  - 高度なコンテンツ抽出

- 🔗 **MCPシームレス統合**
  - プライベートドメインアクセス、ナレッジグラフ、Webブラウジングなどの機能を拡張
  - 多様な研究ツールと方法論の統合を促進

### 人間との協力

- 🧠 **人間参加型ループ**
  - 自然言語を使用した研究計画の対話的修正をサポート
  - 研究計画の自動承認をサポート

- 📝 **レポート後編集**
  - Notionライクなブロック編集をサポート
  - AI支援による洗練、文の短縮、拡張などのAI改良を可能に
  - [tiptap](https://tiptap.dev/)を活用

### コンテンツ作成

- 🎙️ **ポッドキャストとプレゼンテーション生成**
  - AI駆動のポッドキャストスクリプト生成と音声合成
  - シンプルなPowerPointプレゼンテーションの自動作成
  - カスタマイズ可能なテンプレートで個別のコンテンツに対応

## アーキテクチャ

DeerFlow は、自動研究とコード分析のためのモジュラーなマルチエージェントシステムアーキテクチャを実装しています。システムは LangGraph 上に構築され、コンポーネントが明確に定義されたメッセージパッシングシステムを通じて通信する柔軟な状態ベースのワークフローを実現しています。

![アーキテクチャ図](./assets/architecture.png)

> [deerflow.tech](https://deerflow.tech/#multi-agent-architecture)でライブで確認できます

システムは以下のコンポーネントを含む合理化されたワークフローを採用しています：

1. **コーディネーター**：ワークフローのライフサイクルを管理するエントリーポイント

   - ユーザー入力に基づいて研究プロセスを開始
   - 適切なタイミングでプランナーにタスクを委託
   - ユーザーとシステム間の主要なインターフェースとして機能

2. **プランナー**：タスク分解と計画のための戦略的コンポーネント

   - 研究目標を分析し、構造化された実行計画を作成
   - 十分なコンテキストが利用可能か、さらなる研究が必要かを判断
   - 研究フローを管理し、最終レポート生成のタイミングを決定

3. **研究チーム**：計画を実行する専門エージェントの集合：

   - **研究者**：Web 検索エンジン、クローリング、さらには MCP サービスなどのツールを使用して Web 検索と情報収集を行う。
   - **コーダー**：Python REPL ツールを使用してコード分析、実行、技術的タスクを処理する。
     各エージェントは自分の役割に最適化された特定のツールにアクセスでき、LangGraph フレームワーク内で動作する

4. **レポーター**：研究出力の最終段階プロセッサ
   - 研究チームの調査結果を集約
   - 収集した情報を処理および構造化
   - 包括的な研究レポートを生成

## テキスト読み上げ統合

DeerFlowには現在、研究レポートを音声に変換できるテキスト読み上げ（TTS）機能が含まれています。この機能は火山引擎TTS APIを使用して高品質なテキストオーディオを生成します。速度、音量、ピッチなどの特性もカスタマイズ可能です。

### TTS APIの使用

`/api/tts`エンドポイントからTTS機能にアクセスできます：

```bash
# curlを使用したAPI呼び出し例
curl --location 'http://localhost:8000/api/tts' \
--header 'Content-Type: application/json' \
--data '{
    "text": "これはテキスト読み上げ機能のテストです。",
    "speed_ratio": 1.0,
    "volume_ratio": 1.0,
    "pitch_ratio": 1.0
}' \
--output speech.mp3
```

## 開発

### テスト

テストスイートの実行：

```bash
# すべてのテストを実行
make test

# 特定のテストファイルを実行
pytest tests/integration/test_workflow.py

# カバレッジテストを実行
make coverage
```

### コード品質

```bash
# コードチェックを実行
make lint

# コードをフォーマット
make format
```

### LangGraph Studio によるデバッグ

DeerFlow はワークフローアーキテクチャとして LangGraph を使用しています。LangGraph Studio を使用してワークフローをリアルタイムでデバッグおよび可視化できます。

#### ローカルで LangGraph Studio を実行

DeerFlow には`langgraph.json`設定ファイルが含まれており、これが LangGraph Studio のグラフ構造と依存関係を定義しています。このファイルはプロジェクトで定義されたワークフローグラフを指し、`.env`ファイルから環境変数を自動的に読み込みます。

##### Mac

```bash
# uvパッケージマネージャがない場合はインストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存関係をインストールしLangGraphサーバーを開始
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.12 langgraph dev --allow-blocking
```

##### Windows / Linux

```bash
# 依存関係をインストール
pip install -e .
pip install -U "langgraph-cli[inmem]"

# LangGraphサーバーを開始
langgraph dev
```

LangGraphサーバーを開始すると、端末にいくつかのURLが表示されます：

- API: <http://127.0.0.1:2024>
- Studio UI: <https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024>
- APIドキュメント: <http://127.0.0.1:2024/docs>

- API: <http://127.0.0.1:2024>
- Studio UI: <https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024>
- APIドキュメント: <http://127.0.0.1:2024/docs>

ブラウザで Studio UI リンクを開いてデバッグインターフェースにアクセスします。

#### LangGraph Studio の使用

Studio UI では、次のことができます：

1. ワークフローグラフを可視化し、コンポーネントの接続方法を確認
2. 実行をリアルタイムで追跡し、データがシステム内をどのように流れるかを理解
3. ワークフローの各ステップの状態を検査
4. 各コンポーネントの入力と出力を検査して問題をデバッグ
5. 計画段階でフィードバックを提供して研究計画を洗練

Studio UIで研究トピックを送信すると、次を含む全ワークフロー実行プロセスを見ることができます：

- 研究計画を作成する計画段階
- 計画を修正できるフィードバックループ
- 各セクションの研究と執筆段階
- 最終レポート生成

### LangSmith トレースの有効化

DeerFlow は LangSmith トレース機能をサポートしており、ワークフローのデバッグとモニタリングに役立ちます。LangSmith トレースを有効にするには：

1. `.env` ファイルに次の設定があることを確認してください（`.env.example` を参照）：

   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
   LANGSMITH_API_KEY="xxx"
   LANGSMITH_PROJECT="xxx"
   ```

2. 次のコマンドを実行して LangSmith トレースを開始します：

   ```bash
   langgraph dev
   ```

これにより、LangGraph Studio でトレース可視化が有効になり、トレースがモニタリングと分析のために LangSmith に送信されます。

## Docker

このプロジェクトは Docker でも実行できます。

まず、以下の[設定](#設定)セクションを読んでください。`.env`と`.conf.yaml`ファイルが準備できていることを確認してください。

次に、独自の Web サーバーの Docker イメージをビルドします：

```bash
docker build -t deer-flow-api .
```

最後に、Web サーバーを実行する Docker コンテナを起動します：

```bash
# deer-flow-api-appを希望のコンテナ名に置き換えてください
docker run -d -t -p 8000:8000 --env-file .env --name deer-flow-api-app deer-flow-api

# サーバーを停止
docker stop deer-flow-api-app
```

### Docker Compose

このプロジェクトは docker compose でも設定できます：

```bash
# dockerイメージをビルド
docker compose build

# サーバーを起動
docker compose up
```

## テキスト読み上げ統合

DeerFlow には現在、研究レポートを音声に変換できるテキスト読み上げ（TTS）機能が含まれています。この機能は火山引擎 TTS API を使用して高品質なテキストオーディオを生成します。速度、音量、ピッチなどの特性もカスタマイズ可能です。

### TTS API の使用

`/api/tts`エンドポイントから TTS 機能にアクセスできます：

```bash
# curlを使用したAPI呼び出し例
curl --location 'http://localhost:8000/api/tts' \
--header 'Content-Type: application/json' \
--data '{
    "text": "これはテキスト読み上げ機能のテストです。",
    "speed_ratio": 1.0,
    "volume_ratio": 1.0,
    "pitch_ratio": 1.0
}' \
--output speech.mp3
```

## 例

以下の例は DeerFlow の機能を示しています：

### 研究レポート

1. **OpenAI Sora レポート** - OpenAI の Sora AI ツールの分析

   - 機能、アクセス方法、プロンプトエンジニアリング、制限、倫理的考慮について議論
   - [完全なレポートを見る](examples/openai_sora_report.md)

2. **Google の Agent to Agent プロトコルレポート** - Google の Agent to Agent（A2A）プロトコルの概要

   - AI エージェント通信における役割と、Anthropic の Model Context Protocol（MCP）との関係について議論
   - [完全なレポートを見る](examples/what_is_agent_to_agent_protocol.md)

3. **MCP とは何か？** - 複数のコンテキストにおける「MCP」という用語の包括的分析

   - AI における Model Context Protocol、化学における Monocalcium Phosphate、電子工学における Micro-channel Plate を探る
   - [完全なレポートを見る](examples/what_is_mcp.md)

4. **ビットコイン価格変動** - 最近のビットコイン価格動向の分析

   - 市場動向、規制の影響、テクニカル指標の調査
   - 歴史的データに基づく提言
   - [完全なレポートを見る](examples/bitcoin_price_fluctuation.md)

5. **LLM とは何か？** - 大規模言語モデルの詳細な探求

   - アーキテクチャ、トレーニング、応用、倫理的考慮について議論
   - [完全なレポートを見る](examples/what_is_llm.md)

6. **Claude を使った深層研究の方法は？** - 深層研究での Claude の使用に関するベストプラクティスとワークフロー

   - プロンプトエンジニアリング、データ分析、他のツールとの統合
   - [完全なレポートを見る](examples/how_to_use_claude_deep_research.md)

7. **医療における AI 採用：影響要因** - 医療における AI 採用に影響する要因の分析

   - AI テクノロジー、データ品質、倫理的考慮、経済的評価、組織の準備状況、デジタルインフラについて議論
   - [完全なレポートを見る](examples/AI_adoption_in_healthcare.md)

8. **量子コンピューティングの暗号学への影響** - 量子コンピューティングの暗号学への影響の分析

   - 古典的暗号の脆弱性、ポスト量子暗号学、耐量子暗号ソリューションについて議論
   - [完全なレポートを見る](examples/Quantum_Computing_Impact_on_Cryptography.md)

9. **クリスティアーノ・ロナウドのパフォーマンスハイライト** - クリスティアーノ・ロナウドのパフォーマンスハイライトの分析
   - 彼のキャリア達成、国際ゴール、さまざまな大会でのパフォーマンスについて議論
   - [完全なレポートを見る](examples/Cristiano_Ronaldo's_Performance_Highlights.md)

これらの例を実行したり、独自の研究レポートを作成したりするには、次のコマンドを使用できます：

```bash
# 特定のクエリで実行
uv run main.py "医療におけるAI採用に影響する要因は何か？"

# カスタム計画パラメータで実行
uv run main.py --max_plan_iterations 3 "量子コンピューティングは暗号学にどのように影響するか？"

# 組み込み質問を使用したインタラクティブモードで実行
uv run main.py --interactive

# または基本的なインタラクティブプロンプトで実行
uv run main.py

# 利用可能なすべてのオプションを表示
uv run main.py --help
```

### インタラクティブモード

アプリケーションは現在、英語と中国語の組み込み質問を使用したインタラクティブモードをサポートしています：

1. インタラクティブモードを開始：

   ```bash
   uv run main.py --interactive
   ```

2. 好みの言語（English または Chinese）を選択

3. 組み込み質問リストから選択するか、独自の質問を提示するオプションを選択

4. システムが質問を処理し、包括的な研究レポートを生成

### 人間参加型ループ

DeerFlow には人間参加型ループメカニズムが含まれており、研究計画を実行する前にレビュー、編集、承認することができます：

1. **計画レビュー**：人間参加型ループが有効な場合、システムは実行前に生成された研究計画を表示

2. **フィードバック提供**：次のことができます：

   - `[ACCEPTED]`と返信して計画を承認
   - フィードバックを提供して計画を編集（例：`[EDIT PLAN] 技術実装に関するステップをさらに追加する`）
   - システムはフィードバックを統合し、修正された計画を生成

3. **自動承認**：レビュープロセスをスキップするために自動承認を有効にできます：

4. **API統合**：APIを使用する場合、`feedback`パラメータでフィードバックを提供できます：

   ```json
   {
     "messages": [
       { "role": "user", "content": "量子コンピューティングとは何ですか？" }
     ],
     "thread_id": "my_thread_id",
     "auto_accepted_plan": false,
     "feedback": "[EDIT PLAN] 量子アルゴリズムについてもっと含める"
   }
   ```

### コマンドライン引数

アプリケーションは動作をカスタマイズするための複数のコマンドライン引数をサポートしています：

- **query**：処理する研究クエリ（複数の単語でも可）
- **--interactive**：組み込み質問を使用したインタラクティブモードで実行
- **--max_plan_iterations**：最大計画サイクル数（デフォルト：1）
- **--max_step_num**：研究計画の最大ステップ数（デフォルト：3）
- **--debug**：詳細なデバッグログを有効化

## よくある質問

詳細については[FAQ.md](docs/FAQ.md)を参照してください。

## ライセンス

このプロジェクトはオープンソースであり、[MIT ライセンス](./LICENSE)に従っています。

## 謝辞

DeerFlow はオープンソースコミュニティの素晴らしい成果の上に構築されています。DeerFlow を可能にしたすべてのプロジェクトと貢献者に深く感謝します。私たちは確かに巨人の肩の上に立っています。

以下のプロジェクトに心からの感謝を表します：

- **[LangChain](https://github.com/langchain-ai/langchain)**：彼らの優れたフレームワークは、シームレスな統合と機能性を実現する LLM 相互作用とチェーンに力を与えています。
- **[LangGraph](https://github.com/langchain-ai/langgraph)**：マルチエージェントオーケストレーションへの革新的アプローチは、DeerFlow の複雑なワークフローの実現に不可欠でした。

これらのプロジェクトはオープンソースコラボレーションの変革力を示しており、その基盤の上に構築できることを誇りに思います。

### 主要貢献者

`DeerFlow`の主要な作者に心から感謝します。彼らのビジョン、情熱、献身がこのプロジェクトを実現しました：

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

あなたの揺るぎない取り組みと専門知識が DeerFlow の成功を推進しています。この旅をリードしていただき光栄です。

## スター履歴

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
