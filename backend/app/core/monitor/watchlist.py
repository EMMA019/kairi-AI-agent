"""
Watchlist & Systematic Filter — 日英韓3ヶ国語対応辞書・加算式スコアリング・Entity-Slot名寄せエンジン

【機能】
1. 日英韓3ヶ国語対応・網羅的ターゲット＆カタリスト辞書（DAW30, S&P500, Nasdaq, SOX, 日経平均, KOSPI ＆ 中核50社超）
2. LLM API不使用の加算式重要度スコアリング (systematic_screen_and_score)
3. Entity-Slot 安全弁付き文字列類似度名寄せ判定 (systematic_deduplicate)
4. 棄却ニュースの保管 (rejected_news_log) および通知履歴管理
"""
import re
import json
import os
import difflib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set
import aiosqlite
from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "monitor.db")

# =====================================================================
# 1. 日英韓3ヶ国語対応・網羅的ターゲット辞書 (6大コア指数＆中核銘柄)
# =====================================================================
TARGET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "^DJI": {
        "name": "DOW 30 / ダウ平均",
        "category": "US_INDEX",
        "synonyms": [
            "dow jones", "dow 30", "dji", "djia", "ダウ平均", "ニューヨークダウ", "米ダウ",
            "다우 존스", "다우 30", "뉴욕 다우", "다우지수"
        ]
    },
    "^GSPC": {
        "name": "S&P 500",
        "category": "US_INDEX",
        "synonyms": [
            "s&p 500", "sp500", "s&p500", "standard & poor's", "gspc", "s&p 500指数",
            "s&p 500 지수", "에스앤피 500", "spx"
        ]
    },
    "^IXIC": {
        "name": "NASDAQ / ナスダック",
        "category": "US_INDEX",
        "synonyms": [
            "nasdaq", "ixic", "qqq", "tech sector", "ナスダック", "ナスダック総合", "ナスダック100",
            "나스닥", "나스닥 종합", "나스닥100", "나스닥 지수"
        ]
    },
    "^SOX": {
        "name": "SOX / フィラデルフィア半導体指数",
        "category": "SECTOR_CHIPS",
        "synonyms": [
            "sox", "soxl", "soxs", "soxx", "phlx semiconductor", "semiconductor sector", "chip stocks",
            "フィラデルフィア半導体", "半導体セクター", "半導体株", "半導体指数", "米半導体",
            "필라델피아 반도체", "반도체 지수", "반도체 섹터", "soxl", "반도체주"
        ]
    },
    "^N225": {
        "name": "Nikkei 225 / 日経平均",
        "category": "JP_INDEX",
        "synonyms": [
            "nikkei 225", "nikkei", "n225", "tse", "tokyo stock exchange", "topix",
            "日経平均", "日経225", "東京証券取引所", "東証", "日本株", "日経株価",
            "닛케이 225", "닛케이 지수", "도쿄증시", "일본증시", "토픽스"
        ]
    },
    "^KS11": {
        "name": "KOSPI / 韓国総合株価指数",
        "category": "KR_INDEX",
        "synonyms": [
            "kospi", "ks11", "korean stock market", "krx", "kosdaq",
            "韓国総合株価指数", "コスピ", "韓国株", "韓国市場",
            "코스피", "코스닥", "한국 증시", "코스피 지수", "국내증시"
        ]
    },
    "^SOXX": {
        "name": "iShares Semiconductor ETF / SOXX",
        "category": "SECTOR_CHIPS",
        "synonyms": [
            "soxx", "ishares semiconductor etf", "semiconductor etf", "米半導体etf", "soxx etf",
            "아이셰어즈 반도체 etf"
        ]
    },
    "^HDV": {
        "name": "iShares Core High Dividend ETF / HDV",
        "category": "US_DIVIDEND_ETF",
        "synonyms": [
            "hdv", "ishares core high dividend", "high dividend etf", "米国高配当株etf", "高配当etf",
            "고배당 etf", "hdv etf"
        ]
    },
    "^DGRO": {
        "name": "iShares Core Dividend Growth ETF / DGRO",
        "category": "US_DIVIDEND_ETF",
        "synonyms": [
            "dgro", "ishares core dividend growth", "dividend growth etf", "米国増配株etf", "増配株etf",
            "배당성장 etf", "dgro etf"
        ]
    },
    "^DIV_TOP_ETFS": {
        "name": "TOPT / VYM / SPYD (トップ配当・高配当ETF群)",
        "category": "US_DIVIDEND_ETF",
        "synonyms": [
            "topt", "vym", "spyd", "top dividend etf", "vanguard high dividend yield", "spdr portfolio s&p 500 high dividend",
            "米国高配当etf", "トップ配当etf", "spyd etf", "vym etf"
        ]
    }
}

# 個別中核銘柄・世界を左右する重要エンティティ辞書（Entity-Slot名寄せ＆所属指数マッピング用）
CORE_ENTITY_MAPPING: Dict[str, Dict[str, Any]] = {
    # --- 🌐 半導体・AI・メガテック・半導体製造装置 (US / TW / ASIA) ---
    "TSMC": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["tsmc", "taiwan semiconductor", "tsm", "2330.tw", "台湾積体電路製造", "대만 반도체", "티에스엠씨"]
    },
    "NVDA": {
        "targets": ["^SOX", "^SOXX", "^IXIC", "^GSPC"],
        "synonyms": ["nvda", "nvidia", "エヌビディア", "엔비디아"]
    },
    "ASML": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["asml", "asml holding", "エーエスエムエル", "아스믈"]
    },
    "SK_HYNIX": {
        "targets": ["^KS11", "^SOX", "^SOXX"],
        "synonyms": ["sk hynix", "hynix", "000660.ks", "sk Hynix", "skハイニックス", "ハイニックス", "sk하이닉스", "하이닉스"]
    },
    "SAMSUNG": {
        "targets": ["^KS11", "^SOX", "^SOXX"],
        "synonyms": ["samsung electronics", "samsung", "005930.ks", "サムスン電子", "サムスン", "삼성전자", "삼성"]
    },
    "KIOXIA": {
        "targets": ["^N225", "^SOX", "^SOXX"],
        "synonyms": ["kioxia", "toholt", "キオクシア", "キオクシアホールディングス", "키옥시아"]
    },
    "AVGO": {
        "targets": ["^SOX", "^SOXX", "^IXIC", "^GSPC", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["avgo", "broadcom", "ブロードコム", "브로드컴"]
    },
    "AMD": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["amd", "advanced micro devices", "アドバンスト・マイクロ・デバイセズ", "에이엠디"]
    },
    "QCOM": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["qcom", "qualcomm", "クアルコム", "퀄컴"]
    },
    "INTC": {
        "targets": ["^SOX", "^SOXX", "^IXIC", "^DJI"],
        "synonyms": ["intc", "intel", "intel corp", "インテル", "인텔"]
    },
    "MU": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["mu", "micron", "micron technology", "マイクロン", "マイクロン・テクノロジー", "마이크론"]
    },
    "ARM": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["arm holdings", "arm ltd", "アーム", "アーム・ホールディングス", "암 홀딩스"]
    },
    "SMCI": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["smci", "super micro computer", "supermicro", "スーパーマイクロ", "슈퍼마이크로"]
    },
    "TXN": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["txn", "texas instruments", "テキサス・インスツルメンツ", "テキサスインスツルメンツ", "텍사스 인스트루먼트"]
    },
    "AMAT": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["amat", "applied materials", "アプライド・マテリアルズ", "アプライドマテリアルズ", "어플라이드 머티어리얼즈"]
    },
    "LRCX": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["lrcx", "lam research", "ラムリサーチ", "램리서치"]
    },
    "KLAC": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["klac", "kla corp", "kla corporation", "kla corporation", "klaコーポレーション"]
    },
    "ADI": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["adi", "analog devices", "アナログ・デバイセズ", "アナログデバイセズ", "아날로그 디바이스"]
    },
    "MRVL": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["mrvl", "marvell", "marvell technology", "マーベル・テクノロジー", "マーベル", "마벨"]
    },
    "NXPI": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["nxpi", "nxp semiconductors", "nxp", "nxpセミコンダクターズ", "엔엑스피"]
    },
    "ON_SEMI": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["onsemi", "on semiconductor", "オンセミ", "オン・セミコンダクター", "온세미컨덕터"]
    },
    "MCHP": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["mchp", "microchip technology", "マイクロチップ・テクノロジー", "マイクロチップ", "마이크로칩"]
    },
    "MPWR": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["mpwr", "monolithic power systems", "モノリシック・パワー・システムズ"]
    },
    "ENTG": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["entg", "entegris", "インテグリス"]
    },
    "TER": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["teradyne", "ter", "テラダイン"]
    },
    "QRVO": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["qrvo", "qorvo", "コルボ"]
    },
    "SWKS": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["swks", "skyworks solutions", "skyworks", "スカイワークス"]
    },
    "WDC": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["wdc", "western digital", "ウェスタン・デジタル", "ウエスタン・デジタル", "웨스턴 디지털"]
    },
    "STX": {
        "targets": ["^SOX", "^SOXX", "^IXIC"],
        "synonyms": ["stx", "seagate", "seagate technology", "シーゲイト・テクノロジー", "シーゲイト", "씨게이트"]
    },
    "PLTR": {
        "targets": ["^IXIC", "^GSPC"],
        "synonyms": ["pltr", "palantir", "パランティア", "팔란티어"]
    },
    "ORCL": {
        "targets": ["^IXIC", "^GSPC"],
        "synonyms": ["orcl", "oracle", "オラクル", "오라클"]
    },

    # --- 🇺🇸 米国 MAG7・ビッグテック中核 (ダウ・S&P500・ナスダック全体牽引) ---
    "APPLE": {
        "targets": ["^IXIC", "^DJI", "^GSPC", "^DGRO"],
        "synonyms": ["aapl", "apple inc", "apple", "アップル", "애플"]
    },
    "MICROSOFT": {
        "targets": ["^IXIC", "^DJI", "^GSPC", "^DGRO"],
        "synonyms": ["msft", "microsoft", "マイクロソフト", "마이크로소프트"]
    },
    "AMZN": {
        "targets": ["^IXIC", "^DJI", "^GSPC"],
        "synonyms": ["amzn", "amazon", "amazon.com", "アマゾン", "아마존"]
    },
    "GOOGL": {
        "targets": ["^IXIC", "^GSPC"],
        "synonyms": ["googl", "goog", "alphabet", "google", "グーグル", "アルファベット", "구글", "알파벳"]
    },
    "META": {
        "targets": ["^IXIC", "^GSPC"],
        "synonyms": ["meta platforms", "meta", "facebook", "メタ", "フェイスブック", "메타", "페이스북"]
    },
    "TSLA": {
        "targets": ["^IXIC", "^GSPC"],
        "synonyms": ["tsla", "tesla", "テスラ", "테슬라"]
    },

    # --- 🇺🇸 米国 金融・銀行ショック震源 (システムリスク・信用不安) ---
    "JPM": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["jpm", "jpmorgan", "jpmorgan chase", "jpモルガン", "jpモルガン・チェース", "jp모건"]
    },
    "GS": {
        "targets": ["^DJI", "^GSPC"],
        "synonyms": ["gs", "goldman sachs", "ゴールドマン・サックス", "ゴールドマン", "골드만삭스"]
    },
    "MS_BANK": {
        "targets": ["^GSPC"],
        "synonyms": ["morgan stanley", "モルガン・スタンレー", "모건스탠리"]
    },
    "BAC": {
        "targets": ["^GSPC", "^HDV", "^DIV_TOP_ETFS"],
        "synonyms": ["bac", "bank of america", "bofa", "バンク・オブ・アメリカ", "뱅크오브아메리카"]
    },
    "BLK": {
        "targets": ["^GSPC", "^DGRO"],
        "synonyms": ["blk", "blackrock", "ブラックロック", "블랙록"]
    },

    # --- 🛢️ エネルギー・原油・貴金属 ＆ 🇺🇸 高配当・増配ETF中核構成銘柄 (HDV / DGRO / VYM / SPYD) ---
    "XOM": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["xom", "exxon mobil", "exxonmobil", "エクソンモービル", "엑슨모빌"]
    },
    "CVX": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["cvx", "chevron", "シェブロン", "쉐브론"]
    },
    "ABBV": {
        "targets": ["^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["abbv", "abbvie", "アッヴィ", "애브비"]
    },
    "VZ": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DIV_TOP_ETFS"],
        "synonyms": ["vz", "verizon", "verizon communications", "ベライゾン", "ベライゾン・コミュニケーションズ", "버라이즌"]
    },
    "PG": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["pg", "procter & gamble", "procter and gamble", "p&g", "プロクター・アンド・ギャンブル", "プロクター＆ギャンブル", "프록터 앤 갬블"]
    },
    "JNJ": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["jnj", "johnson & johnson", "johnson and johnson", "ジョンソン・エンド・ジョンソン", "ジョンソン＆ジョンソン", "존슨앤드존슨"]
    },
    "CAT": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["cat", "caterpillar", "caterpillar inc", "キャタピラー", "캐터필러"]
    },
    "PEP": {
        "targets": ["^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["pep", "pepsico", "ペプシコ", "펩시코"]
    },
    "KO": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["ko", "coca-cola", "coca cola", "コカ・コーラ", "コカコーラ", "코카콜라"]
    },
    "MRK": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["mrk", "merck", "merck & co", "メルク", "머크"]
    },
    "PFE": {
        "targets": ["^GSPC", "^HDV", "^DIV_TOP_ETFS"],
        "synonyms": ["pfe", "pfizer", "ファイザー", "화이자"]
    },
    "HD": {
        "targets": ["^DJI", "^GSPC", "^HDV", "^DGRO", "^DIV_TOP_ETFS"],
        "synonyms": ["hd", "home depot", "the home depot", "ホーム・デポ", "ホームデポ", "홈디포"]
    },
    "COMMODITY_OIL_GOLD": {
        "targets": ["^DJI", "^GSPC", "^N225"],
        "synonyms": ["crude oil", "wti crude", "brent crude", "gold price", "原油先物", "wti原油", "ブレント原油", "金先物", "金価格", "원유", "국제유가", "금값"]
    },

    # --- 🛡️ 防衛・重工・産業コア ---
    "BA": {
        "targets": ["^DJI", "^GSPC"],
        "synonyms": ["boeing", "ボーイング", "보잉"]
    },
    "LMT": {
        "targets": ["^GSPC"],
        "synonyms": ["lockheed martin", "ロッキード・マーティン", "록히드마틴"]
    },

    # --- 🇯🇵 日本株 日経平均＆TOPIX コア震源銘柄 (自動車・商社・半導体装置・銀行) ---
    "TEL": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["tokyo electron", "tel", "8035.t", "東京エレクトロン", "東エレク", "도쿄일렉트론"]
    },
    "ADVANTEST": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["advantest", "6857.t", "アドバンテスト", "어드반테스트"]
    },
    "DISCO": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["disco corp", "6146.t", "ディスコ", "디스코"]
    },
    "SCREEN": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["screen holdings", "7735.t", "screenホールディングス", "スクリーン", "스크린 홀딩스"]
    },
    "LASERTEC": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["lasertec", "6920.t", "レーザーテック", "레이저텍"]
    },
    "RENESAS": {
        "targets": ["^N225", "^SOX"],
        "synonyms": ["renesas", "6723.t", "ルネサス", "ルネサスエレクトロニクス", "르네사스"]
    },
    "TOYOTA": {
        "targets": ["^N225"],
        "synonyms": ["toyota", "toyota motor", "7203.t", "トヨタ自動車", "トヨタ", "토요타", "도요타"]
    },
    "SONY": {
        "targets": ["^N225"],
        "synonyms": ["sony", "sony group", "6758.t", "ソニーグループ", "ソニー", "소니"]
    },
    "SBG": {
        "targets": ["^N225", "^IXIC"],
        "synonyms": ["softbank group", "softbank", "sbg", "9984.t", "ソフトバンクグループ", "ソフバン", "소프트뱅크"]
    },
    "MUFG": {
        "targets": ["^N225"],
        "synonyms": ["mufg", "mitsubishi ufj", "8306.t", "三菱ufj", "三菱ufjフィナンシャル・グループ", "미쓰비시 ufj"]
    },
    "MITSUBISHI_CORP": {
        "targets": ["^N225"],
        "synonyms": ["mitsubishi corp", "8058.t", "三菱商事", "미쓰비시 상사"]
    },
    "FAST_RETAILING": {
        "targets": ["^N225"],
        "synonyms": ["fast retailing", "uniqlo", "9983.t", "ファーストリテイリング", "ユニクロ", "패스트리테일링", "유니클로"]
    },

    # --- 🇨🇳 アジア全体牽引 (中国・香港テック震源) ---
    "CHINA_TECH_CORE": {
        "targets": ["^N225", "^KS11", "^GSPC"],
        "synonyms": ["tencent", "alibaba", "baba", "byd", "テンセント", "アリババ", "比亜迪", "텐센트", "알리바바", "비야디"]
    },

    # --- 🏦 世界の中央銀行＆超マクロ機関 (2026年最新対応: ケビン・ウォーシュ米FRB議長) ---
    "MACRO_CENTRAL_BANKS": {
        "targets": ["^DJI", "^GSPC", "^IXIC", "^SOX", "^N225", "^KS11"],
        "synonyms": ["fomc", "federal reserve", "kevin warsh", "warsh", "boj", "bank of japan", "bank of korea", "ecb", "frb", "日銀", "日本銀行", "植田総裁", "ウォーシュ議長", "ケビン・ウォーシュ", "ウォーシュ", "米連邦準備理事会", "韓銀", "한국은행", "이창용", "케빈 워시", "워시 의장"]
    }
}

# =====================================================================
# 2. カタリスト爆弾ワード辞書 (英・日・韓 3ヶ国語対応)
# =====================================================================
CATALYST_KEYWORDS: Dict[str, Dict[str, Any]] = {
    "CIRCUIT_BREAKER_HALT": {
        "weight": 40,
        "label": "🚨 サーキットブレーカー/売買停止",
        "patterns": [
            r"circuit breaker", r"trading halt(ed)?", r"curb(s)? triggered",
            r"サーキットブレーカー", r"売買停止", r"取引一時停止", r"値幅制限",
            r"서킷브레이커", r"매매거래정지", r"사이드카", r"거래 중단"
        ]
    },
    "MARGIN_CALL_LIQUIDATION": {
        "weight": 35,
        "label": "💥 追証・強制ロスカット・連鎖決済",
        "patterns": [
            r"margin call(s)?", r"forced liquidation", r"leverage(d)? blowup", r"margin crunch",
            r"追証", r"強制決済", r"ロスカット連鎖", r"レバレッジ清算", r"信用買い残清算",
            r"마진콜", r"반대매매", r"강제청산", r"레버리지 청산", r"신용융자 청산"
        ]
    },
    "EXPORT_CONTROL_SANCTIONS": {
        "weight": 40,
        "label": "🚫 輸出規制・制裁・地政学制限",
        "patterns": [
            r"export control(s)?", r"export restriction(s)?", r"chip ban", r"trade ban", r"sanctions",
            r"輸出規制", r"半導体規制", r"禁輸", r"制裁措置", r"輸出制限",
            r"수출 규제", r"수출 통제", r"반도체 제재", r"제재 조치"
        ]
    },
    "GUIDANCE_EARNINGS_SHOCK": {
        "weight": 30,
        "label": "📉 決算ショック・見通し下方修正",
        "patterns": [
            r"guidance lowered", r"lower(ed)? guidance", r"unexpected miss", r"earnings miss(ed)?", r"profit warning", r"slashing forecast",
            r"見通し下方修正", r"業績予測引き下げ", r"想定外の下落", r"決算失望", r"下方修正", r"減益見通し",
            r"가이던스 하향", r"실적 전망 하향", r"어닝 쇼크", r"예상치 하회", r"전망치 하향"
        ]
    },
    "CENTRAL_BANK_MACRO": {
        # 銘柄なしでも高信頼ソースなら通知ライン(75)に届くよう 40
        "weight": 40,
        "label": "🏦 中銀金利決定・サプライズ政策",
        "patterns": [
            r"rate hike", r"rate cut", r"fomc surprise", r"boj decision", r"emergency cut",
            r"利上げ", r"利下げ", r"日銀会合", r"金利サプライズ", r"政策変更",
            r"금리 인상", r"금리 인하", r"금리 동결", r"한은 결정", r"통화정책"
        ]
    },
    "TARIFF_TRADE_WAR": {
        "weight": 40,
        "label": "⚔️ 関税・貿易摩擦・緊急関税",
        "patterns": [
            r"tariff(s)?", r"trade war", r"import duties", r"retaliatory tariff",
            r"関税", r"追加関税", r"貿易摩擦", r"報復関税",
            r"관세", r"추가 관세", r"무역전쟁", r"보복관세"
        ]
    },
    "RECORD_HIGH_MARKET_CAP": {
        "weight": 35,
        "label": "🚀 最高値/時価総額最高値更新・歴史的突破",
        "patterns": [
            # bare "ath" は path/rather 等に誤爆するため禁止。境界付きのみ。
            r"all-time high", r"record high", r"\bath\b", r"market cap record", r"historic high", r"surges to record",
            r"時価総額最高", r"時価総額過去最高", r"最高値更新", r"上場来高値", r"過去最高値", r"歴史的高値",
            r"사상 최고치", r"역대 최고치", r"시가총액 최고", r"최고가 경신"
        ]
    },
    "GUIDANCE_RAISED_BEAT": {
        "weight": 30,
        "label": "📈 決算好感・上方修正・サプライズ",
        "patterns": [
            r"guidance raised", r"raise(d)? guidance", r"earnings beat", r"record profit", r"profit surge", r"strong guidance",
            r"上方修正", r"最高益", r"業績予想引き上げ", r"決算好感", r"増益見通し", r"好決算", r"市場予想を上回る",
            r"어닝 서프라이즈", r"가이던스 상향", r"최대 실적", r"전망치 상향"
        ]
    }
}

async def init_monitor_db():
    """監視エンジンのデータベーステーブルおよびインデックスを初期化"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_guid TEXT,
                title TEXT,
                url TEXT,
                targets TEXT,
                entities TEXT,
                catalyst_type TEXT,
                importance INTEGER,
                alert_level TEXT,
                price_reaction TEXT,
                notified_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rejected_news_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT,
                title TEXT,
                url TEXT,
                source TEXT,
                raw_score INTEGER,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_title ON alert_history(title)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_notified_at ON alert_history(notified_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_rejected_log_created_at ON rejected_news_log(created_at)")
        await db.commit()
    logger.info("Radar DB initialized (alert_history, rejected_news_log).")

def _synonym_matches(text_lower: str, syn: str) -> bool:
    """
    短い英数字同義語は単語境界のみ。education→cat / earnings→gs / quarter→ter を防ぐ。
    日本語・韓国語や長いフレーズは部分一致のまま。
    """
    if not syn:
        return False
    s = syn.lower()
    # ASCII短語（ティッカー・略語）は境界必須
    if re.fullmatch(r"[a-z0-9$.^\-]{1,4}", s):
        # $TICKER / ^INDEX / 単独単語
        pat = rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])"
        return bool(re.search(pat, text_lower))
    return s in text_lower


def extract_matched_targets_and_entities(text_lower: str) -> Tuple[List[str], List[str]]:
    """テキストからマッチしたターゲット指数コードおよびエンティティを抽出"""
    matched_targets = set()
    matched_entities = set()

    # 1. ターゲット指数シノニムチェック
    for t_code, t_info in TARGET_DEFINITIONS.items():
        for syn in t_info["synonyms"]:
            if _synonym_matches(text_lower, syn):
                matched_targets.add(t_code)
                break

    # 2. 中核エンティティシノニムチェック＆指数逆引き
    for entity_id, e_info in CORE_ENTITY_MAPPING.items():
        for syn in e_info["synonyms"]:
            if _synonym_matches(text_lower, syn):
                matched_entities.add(entity_id)
                for t_code in e_info["targets"]:
                    matched_targets.add(t_code)
                break

    return list(matched_targets), list(matched_entities)

def systematic_screen_and_score(news_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM APIを一切使わず、日英韓3ヶ国語辞書と正規表現による加算式重要度スコアリングを行う。
    
    加算式: 基本点(20) + ターゲット一致(+30) + 爆弾ワード(+25〜40) + 1次情報ソース(+15) + 初動価格反応(+10)
    75点以上で Tier 3 (検証通過＆通知候補) となる。
    """
    title = (news_item.get("title") or "").strip()
    summary = (news_item.get("summary") or "").strip()
    source = (news_item.get("source") or "").strip()
    full_text = f"{title}\n{summary}"
    text_lower = full_text.lower()

    matched_targets, matched_entities = extract_matched_targets_and_entities(text_lower)

    # ターゲット・エンティティが全く含まれない一般ニュースは、スコア0として即時切り捨て対象
    if not matched_targets and not matched_entities:
        pass

    # 0. スパム・煽り・広告記事（Motley Fool等）の検知 (-100点)
    spam_keywords = [
        r"10 best stocks", r"motley fool", r"stock advisor", r"don't miss the latest",
        r"monster returns", r"if you invested \$", r"market-crushing", r"before you buy",
        r"buy right now\?", r"stocks to buy", r"top picks?", r"best stocks to",
        r"\btop \d+ stocks\b", r"should you buy", r"where to invest",
        r"10銘柄", r"テンバガー", r"爆上げ", r"無料メルマガ", r"今買うべき",
    ]
    if any(re.search(pat, full_text, re.IGNORECASE) for pat in spam_keywords):
        processed = dict(news_item)
        processed["importance"] = 0
        processed["matched_targets"] = matched_targets
        processed["matched_entities"] = matched_entities
        processed["detected_catalysts"] = ["🗑️ SPAM / 広告記事"]
        processed["detected_catalyst_ids"] = []
        processed["score_reasons"] = ["スパム・広告フィルターによる即時棄却(-100pt)"]
        return processed

    base_score = 20
    score = base_score
    reasons = []

    # 1. ターゲット＆エンティティ直接一致加点 (+30)
    if matched_targets or matched_entities:
        score += 30
        reasons.append(f"ターゲット一致: {', '.join(matched_targets + matched_entities)}")

    # 2. カタリスト爆弾ワード検出加点 (+25〜40)
    detected_catalysts = []
    detected_catalyst_ids: List[str] = []
    max_catalyst_weight = 0
    for c_id, c_info in CATALYST_KEYWORDS.items():
        for pat in c_info["patterns"]:
            if re.search(pat, full_text, re.IGNORECASE):
                detected_catalysts.append(c_info["label"])
                detected_catalyst_ids.append(c_id)
                if c_info["weight"] > max_catalyst_weight:
                    max_catalyst_weight = c_info["weight"]
                break

    if detected_catalysts:
        score += max_catalyst_weight
        reasons.append(f"カタリスト検出({max_catalyst_weight}pt): {', '.join(detected_catalysts)}")

    # 3. 1次情報・高信頼メディア加点 (+15)
    from app.core.source_evaluator import evaluate_source_authority
    eval_res = evaluate_source_authority(news_item.get("url", ""), title, source)
    source_l = source.lower()
    is_high_trust = (
        eval_res.get("tier") == 1
        or "prnewswire" in source_l
        or "businesswire" in source_l
        or "reuters" in source_l
        or "bloomberg" in source_l
    )
    if is_high_trust:
        score += 15
        reasons.append("1次・主要高信頼ソース(+15pt)")

    # 4. 先物やプレマーケット等の価格反応シグナル文言チェック (+10)
    price_reaction_keywords = [
        r"plunge(s|d)?", r"surge(s|d)?", r"sink(s|d)?", r"tumble(s|d)?", r"skyrocket",
        r"急落", r"急騰", r"暴落", r"急上昇", r"サーキットブレーカー", r"下落", r"上昇",
        r"급락", r"급등", r"폭락", r"폭등", r"하한가", r"상한가"
    ]
    if any(re.search(pat, full_text, re.IGNORECASE) for pat in price_reaction_keywords):
        score += 10
        reasons.append("価格反応・急変動文言検出(+10pt)")

    # ターゲット・エンティティも爆弾ワードもない場合は実質無効
    if not matched_targets and not detected_catalysts:
        score = min(score, 45)

    processed = dict(news_item)
    processed["importance"] = min(score, 100)
    processed["matched_targets"] = matched_targets
    processed["matched_entities"] = matched_entities
    processed["detected_catalysts"] = detected_catalysts
    processed["detected_catalyst_ids"] = detected_catalyst_ids
    processed["is_high_trust_source"] = is_high_trust
    processed["score_reasons"] = reasons
    return processed

async def systematic_deduplicate(news_item: Dict[str, Any], recent_alerts: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Entity-Slot (主語シンボル) 安全弁付きの文字列類似度名寄せ判定＆同一銘柄・同一ターゲット・同一カタリストの連発抑止。
    """
    title = (news_item.get("title") or "").strip()
    current_url = (news_item.get("url") or news_item.get("guid") or "").strip()
    current_entities = set(news_item.get("matched_entities", []))
    current_targets = set(news_item.get("matched_targets", []))
    current_catalysts = set(news_item.get("detected_catalysts", []))

    if not recent_alerts:
        return False, ""

    # 1. まず URL および タイトルの「完全一致」を直近150件全件に対して高速チェック
    for alert in recent_alerts[:150]:
        prev_url = (alert.get("url") or alert.get("news_guid") or "").strip()
        prev_title = (alert.get("title") or "").strip()
        if current_url and prev_url and current_url == prev_url:
            reason = f"完全一致抑止: 同一URL既読 ({current_url[:40]}...)"
            logger.info(f"🛑 [SystematicDeduplicate] {reason}")
            return True, reason
        if title and prev_title and title.lower() == prev_title.lower():
            reason = f"完全一致抑止: 同一タイトル既読「{prev_title[:35]}...」"
            logger.info(f"🛑 [SystematicDeduplicate] {reason}")
            return True, reason

    def tokenize(text: str) -> Set[str]:
        words = re.findall(r'[a-z0-9]+|[^\x00-\x7F]+', text.lower())
        return set(w for w in words if len(w) >= 2)

    current_tokens = tokenize(title)

    for idx, alert in enumerate(recent_alerts[:150]):
        prev_title = alert.get("title", "").strip()
        prev_entities_data = alert.get("matched_entities") or alert.get("entities") or []
        try:
            prev_entities = set(json.loads(prev_entities_data)) if isinstance(prev_entities_data, str) else set(prev_entities_data)
        except Exception:
            prev_entities = set()

        prev_targets_data = alert.get("matched_targets") or alert.get("targets") or []
        try:
            prev_targets = set(json.loads(prev_targets_data)) if isinstance(prev_targets_data, str) else set(prev_targets_data)
        except Exception:
            prev_targets = set()

        prev_catalysts_data = alert.get("detected_catalysts") or alert.get("catalyst_type") or []
        try:
            prev_catalysts = set(json.loads(prev_catalysts_data)) if isinstance(prev_catalysts_data, str) else set([prev_catalysts_data] if isinstance(prev_catalysts_data, str) and prev_catalysts_data else prev_catalysts_data)
        except Exception:
            prev_catalysts = set()

        # 🔴【連発・クールダウン抑止バリア】
        # 同一エンティティ(銘柄) または 同一ターゲット(指数・マクロ中銀等) かつ 同一カタリストのニュースが既に通知されている場合、連発(速報・一問一答等)を強力に抑止
        has_common_entity_or_target = bool(
            (current_entities and prev_entities and current_entities.intersection(prev_entities)) or
            (current_targets and prev_targets and current_targets.intersection(prev_targets))
        )
        if has_common_entity_or_target and current_catalysts and prev_catalysts and current_catalysts.intersection(prev_catalysts):
            common_tgt = current_entities.intersection(prev_entities) or current_targets.intersection(prev_targets)
            reason = f"クールダウン抑止: 直近アラート「{prev_title[:35]}...」と同一ターゲット({', '.join(common_tgt)})・同一カタリスト({', '.join(current_catalysts.intersection(prev_catalysts))})の連発抑止"
            logger.info(f"🛑 [SystematicDeduplicate] {reason}")
            return True, reason

        # Entity-Slot 安全弁チェック (異なる主語銘柄のニュースはテキストが似ていてもカットしない)
        if current_entities and prev_entities:
            if not current_entities.intersection(prev_entities):
                continue

        seq_sim = difflib.SequenceMatcher(None, title.lower(), prev_title.lower()).ratio()

        prev_tokens = tokenize(prev_title)
        if current_tokens and prev_tokens:
            jaccard_sim = len(current_tokens.intersection(prev_tokens)) / len(current_tokens.union(prev_tokens))
        else:
            jaccard_sim = 0.0

        # 同じ銘柄・ターゲット・トピックが共通している場合は類似度閾値を大きく引き下げてシリーズ報道(改題・速報・続報)をブロック
        seq_threshold = 0.42 if has_common_entity_or_target else 0.65
        jac_threshold = 0.35 if has_common_entity_or_target else 0.60

        if seq_sim >= seq_threshold or jaccard_sim >= jac_threshold:
            reason = f"重複抑止: 直近アラート「{prev_title[:35]}...」(SeqSim={seq_sim:.2f}, Jaccard={jaccard_sim:.2f}) と同一話題"
            logger.info(f"🛑 [SystematicDeduplicate] {reason}")
            return True, reason

    return False, ""

async def log_rejected_news(items: List[Dict[str, Any]]):
    """Tier 1で基準未達となったニュースを `rejected_news_log` に一定期間保存"""
    if not items:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for it in items:
            guid = it.get("guid") or it.get("url") or ""
            title = it.get("title", "")
            url = it.get("url", "")
            source = it.get("source", "")
            raw_score = it.get("importance", 0)
            reasons_str = ", ".join(it.get("score_reasons", []))
            await db.execute("""
                INSERT INTO rejected_news_log (guid, title, url, source, raw_score, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (guid, title, url, source, raw_score, reasons_str))
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute("DELETE FROM rejected_news_log WHERE created_at < ?", (seven_days_ago,))
        await db.commit()

async def save_alert_history(alert_item: Dict[str, Any]):
    """通知が完了したアラート履歴を保存"""
    async with aiosqlite.connect(DB_PATH) as db:
        targets_json = json.dumps(alert_item.get("matched_targets", []), ensure_ascii=False)
        entities_json = json.dumps(alert_item.get("matched_entities", []), ensure_ascii=False)
        catalyst_str = ", ".join(alert_item.get("detected_catalysts", []))
        await db.execute("""
            INSERT INTO alert_history (
                news_guid, title, url, targets, entities, catalyst_type, importance, alert_level, price_reaction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            alert_item.get("guid") or alert_item.get("url", ""),
            alert_item.get("title", ""),
            alert_item.get("url", ""),
            targets_json,
            entities_json,
            catalyst_str,
            alert_item.get("importance", 0),
            alert_item.get("alert_level", "CATALYST_EARLY_WARNING"),
            alert_item.get("price_reaction", "変動前/初動")
        ))
        await db.commit()

async def get_recent_alerts(hours: int = 48) -> List[Dict[str, Any]]:
    """直近指定時間以内のアラート履歴を取得（重複・連投防止のため最大150件取得）"""
    time_limit = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM alert_history WHERE notified_at >= ? ORDER BY notified_at DESC LIMIT 150", (time_limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
