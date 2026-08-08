---
name: python-backend
description: FastAPI, SQLite, aiosqlite, 非同期処理 (asyncio) および AIエージェント・ツール実行系モジュールの開発・デバッグ専門スキル。
keywords: ["python", "fastapi", "backend", "sqlite", "aiosqlite", "async", "router", "バックエンド", "サーバー", "データベース", "db", "api"]
---

# Python Backend & Agent Architecture Skill

このスキルがアクティブになった場合、以下のバックエンド開発ベストプラクティスを遵守してください。

## 1. 非同期とデータベース処理
- **aiosqlite の活用**: SQLiteへのアクセスは全て非同期 (`aiosqlite.connect`) で行い、イベントループのブロッキングを防ぐこと。
- **コネクションとトランザクション**: `async with` コンテキストマネージャを使用し、DBリソースのリークを確実に防ぐこと。

## 2. エラーハンドリングとロギング
- 例外を握りつぶさず、必ず `logger.error(f"Error: {e}", exc_info=True)` などでスタックトレースをログに残すこと。
- フロントエンドに返すエラーレスポンスは、ユーザーが直感的に理解できるクリーンな日本語メッセージにすること。

## 3. 自律検証
- Pythonコードの編集を行った際は、必ず `python -m py_compile <changed_file.py>` をバックグラウンドで実行し、構文エラーがないことを事前に自律検証すること。
