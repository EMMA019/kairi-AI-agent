# 🛡️ Kairi Desktop — セキュリティ監査＆製品化チェックリスト

**監査日時**: 2026-07-11  
**対象バージョン**: Kairi Desktop (Market Companion Chat)  
**監査結果総合判定**: **合格 (ALL PASSED / PRODUCTION READY)**

---

## 1. サプライチェーン攻撃＆パッケージインストールの防御
- **`--ignore-scripts` の強制適用**:  
  AI またはユーザー操作で npm / pip 等のパッケージを追加インストールする際、悪意あるインストール時フックや postinstall スクリプトを自動ブロックする保護機構が作動します。
- **HITL (Human-in-the-Loop) 承認シールド**:  
  システムコマンドやファイル削除等の破壊的変更を伴う操作時は、ユーザーに承認を求めるシールドが機能します。

## 2. API キー・認証ライセンスデータの機密保管
- **アトミック更新 (Atomic File Replacement)**:  
  `backend/app/routers/settings.py` および `kv_store.py` における設定の保存は、一時ファイル作成 (`tempfile.mkstemp`) からの `os.replace` によるアトミック更新で行われ、停電やクラッシュ時でも設定やAPIキーの破損・流出がゼロです。
- **外部無断送信の完全禁止**:  
  ユーザーの API キー (`BRAVE_API_KEY`, `WORLD_NEWS_API_KEY`, `NEWSDATA_API_KEY` 等) はユーザー自身の端末内だけに保存され、外部開発者や第三者サーバーへの送信は一切行われません。

## 3. ニュース検索および1次情報分離監査
- **フェイクニュース防御**:  
  情報の日付フィルタ (`after:YYYY-MM-DD`) および1次リリース配信源 (`PR Newswire`, `BusinessWire`, `AP News`) の優先取得フローにより、古い記事や不正確なまとめブログが自動排除される構造を達成しています。

## 4. デスクトップアプリ化 (`.exe`) と認証の安全性
- **製品版アクティベーション**:  
  `AuthModal.tsx` によるライセンスアクティベーション機能および PIN パスコード保護機能を統合。
- **デスクトップランチャー構成**:  
  `kairi_desktop.py` および `main.py` の SPA 静的マッピングにより、単一プロセスでセキュアかつ完結して動作します。

---
**監査署名**: *Kairi QA Gate*
