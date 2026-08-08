# Kairi — 検索つき市況／相棒チャット（BYOK）

> 公開向けの英語 README は [README.md](README.md) です。ライセンスは [MIT](LICENSE)。

<img width="1911" height="920" alt="image" src="https://github.com/user-attachments/assets/0bc17403-e1b7-4527-a1a2-c8bc0d50fcaf" />
<img width="1903" height="922" alt="image" src="https://github.com/user-attachments/assets/00d89b91-538b-415c-b443-c16fffafcd82" />


<div align="center">
  
![UI](https://img.shields.io/badge/UI-React_19_%2B_Tailwind_v4-blue)
![Backend](https://img.shields.io/badge/Backend-FastAPI_%2B_SQLite-green)
![Models](https://img.shields.io/badge/Models-DeepSeek_V4_%2F_GPT_%2F_Gemini-orange)
![Cache](https://img.shields.io/badge/Cache-SQLite_Semantic-purple)

**米国株・日本株の「今日どう？」を、検索と終値付きで日本語で答える相棒**

</div>

---

## 📋 概要

Kairi の本命は **個人向け・検索つき市況／相棒チャット（BYOK）** です。日付アンカーと検索 grounding で、市況のざっくり把握と個別銘柄の「なにかあった？」に答えます。

IDE 実装ループやレーダーは **上級モード（既定オフ）** の実験機能です。コーディング専用 CLI の二番煎じにはしません。

同梱 Python ビルド手順は `scripts/prepare_embedded_python.ps1`。`start_kairi.bat` で起動 → 初回 DeepSeek キー → 会話。

### 本命 / 実験 / 運用

| 区分 | 内容 |
|------|------|
| **本命** | 市況・ニュースの検索 grounding、セッション日付、**明示時のみ** KV 記憶、ブラウザ完結の相棒感 |
| **実験（上級）** | task IDE、char、radar / 定期ブリーフィング（`KAIRI_ENABLE_SCHEDULERS=1`） |
| **運用** | `KAIRI_API_TOKEN`、`python -m evals.run_evals`、デモゲート `tests/test_demo_sellable_gate.py` |

未知の事実への対策は「検索 → 出典強制 → 未ヒットなら埋めない」が基本です（RL再学習・複数モデル交差は対象外）。  
リポジトリ分割の詳細は [docs/REPO_SEPARATION.md](docs/REPO_SEPARATION.md) を参照。

---

## ✨ 主要機能

### 本命 — 市況チャット

| 機能 | 説明 |
|------|------|
| **市況 Q&A** | 「今日の米国市場どうだった？」に、セッション判定（場中/live・引け後/settled）と日付アンカーで正確に回答 |
| **個別銘柄フォロー** | 「Google なにかあった？」に、株価クォート＋検索 grounding で材料を回答 |
| **普通のチャット** | 雑談・ラボのメモは検索を走らせず、そのまま会話。市況と日常のメリハリを自動判定 |
| **検索 grounding＋出典** | 検索結果に出典リンクを明示し、ヒットしなければ「埋めない」。捏造禁止 |
| **ローカル保存** | 会話・設定はすべて SQLite（あなたのPC内）。APIキーは持ち込み（BYOK）|

### ブリーフィング / ニュースプール（オプション）

| 項目 | 内容 |
|------|------|
| **寄り前** | JST 08:15 — 米国確定値（DIA/SPY/QQQ/SOXX/USDJPY）＋解説＋ヘッドライン |
| **大引け後** | JST 16:00 — 日経/TOPIX スナップショット＋前日比＋解説＋ヘッドライン |
| **ニュースプール** | RSS 並列取得、72時間ローリング蓄積。ペイウォール記事は無料ソースで差し替え |
| **配信** | Discord Webhook へ全文分割送信（未設定時はログのみ） |

### 上級モード（既定オフ）

Settings → System → Advanced modes で有効化。IDE / Char / Radar / 定期ブリーフィングスケジューラ（`KAIRI_ENABLE_SCHEDULERS=1`）。

### マルチLLM対応

| プロバイダ | モデル例 | 用途 |
|-----------|---------|------|
| DeepSeek | V4 / Chat | デフォルト（高コスパ） |
| Anthropic | Claude | 高品質思考 |
| OpenAI | GPT-5 | 汎用 |
| Gemini | 3.1 | 高品質・低コスト |
| ローカル | Ollama | オフライン |

---

## 🚀 クイックスタート

### バックエンド

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

`.env` にAPIキーを設定（最低1つ）:
```
DEEPSEEK_API_KEY=sk-xxxxx
# または
ANTHROPIC_API_KEY=sk-xxxxx
# または
GEMINI_API_KEY=xxxxx
```

起動:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### フロントエンド

```bash
cd frontend
npm install
npm run dev
```

ブラウザで `http://localhost:5173` にアクセス。

---

## 🏗️ アーキテクチャ

```
User Input
    │
    ▼
┌──────────────────────┐
│  Search Planner       │  ← ルールベース判定（今日系/個別株/為替等は即検索）
│  + Search Trigger     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  LLM 呼び出し          │  ← DeepSeek/Claude/GPT/Gemini
│  （必要時のみ検索結果注入）│
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Fact Filter Pipeline │  ← 捏造防止 / 出典強制 / 文末トリミング
│  + Reply Language     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Response             │
│  (SSE Stream)        │
└──────────────────────┘
```

### キャッシュ戦略

- **検索結果キャッシュ**: 30分TTL（メモリ内）＋ 市況系は2日以内ルックバック
- **定型応答ショートサーキット**: 「おはよう」等はLLM呼び出しゼロ
- **KV メモリ**: 明示要求時のみ保存・参照（勝手読み出し禁止）

---

## 🗂️ ディレクトリ構成（主要部分）

```
backend/
├── app/
│   ├── main.py                     # FastAPI エントリーポイント（SPA静的配信含む）
│   ├── core/
│   │   ├── market_session.py       # 東証/米国 セッション判定（場中/引け後）
│   │   ├── market_calendar.py      # 祝日カレンダー
│   │   ├── chat_search.py          # チャット検索（日付アンカー/キャリーオーバー）
│   │   ├── search_planner.py       # 検索プランナー（今日系/個別株/為替 即検索）
│   │   ├── search_trigger.py       # 検索トリガー判定
│   │   ├── search/                # 検索プロバイダ統合
│   │   │   ├── router.py           # 天気/Wiki/Brave/Tavily/Jina/News ルーティング
│   │   │   ├── reranker.py         # キーワード+鮮度リランカー
│   │   │   └── providers/          # brave/tavily/jina/duckduckgo/news/weather/wiki
│   │   ├── fact_filters/           # 捏造防止パイプライン（出典/通貨/数値/日付）
│   │   ├── reply_language.py       # 言語（locale）判定
│   │   ├── news/                   # RSS プール・ペイウォール差し替え
│   │   ├── briefing/               # 寄り前/大引け後ブリーフィング生成
│   │   ├── notify/discord.py       # Discord Webhook（アラート＋全文配信）
│   │   ├── ibkr/                   # IBKR 口座連携（株価クォート）
│   │   ├── monitor/                # レーダー（無人市場監視・上級）
│   │   ├── cache_manager.py        # 検索結果キャッシュ
│   │   ├── llm_client.py           # マルチLLM統合ラッパー
│   │   ├── kv_store.py             # KVメモリ（明示要求時のみ）
│   │   └── memory.py               # 会話メモリ管理
│   ├── routers/
│   │   ├── chat.py                 # チャットAPI（SSEストリーミング）
│   │   ├── history.py              # 会話履歴API
│   │   ├── settings.py             # 設定API
│   │   ├── news_health.py          # ニュース健全性・ブリーフィング API
│   │   └── workspace.py            # ワークスペースAPI（上級）
│   └── models/
├── storage/                        # 会話履歴DB・briefings/
└── requirements.txt

frontend/
├── src/
│   ├── App.tsx                     # メインアプリケーション
│   ├── components/
│   │   ├── ChatArea.tsx            # 会話表示エリア
│   │   ├── InputArea.tsx           # 入力欄
│   │   ├── MarketDesk.tsx          # 市況デスク
│   │   ├── BriefingPanel.tsx       # ブリーフィング一覧・生成
│   │   └── SettingsModal.tsx       # 設定（APIキー/locale）
│   └── hooks/
│       ├── useChat.ts              # チャットAPI連携
│       └── useStreaming.ts         # SSEストリーミング受信
└── package.json
```

その他、上級モード（IDE/コード編集）用のモジュール（`supervisor` / `executor` / `auto_execution_loop` / `context_compressor` / `file_edit_fallback` / `sandbox` / `mcp` 等）は `backend/app/core/` 配下に存在しますが、**既定オフの実験機能**です。

---

## ⚙️ 設定

`.env` ファイルで設定可能:

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `DEEPSEEK_API_KEY` | DeepSeek APIキー | - |
| `ANTHROPIC_API_KEY` | Claude APIキー | - |
| `GEMINI_API_KEY` | Gemini APIキー | - |
| `OPENAI_API_KEY` | OpenAI APIキー | - |
| `BRAVE_API_KEY` | Brave Search APIキー（検索用） | - |
| `DISCORD_WEBHOOK_URL` | ブリーフィング/アラート Discord 配信 | - |
| `LLM_PROVIDER` | デフォルトLLM | `deepseek` |
| `KAIRI_API_TOKEN` | API 認証トークン（本番必須） | - |

---

## 📝 ライセンス

[MIT License](LICENSE)。

---

*Created by Kairi*
