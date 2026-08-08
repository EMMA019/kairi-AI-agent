# IBKR 閲覧専用（TWS / Gateway）セットアップ

Kairi は **読み取りのみ**（残高・ポジション・直近約定）。発注 API のコードパスはありません。

## 推奨構成（ライブ口座 + Yahoo 株価）

取引はライブ口座で続けつつ、**API 向けマーケットデータ課金はしない**のが既定方針。

| 用途 | 経路 |
|------|------|
| 株価・市況スナップショット | **Yahoo（yfinance）専属** |
| 口座サマリー / ポジション / 約定 | **TWS live :7496**（読み取り専用） |

```env
# ローカル推奨
IBKR_ENABLED=1
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=100
IBKR_MARKET_DATA=0
```

`IBKR_MARKET_DATA` 未設定時も株価 IBKR は **オフ**（Yahoo）。有料 API 購読後にリアルタイム株価を使う場合のみ `IBKR_MARKET_DATA=1`。

## ローカル vs Render（スマホ）

| 環境 | 想定 | 株価 |
|------|------|------|
| **ローカル** | PC + TWS 同居 | **Yahoo 既定**（口座ツールのみ IBKR） |
| **Render** | 外部スマホからチャット | **Yahoo 即時**。IBKR に繋がない |

Render では自宅 `127.0.0.1:7496` に届かない。不通待ちでスマホ応答が途切れるのを防ぐため、クラウドでは株価 IBKR オフ。

```env
# Render 推奨
IBKR_ENABLED=0
# または誤って IBKR_ENABLED=1 でも株価だけ切る
IBKR_MARKET_DATA=0
```

強制上書き（通常不要）: `KAIRI_CLOUD=1` / `KAIRI_CLOUD=0`

## 前提

1. Interactive Brokers **Live** または Paper 口座（ローカル用）
2. **TWS** または **IB Gateway** を起動し、API を有効化
3. Kairi backend が Gateway/TWS に TCP 接続できること（同一マシンなら `127.0.0.1`）

## ポート

| モード | TWS | IB Gateway |
|--------|-----|------------|
| Live（本番） | **7496**（Kairi デフォルト） | 4001 |
| Paper（デモ） | 7497 | 4002 |

Paper TWS なら `.env` で `IBKR_PORT=7497`。Gateway paper は `IBKR_PORT=4002`。

## TWS / Gateway 側

1. ログイン（Live / Paper）
2. **Edit → Global Configuration → API → Settings**
   - Enable ActiveX and Socket Clients
   - Socket port = 上記表に合わせる
   - Trusted IPs に `127.0.0.1`（必要なら）
   - 「Read-Only API」をオンにできる場合はオン推奨
3. ダイアログで API 接続をブロックしない
4. **同時に別のライブセッションで同じデータの独占利用をしない**（Error 10197）

## Kairi 側（ローカル `backend/.env`）

### 推奨（口座のみ IBKR / 株価 Yahoo）

```env
IBKR_ENABLED=1
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=100
IBKR_MARKET_DATA=0
```

| 変数 | 意味 |
|------|------|
| `IBKR_MARKET_DATA=0` | 株価は Yahoo のみ（課金・Error 10089 回避） |
| `IBKR_MARKET_DATA=1` | 株価を IBKR 優先（API 購読が必要） |
| `IBKR_MARKET_DATA_TYPE=1` | Live（リアルタイム）。`3` は Delayed（〜15分） |

- `IBKR_CLIENT_ID` はベース値。実際の接続 ID は `base + (pid % 10000)` でプロセスごとにずらす。
- 口座パスワードは Kairi に保存しない（TWS/Gateway ログインのみ）。

```bash
pip install ib_insync
```

### API リアルタイム株価を使う場合のみ（任意）

TWS UI の無料表示と API 購読は別ライセンス。US 銘柄で Error **10089** が出る場合:

1. IBKR Account Management → **Market Data Subscriptions**
2. US 株式の **Streaming（API）** パッケージ（Non-Pro でおおよそ月 $10 前後、手数料免除条件あり）
3. TWS 再ログイン後、`IBKR_MARKET_DATA=1` で backend 再起動

日本株（TSEJ）は別途 Tokyo Stock Exchange 系の購読が必要。

**今回の推奨構成では購読不要**（株価は Yahoo）。

## チャット / Desk ツール

| ツール | 用途 |
|--------|------|
| `ibkr_account_summary` | NetLiquidation / Cash / BuyingPower 等 |
| `ibkr_positions` | 保有銘柄・数量・平均取得 |
| `ibkr_recent_fills` | 直近約定（既定 20・最大 50） |
| `get_stock_quote` | 単銘柄（既定: Yahoo。`IBKR_MARKET_DATA=1` 時のみ IBKR 優先） |
| `get_stock_quotes` | **複数銘柄1接続**（Market Desk 用） |
| `get_jp_market_snapshot` | 日本指数・業種ETF（チャット注入は常に Yahoo） |

未接続時は `{"ok": false, "error": "gateway_unavailable", ...}`。数値の推測埋めは禁止。

## 株価取得の優先順位

1. **`IBKR_MARKET_DATA=0` または未設定** → yfinance
2. `IBKR_MARKET_DATA=1` + 購読あり → `source: ibkr`, `realtime: true`
3. 購読エラーは速失敗 → yfinance
4. Render / クラウド → 最初から yfinance
5. Market Desk ヘッダに `IBKR live` / `Yahoo ~15m` を表示

## 疎通チェック

1. TWS 起動・API 有効（ローカル）
2. `IBKR_ENABLED=1` / `IBKR_MARKET_DATA=0` / `IBKR_PORT=7496` で backend 再起動
3. チャットで「IBKRの残高は？」（口座ツール）
4. 株価は Yahoo（ヘッダ `Yahoo ~15m`）。Error 10089 は出ないこと
5. Render では IBKR connect が走らないこと

## やらないこと（意図的）

- 発注・取消・変更
- Client Portal Web API
- API マーケットデータ購読の強制
