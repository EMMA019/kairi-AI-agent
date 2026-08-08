# ブリーフィング試験運用チェックリスト

Kairi 寄り前（JST 08:15）/ 大引け後（JST 16:00）ブリーフの1週間試験運用用。

前提: Render 無料プランは既存 cron-job の定期 ping でスリープ回避済み。収集は内蔵 30 分 radar ループ。

## 毎朝（寄り前前）

- [ ] `GET /api/news/health` で `pool_total` / `pool_last_18h` が 0 でないこと
- [ ] `feeds_failing` が急増していないこと（連続失敗 3 回以上のフィード）
- [ ] Market Desk → Briefing タブで前日以降のファイルが一覧に出ること

## 寄り前（08:15 前後）

- [ ] `YYYY-MM-DD_preopen.md` が生成されている
- [ ] **米国市場確定値**テーブルに DIA/SPY/QQQ/SOXX/USDJPY が入っている（欠損は「取得失敗」）
- [ ] **今日のポイント**が 3〜5 行ある（LLM 失敗時は無くても可）
- [ ] ヘッドラインが最大 5 本、出典 URL がある
- [ ] 入力にない数値・日付・固有名詞が解説に混入していない
- [ ] Discord に全文が届いている（分割送信可）

## 大引け後（16:00 前後）

- [ ] `YYYY-MM-DD_postclose.md` が生成されている
- [ ] 日本市場スナップショットと **日経平均 前日比** がある
- [ ] 同上の解説・出典・Discord チェック

## 拾い漏れメモ（CXMT 級）

| 日付 | 漏れたニュース | あったべきフィード | 対応 |
| --- | --- | --- | --- |
|  |  |  |  |

## 週末レビュー

- [ ] `feeds_failing` の連続失敗フィードを見直し（URL 変更・廃止）
- [ ] 解説の grounding で潰せなかった誤りを eval / プロンプトに反映
- [ ] ペイウォール差し替えが効いていない記事を記録

## 手動再生成

Market Desk → Briefing → kind 選択 →「いま生成」、または:

```bash
curl -X POST -H "X-API-Token: $KAIRI_API_TOKEN" \
  "$KAIRI_BACKEND_URL/api/briefing/generate?kind=preopen"
```
