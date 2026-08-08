# シークレットローテーション手順

コミット履歴に API キーが含まれていた可能性があります。**必ずプロバイダ側でキーを無効化し、再発行してください。**

## 対象

- DeepSeek API Key（`settings.json` / `test_deepseek.py` / git 履歴）
- その他 `backend/storage/settings.json` に保存していたキー類

## 手順

1. DeepSeek / Brave / Gemini 等のダッシュボードで旧キーを revoke
2. 新キーを `backend/.env` に設定（例: `DEEPSEEK_API_KEY=...`）
3. 必要ならアプリの Settings UI から再入力（`settings.json` は git 追跡外）
4. 履歴からの完全除去が必要な場合は `git filter-repo` 等を別途実施

## ローカル設定

- 実設定: `backend/storage/settings.json`（gitignore 済み）
- テンプレ: `backend/storage/settings.example.json`
- IBKR（閲覧専用）: 接続先のみ `.env`（`IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID`）。口座パスワードは TWS/Gateway 側。手順は `docs/IBKR_GATEWAY.md`
