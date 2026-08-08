# リポジトリ分離ガイド

チャット本体（Kairi）と同居していた別プロジェクトを段階的に分離するためのメモです。

## 対象ディレクトリ

| パス | 内容 | 方針 |
|------|------|------|
| `Github/` | 本体のミラーコピー | 既に gitignore。ローカル削除可 |
| `personal/` | 別バックエンド/フロント | gitignore 追加済み。別リポジトリへ移設推奨 |
| `gyaru_dash/` | 独立 Vite アプリ | gitignore 追加済み。別リポジトリへ移設推奨 |
| `scratch/` | 実験スクリプト | gitignore 追加済み |
| `tools/lora_studio/` | 画像生成ツールチェーン | 本体ランタイム非依存。必要なら別リポ |

## 移設手順（例: personal）

```bash
# 別場所に新リポジトリを作る
mkdir -p ../personal-trading && cd ../personal-trading
git init
# 元リポジトリからコピー（履歴不要なら）
cp -r ../chat/personal/* .
git add . && git commit -m "Initial import from chat/personal"
```

本体側では `personal/` を削除してもアプリ動作に影響しません（gitignore 済み）。

## 使い捨てスクリプト

`backend/patch_*.py` / `split_*.py` / `extract_prompt.py` / `read_db.py` は本体未参照のため削除済みです。
再追加しないよう `.gitignore` にパターンを入れています。
