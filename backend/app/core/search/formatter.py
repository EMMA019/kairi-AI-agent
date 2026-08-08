import re
from app.core.source_evaluator import annotate_and_sort_search_results

def _filter_entity_noise(query: str, results: list[dict]) -> list[dict]:
    """
    エンティティの曖昧さ回避（例: Zion Suzuki やサッカー選手の検索にバイクのスズキが混じってしまう問題の完全阻止）
    """
    if not query or not results:
        return results
        
    query_lower = query.lower()
    person_sports_keywords = [
        "zion", "suzuki", "sano", "kaishu", "tonali", "soccer", "football", "player", "transfer",
        "鈴木", "ザイオン", "佐野", "海舟", "選手", "サッカー", "移籍", "代表", "w杯", "ワールドカップ", "gk", "mf", "df", "fw", "クラブ"
    ]
    is_person_or_sports = any(kw in query_lower for kw in person_sports_keywords)
    
    vehicle_noise_pattern = re.compile(
        r"(motorcycle|two wheeler|bike|bikers|automobile production|motorcyclesdata|showrooms|specs in india|royal enfield|ducati|scooter|バイク|二輪|車種|試乗|排気量|自動車生産|販売台数|新車価格)",
        re.IGNORECASE
    )
    
    filtered = []
    for r in results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        text_content = f"{title} {snippet}"
        
        if is_person_or_sports and vehicle_noise_pattern.search(text_content):
            if not any(skw in text_content.lower() for skw in ["soccer", "football", "goalkeeper", "gk", "japan national", "parma", "sint-truiden", "サッカー", "日本代表", "移籍", "パルマ", "スタジアム"]):
                continue
        filtered.append(r)
        
    return filtered if filtered else results


from app.core.source_evaluator import annotate_and_sort_search_results, filter_untrusted_sources_for_finance

def _result_published(r: dict) -> str:
    """既存パイプラインの published / fetched_at を拾う（無いなら空。捏造しない）。"""
    for key in ("published", "pub_date", "published_at", "fetched_at", "date"):
        val = (r.get(key) or "").strip() if isinstance(r.get(key), str) else r.get(key)
        if val:
            return str(val).strip()
    return ""


def format_results(results: list[dict], query: str = "") -> list[dict]:
    """プロバイダーに関わらず統一フォーマットに変換し、エンティティノイズ除去＆ソースTier評価を自動適用"""
    filtered_results = _filter_entity_noise(query, results)
    formatted = []
    for r in filtered_results[:10]:  # ユーザー要望により10件に拡大
        item = {
            "title":   r.get("title", ""),
            "snippet": r.get("snippet", "")[:300], # トークン節約のため500->300文字に削減
            "url":     r.get("url", ""),
            "source":  r.get("source", "unknown"),
        }
        pub = _result_published(r)
        if pub:
            item["published"] = pub
        formatted.append(item)
    # ソース評価層によるTier分類 (.edu偽装検知、一次/二次/三次分類と並べ替え)
    annotated = annotate_and_sort_search_results(formatted)
    # 金融・市場分析モード時の Tier 3 (ブログ等) ハードフィルタリング
    annotated = filter_untrusted_sources_for_finance(annotated, query)
    return annotated


def format_for_prompt(results: list[dict], query: str = "") -> str:
    """プロンプト注入用テキストに整形。結果なしの場合は強い制約を返す"""
    if not results:
        # ハルシネーションを絶対に防ぐための強い制約
        return (
            f"「{query}」の検索結果が見つかりませんでした。\n"
            "【重要・絶対遵守】この質問に対して、あなたは自分の持つ事前知識を使って回答を生成してはいけません。\n"
            "必ず「検索結果が見つからなかったため、回答を保留します。恐れ入りますが公式サイト等をご確認ください。」とだけ返答してください。\n"
            "推測や古い情報を混ぜることは固く禁じます。"
        )
        
    lines = [
        "【引用契約】以下の各ソースには番号 [n] が付いています。"
        "時事的な事実（人名/役職/数値/レース結果/市場結果等）を断定する文には、"
        "根拠としたソース番号を文末に [n] 形式で必ず付与してください。"
        "番号を付けられない事実は断定せず、『（要確認）』とするか書かないでください。"
        "各ソースの published 日時を時系列整理に使い、日時不明の水準同士を因果でつなげないでください。"
    ]
    for i, r in enumerate(results, 1):
        display_src = r.get("display_source", r["source"])
        warning = " ⚠️【学術ドメイン偽装疑い】" if r.get("is_spoofed") else ""
        pub = _result_published(r) or "unknown"
        lines.append(
            f"[{i}] (published: {pub}) [{display_src}]{warning} {r['title']}\n"
            f"   {r['snippet']}\n"
            f"   URL: {r['url']}"
        )
    return "\n\n".join(lines)
