"""
ソース権威性・信頼性評価モジュール (Source Evaluator & Entity-Claim Attribution)

機能:
1. ドメイン権威性チェック (.edu偽装検知、企業公式/一次情報かSEO記事サイトかの判定)
2. 一次/二次/三次情報の Tier 分類を株式・金融以外の全トピック（文化・テック・トレンド等）へ横展開
3. 複数主体が混在する記事における主語・述語の正確な紐付け検証 (Entity-Claim Attribution)
"""
import re
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 偽装学術・公的ドメイン (例: .edu.pl, .edu.cn, .edu.vn 等のセカンドレベルにeduが入る非米国教育機関TLD等)
SPOOFED_EDU_TLDS = [
    ".edu.pl", ".edu.cn", ".edu.vn", ".edu.bd", ".edu.in",
    ".edu.pk", ".edu.np", ".edu.eg", ".edu.co",
]

# 一次情報・公的/学術/主要研究機関のドメイン・キーワード (Tier 1)
TIER1_DOMAINS = [
    ".gov", ".go.jp", ".ac.jp", ".org",
    "harvard.edu", "stanford.edu", "mit.edu", "ox.ac.uk", "cam.ac.uk",
    "nature.com", "science.org", "ieee.org", "arxiv.org", "biorxiv.org",
    "who.int", "imf.org", "worldbank.org", "oecd.org",
]

# 二次情報・主要メディア/信頼できる専門調査機関 (Tier 2)
TIER2_DOMAINS = [
    "reuters.com", "bloomberg.com", "nikkei.com", "wsj.com", "ft.com",
    "bbc.com", "bbc.co.uk", "cnn.com", "forbes.com", "economist.com",
    "gartner.com", "euromonitor.com", "statista.com", "idc.com",
    "businesswire.com", "prnewswire.com", "webershandwick.com",
]

# 既知のSEOまとめ・一般キュレーション・三次情報ブログサイト (Tier 3 定義・パターン)
SEO_SUMMARY_KEYWORDS = [
    "culturepulse", "anarchydaily", "hot1009", "matome", "blog",
    "まとめ", "速報", "ブログ", "キュレーション", "おすすめ",
]

# 絶対に1次情報として扱ってはいけないUGC・個人投稿プラットフォーム (Tier 4)
UGC_BANNED_DOMAINS = [
    "note.com", "qiita.com", "zenn.dev", "medium.com", "ameblo.jp", 
    "togetter.com", "hatenablog.com", "chiebukuro.yahoo.co.jp", "5ch.net"
]


def evaluate_source_authority(url: str, title: str = "", source_label: str = "") -> Dict[str, Any]:
    """
    URLおよびタイトルからソースの信頼度 Tier (1〜3) および偽装判定を行う。
    金融・株式以外の全ジャンル（トレンド・テック等）にも横展開適用する。

    Returns:
        {
            "tier": int (1: 一次情報/公的・学術, 2: 信頼できる主要メディア/調査機関, 3: 三次情報/SEO・ブログ),
            "label": str (説明ラベル),
            "is_spoofed": bool (ドメイン偽装の有無),
            "domain": str
        }
    """
    if not url:
        # URLなしの場合は source_label から推測
        upper_label = (source_label or "").upper()
        if "PRIMARY" in upper_label or "OFFICIAL" in upper_label:
            return {
                "tier": 1,
                "label": "一次情報 (公式/直接配信)",
                "is_spoofed": False,
                "domain": source_label,
            }
        return {
            "tier": 3,
            "label": "三次情報 (情報源未特定)",
            "is_spoofed": False,
            "domain": "unknown",
        }

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # 1. ドメイン偽装 (.edu.pl のような紛らわしいドメイン) のチェック
    is_spoofed = False
    for spoof in SPOOFED_EDU_TLDS:
        if hostname.endswith(spoof):
            is_spoofed = True
            logger.warning(f"🚨 学術ドメイン偽装疑い検知: {hostname} ({spoof})")
            break

    if is_spoofed:
        return {
            "tier": 3,
            "label": "⚠️ 【偽装疑いドメイン: 学術機関を模した非公式ドメイン】",
            "is_spoofed": True,
            "domain": hostname,
        }

    # 1.5 UGC・個人投稿サイトのハードブロック (Tier 4)
    if any(d in hostname for d in UGC_BANNED_DOMAINS):
        return {
            "tier": 4,
            "label": "❌ UGC・個人投稿サイト (信頼性担保不可)",
            "is_spoofed": False,
            "domain": hostname,
        }

    # 2. Tier 1 (一次情報 / 正規の学術・公的機関・公式発表)
    # 本物の米国教育機関 .edu (ただし偽装リスト除外後) や .gov, .go.jp 等
    is_genuine_edu = hostname.endswith(".edu") and not any(hostname.endswith(s) for s in SPOOFED_EDU_TLDS)
    if is_genuine_edu or any(hostname.endswith(d) or d in hostname for d in TIER1_DOMAINS):
        return {
            "tier": 1,
            "label": "一次情報 (学術・公的機関・公式発表)",
            "is_spoofed": False,
            "domain": hostname,
        }

    # 3. Tier 2 (信頼できる主要メディア・報道・専門調査機関)
    if any(d in hostname for d in TIER2_DOMAINS):
        is_outlook_or_forecast = any(
            kw in (title or "").lower() or kw in url.lower()
            for kw in ["outlook", "forecast", "prediction", "trends", "見通し", "予測", "展望"]
        )
        t2_label = "二次情報 (主要メディア見通し・予測レポート)" if is_outlook_or_forecast else "二次情報 (主要メディア・調査機関)"
        return {
            "tier": 2,
            "label": t2_label,
            "is_spoofed": False,
            "domain": hostname,
        }

    # 4. Tier 3 (三次情報 / SEO記事・一般ブログ・個人サイト・その他)
    is_seo_or_blog = any(kw in hostname.lower() or kw in (title or "").lower() for kw in SEO_SUMMARY_KEYWORDS)
    label = "三次情報 (SEO記事・一般ブログ等)" if is_seo_or_blog else "三次情報 (一般Web記事・要検証)"

    return {
        "tier": 3,
        "label": label,
        "is_spoofed": False,
        "domain": hostname,
    }


def annotate_and_sort_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    検索結果リストに対してソース評価を実施し、各要素に Tier メタデータを付与するとともに、
    信頼度の高い情報（Tier 1/2）を優先表示・偽装ドメインを明示する。
    """
    if not results:
        return results

    annotated = []
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        source = r.get("source", "")
        eval_res = evaluate_source_authority(url, title, source)

        r_copy = dict(r)
        r_copy["tier"] = eval_res["tier"]
        r_copy["tier_label"] = eval_res["label"]
        r_copy["is_spoofed"] = eval_res["is_spoofed"]
        r_copy["domain"] = eval_res["domain"]

        # タイトルまたはスニペットにティアラベルを補足
        tier_badge = f"[Tier {eval_res['tier']}: {eval_res['label']}]"
        r_copy["display_source"] = f"{source} {tier_badge}".strip()

        annotated.append(r_copy)

    # 偽装なし＆Tier順（1 -> 2 -> 3）で優先ソート（安定ソート）
    annotated.sort(key=lambda x: (1 if x["is_spoofed"] else 0, x["tier"]))
    return annotated


def is_finance_context_query(query_or_text: str) -> bool:
    """金融・市場・政治経済系の分析要請かどうかを判定する"""
    if not query_or_text:
        return False
    kw_list = [
        "株価", "日経平均", "TOPIX", "S&P", "NASDAQ", "ダウ", "原油", "WTI", "ブレント",
        "為替", "ドル円", "金利", "利回り", "先物", "市場", "相場", "投資", "銘柄",
        "セクター", "決算", "業績", "収益", "時価総額", "PER", "配当", "アナリスト",
        "金融", "景気", "インフレ", "CPI", "PPI", "FOMC", "日銀",
    ]
    matches = sum(1 for kw in kw_list if kw in query_or_text)
    return matches >= 1


def filter_untrusted_sources_for_finance(results: List[Dict[str, Any]], query_or_text: str = "") -> List[Dict[str, Any]]:
    """
    金融・市場・経済分析コンテキストが検知された場合、
    Tier 3 (個人ブログ・出所不明SEOサイト) や偽装ドメインをハードフィルタリングで除外する。
    ただし Tier 1/2 が0件になってしまう場合は空リストにせず元のリストを返すセーフティ機能付き。
    """
    if not results:
        return results

    if not is_finance_context_query(query_or_text):
        return results

    # まず、Tier 4 (UGC・個人サイト) と偽装サイトは無条件で完全除外する
    no_ugc_results = [r for r in results if r.get("tier", 3) != 4 and not r.get("is_spoofed", False)]
    
    if not no_ugc_results:
        return []

    # さらに金融用の厳格フィルター (Tier 1, 2のみを残す)
    filtered = [r for r in no_ugc_results if r.get("tier", 3) in [1, 2]]
    if not filtered:
        logger.info("[SourceEvaluator] 金融コンテキストでTier 1/2ソースが見つからなかったため、Tier 3ソースを維持します(UGCは除外済み)")
        return no_ugc_results

    removed_count = len(results) - len(filtered)
    if removed_count > 0:
        logger.info(f"[SourceEvaluator] 金融・市場分析モード: Tier 3以下 (UGC/ブログ/SEO等) ソースを {removed_count} 件ハード除外しました")
    return filtered


def verify_entity_claim_attribution(text: str, known_entities: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    複数主体が混在するテキストにおける主語・述語の取り違え（Entity-Claim Attribution 違反）を検知・補正する。
    例: Gemma と Kimi が共起する記事で、主語不明確なまま数値を提示している場合や代名詞「同モデル」「後者」等による混同を検出。

    Returns:
        (is_valid, processed_text)
    """
    if not text or not isinstance(text, str):
        return True, text

    # 複数モデルや複数企業が共起しているか検知（英語名・モデル名パターン）
    model_or_org_pattern = re.compile(
        r"(?<![A-Za-z0-9._-])(Gemma(?:\s+[A-Za-z0-9._-]+)*|Kimi(?:\s+[A-Za-z0-9._-]+)*|Claude(?:\s+[A-Za-z0-9._-]+)*|GPT-[A-Za-z0-9._-]+|Llama(?:\s+[A-Za-z0-9._-]+)*|DeepSeek(?:\s+[A-Za-z0-9._-]+)*|Qwen(?:\s+[A-Za-z0-9._-]+)*)(?![A-Za-z0-9._-])",
        re.IGNORECASE,
    )

    found_entities = set(m.group(0).strip() for m in model_or_org_pattern.finditer(text))
    if known_entities:
        found_entities.update(known_entities)

    # 主体が2つ以上混在している場合
    if len(found_entities) >= 2:
        # 代名詞や曖昧主語（「同モデルは」「後者は」「前者は」「この指標は」等）の検知
        ambiguous_pronouns = ["同モデルは", "後者は", "前者は", "同社は", "このスコアは"]
        has_ambiguous = any(p in text for p in ambiguous_pronouns)

        if has_ambiguous:
            logger.warning(f"🚨 複数主体混在テキスト内で曖昧主語を検知: {found_entities}")
            warning_tag = f"⚠️ **[主語要確認: 複数主体({', '.join(sorted(found_entities))})が共起する文中での主張です]** "
            if warning_tag not in text:
                return False, f"{warning_tag}{text}"

    return True, text
