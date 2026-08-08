import json
import re
from typing import Any
from app.core.llm_client import call_model
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _market_today_shortcut(
    user_input: str,
    current_date: str,
    current_date_en: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """
    「今日の日本/米国市場」系は LLM planner を飛ばして固定クエリを返す。
    明示日付（7/29 等）があればその日を使い、JST今日で上書きしない。
    soft-US（個別株＋材料聞き等）も todayish 無しでショートサーキット可。
    """
    from datetime import datetime
    from app.core.chat_search import (
        _TODAYISH_KW,
        build_us_market_search_queries,
        format_anchor_date_en,
        is_soft_us_single_stock_query,
        parse_explicit_calendar_date,
        resolve_market_anchor_date,
        JST,
    )

    text = user_input or ""
    now = datetime.now(JST)
    providers = ["tavily", "brave", "news"]

    jp = any(k in text for k in ("日本市場", "日経", "東証", "TOPIX", "東京株式", "日本株"))
    us = any(k in text for k in ("米国市場", "アメリカ市場", "NY", "ナスダック", "Nasdaq", "S&P", "ダウ", "Dow", "Wall Street"))
    soft_us = is_soft_us_single_stock_query(text, session_id=session_id)

    # soft-US 個別株は todayish 無しでも planner を飛ばす
    if soft_us and not jp:
        queries = build_us_market_search_queries(text, now_jst=now, company_focus=True)
        return {
            "needs_search": True,
            "search_queries": queries[:4],
            "providers": providers,
            "needs_deep_search": False,
            "recommended_mode": "chat",
            "category": "finance",
        }

    todayish = any(k in text for k in _TODAYISH_KW) or parse_explicit_calendar_date(text) is not None
    if not todayish:
        return None

    # 「市場」単独 + 今日系で日本寄り（locale既定）
    if not jp and not us and ("市場" in text or "相場" in text or "market" in text.lower()):
        if any(k in text for k in ("米国", "アメリカ", "US", "NY")):
            us = True
        else:
            jp = True

    session = "前場" if "前場" in text else ("後場" if "後場" in text else "")

    if jp and not us:
        from app.core.market_session import get_jp_session_bucket, jp_cash_price_query_word

        jp_d = resolve_market_anchor_date(text, market="jp", now_jst=now)
        d = jp_d.isoformat()
        # 明示セッションが無いときは時計セッションで価格語を選ぶ（場中に『終値』固定しない）
        price_word = jp_cash_price_query_word(now) if not session else (
            "前場終値" if session == "前場" else ("現在値" if session == "後場" else "終値")
        )
        # 過去日の明示質問は終値記事が正しい
        if parse_explicit_calendar_date(text) is not None and jp_d < now.date():
            price_word = "終値"
        q_extra = f" {session}".rstrip()
        queries = [
            f"日経平均{q_extra} {price_word} {d}".replace("  ", " ").strip(),
            f"東京株式市場 市況{q_extra} {d}".replace("  ", " ").strip(),
            f"TOPIX {price_word} {d}",
            f"業種別騰落率 東証 {d}",
        ]
        # 引け後は夜間先物クエリに差し替え（朝の夜間終値記事との混同を減らす）
        if get_jp_session_bucket(now) == "closed" and now.hour >= 16:
            queries[3] = f"日経225先物 夜間取引 {d}"
        return {
            "needs_search": True,
            "search_queries": queries[:4],
            "providers": providers,
            "needs_deep_search": False,
            "recommended_mode": "chat",
            "category": "finance",
        }
    if us and not jp:
        queries = build_us_market_search_queries(text, now_jst=now)
        return {
            "needs_search": True,
            "search_queries": queries[:4],
            "providers": providers,
            "needs_deep_search": False,
            "recommended_mode": "chat",
            "category": "finance",
        }
    return None


PLANNER_SYSTEM_PROMPT = """あなたはユーザーの入力と文脈から、**外部Web検索（Brave Search API）** が必要かどうかを判断し、最高品質の検索クエリを構築する専門AIです。
**絶対にJSON形式のみを出力してください。** それ以外のテキストは一切出力しないでください。

【出力フォーマット（厳守）】
{
  "reasoning": "検索が必要かどうかの理由（短く箇条書きで）",
  "needs_search": true または false,
  "search_queries": ["検索キーワード1", "検索キーワード2"],
  "providers": ["brave", "wikipedia", "news", "weather"],
  "needs_deep_search": true または false,
  "recommended_mode": "chat" または "task",
  "category": "finance" または "coding" または "travel" または "general" # ユーザーの質問のジャンル。株式・金融・相場・経済は finance, プログラミング・システム開発・エラー解決は coding, 旅行・観光・乗り換えは travel, それ以外の一般的な日常会話や話題は general
}

【🔴 検索クエリ設計の絶対ルール (P1/P3 改善指示準拠・キーワード抽出必須化)】
1. **自然文のまま投げない（キーワード抽出・サニタイズ必須化）**: ユーザーの質問（「半導体は短期狙いだったんだ。今は思惑外れてるけどｗ 組み込むならどんな銘柄がいいと思う？」「見ての通り半導体比率が高いのでリバランスしたい」等）をそのまま検索クエリにすることは絶対に禁止です！『ｗ』や『〜だけど』『どう思う？』等の口語・会話表現・接続詞をすべて削ぎ落とし、必ず検索最適化されたキーワード群（例: `["半導体株 ETF 見通し 2026", "半導体セクター リバランス 注目銘柄 2026"]` や `["semiconductor ETF stock outlook July 2026"]`）に変換してください。
2. **時制・日付・四半期情報の反映と日付フィルタ自動付与**: 対象の日付（例: 2026-07-01, Q2 2026）がある場合は、必ずクエリに年号や日付を含めてください。さらに、**「最新ニュース」「今日の」「最近の」などのニュース系クエリの場合、現在の日付を考慮して `after:YYYY-MM-DD` 形式の日付フィルタをクエリに自動付与すること**（例: `world politics economy news after:2026-07-01`）。これにより古い記事の混入を防ぎます。
3. **一次ソースドメインの優先追加 (🟢 P3)**: 株式・財務・開示情報を調べる際は、一般的なニュースサイトだけでなく、一次ソース（SECや公式IR等）にヒットしやすいクエリ（例: `"ティッカー" dividend SEC`, `"ティッカー" investor relations`, `site:sec.gov "ティッカー"`）を配列に優先追加してください。
4. **コーポレートアクションの最優先照合 (🟠 P1)**: 銘柄の急落や急騰理由を調べる際は、決算だけでなく「配当権利落ち日 (ex-dividend date)」「株式分割 (stock split)」「公募増資 (offering)」などのコーポレートアクションが直接原因である可能性が極めて高いため、必ず `"ティッカー" ex-dividend date 2026` 等のイベント照合クエリを第1候補として組み込んでください。
5. **英語クエリの原則と日付範囲指定の徹底**: 検索エンジンは英語のほうが圧倒的にヒット率・情報の質が高いため、日本国内のローカルな話題以外はすべて英語で同義クエリを1〜2個（最大2個）生成してください。ニュース・政治経済のクエリには必ず `after:YYYY-MM-DD` または `2026` の年号を含めること。例えば「世界の政治経済ニュース」→ `["world politics economy news after:2026-07-01", "global economic news July 2026"]` のように、日付範囲を明示したクエリを優先してください。
6. **全領域における両面バランス・多角的検索クエリのペア生成 (🔴 最重要・厳守)**: 市場相場（下落・暴落など）に限らず、政治経済、技術評価、製品レビュー、社会問題、学術論文などあらゆるテーマの検索において、**一方向の見解やネガティブ/ポジティブ単一キーワードだけに偏った検索クエリを生成することを厳禁します。**
   - 例えば「半導体の暴落は懸念で済んだ？」なら、下落要因のクエリと **反発・回復トレンド（rebound / recovery / latest update）** のクエリをペアで生成する。
   - 例：「〇〇技術の欠点は？」なら、欠点（drawbacks / issues）と同時に **解決策・最新改善・メリット（solutions / latest improvements）** も合わせる。
   - 常に「そのテーマに関する主要な事象・問題・見解」を調べる第1クエリと、「その反対側面・最新フォローアップ・回復動向・別視点」を調べる第2クエリをバランスよくペア（配列最大2件）にして生成し、両面からのファクトを同時に収集できるようにしてください！
6.5. **施設料金・営業時間・チケット価格の「公式サイト検索」ルール (🟡 P1)**: 観光地・水族館・施設等の「料金」「営業時間」「定休日」に関する質問時は、まっぷるやじゃらん等のまとめ記事で止まらず正確な最新料金（例：改定後料金）を確認できるように、必ず「施設名 料金 営業時間 公式」「施設名 入園料 2026 公式サイト」のような公式サイト・公式案内をヒットさせるキーワードを生成すること。
6.6. **日本株・日本市場に関する検索クエリ (🔴 P0)**: 「今日の日本市場どうだった？」「日経平均は？」等の日本市場・国内市況に関する質問時は、必ず日本語の具体的キーワード（例: `["東京株式市場 日経平均 今日 終値 市況", "日本株 今日 動向 ニュース"]`）を作成し、`providers` は必ず `["brave", "news"]` を併用してください。"news" 単体だと海外英語RSSに偏るため、日本の終値や株価動向を確実に取得するため `["brave", "news"]` を必須とします。
6.7. **米国株・米国市場に関する検索クエリ (🔴 P0)**: 「米国市場どうだった？」「NYダウは？」等の米国市場に関する質問時は、日本語の記事だと指数の具体的な数値が欠落しやすいため、絶対に日本語で検索せず、必ず英語のキーワード（例: `["US stock market closing numbers July 2026", "S&P 500 Dow Jones Nasdaq closing July 2026"]`）を生成してください。
6.8. **企業のCEO・経営陣・組織トップに関する検索クエリ (🔴 P0)**: 企業や団体のCEO、役員体制、人事異動に関する質問時は、AIモデルの過去データによる古い役職ハルシネーションを防ぐため、必ず現在の年号 `2026` を含めた最新情報を取得できるキーワード（例: `["Company name current CEO leadership 2026", "企業名 現CEO 経営陣 2026"]`）を生成してください。
6.9. **選択肢・推薦リストからの個別タイトル・作品・項目への言及時の必須検索とエンティティ特定 (🔴 P0)**: 直前の会話履歴に複数の選択肢や推薦リスト（アーティスト、アルバム、作品、製品、機能等）が存在し、ユーザーがそのうちの特定の曲名・作品名・項目名（例：「How Long Have I Been You Fool聴きました」「〇〇について詳しく」）に言及した場合、コンテキスト内の近接バイアスで別の直近アーティストや主語に誤帰属させるハルシネーションを防ぐため、必ず `needs_search: true` とし、その個別タイトルと親エンティティを特定確認する検索クエリ（例: `["How Long Have I Been You Fool artist song details"]`）を作成すること。
6.10. **【実績と見通しの厳格分離】全経済統計・決算イベントにおける対象期間と時系列同期クエリ (🔴 P0)**: ユーザーから雇用統計・CPI・PCE・決算等の質問があった場合、必ずユーザーの意図が「過去の実績」か「未来の見通し」かを判定し、検索クエリ内で両者を明確に分離してください。
   - **実績を求めている場合（例: 「Q3実績は？」「前回の決算はどうだった？」「Capexはいくら？」）**: 検索キーワードに必ず `actual results`, `reported`, `earnings release` 等を優先し、`outlook`, `guidance`, `forecast`, `estimate` は**絶対に含めない**でください。
   - **見通しを求めている場合（例: 「来期はどうなる？」「今後の予測は？」）**: 検索キーワードに `outlook`, `guidance`, `forecast` などを意図的に追加してください。
   - **意図が曖昧な場合（例: 「最近の〇〇の決算について」）**: この場合のみ、実績のクエリと見通しのクエリの2パターンを作成（例: `["Company Q1 2026 earnings actual", "Company Q2 2026 guidance outlook"]`）してください。片方に決めつけてはいけません。
   - **複数指標・決算・イベントの比較・同期検索原則**: 「今回のCPIは良かったが、雇用統計のときは？」「Q2決算と他社の比較」のように複数の項目を比較・言及している際は、比較先の全項目も必ず同じデータ対象期間（例：同じ6月度データ、同じ四半期）のキーワード (`["US jobs report June 2026 actual", "US PCE June 2026"]`) にアンカー・同期させ、異なる期を取り違えて検索する頓珍漢なクエリ生成を全ドメインで厳格に禁止します。
   - これにより、ユーザーが過去の確定データを求めているのに「予想・見通し」記事が混入して実績値と誤認してしまう最悪のハルシネーションリスクを根本から根絶します。
7. **マルチトピック・人物のクエリ分割**: ユーザーの質問に複数の人物、異なる企業、異なるトピック（例: 「鈴木ザイオンと佐野海舟の最新情報」）が含まれている場合、必ず各トピックや人物ごとに独立した検索キーワードを作成し、`search_queries` 配列に複数出力してください。APIコスト削減のため**クエリ数は最大2個まで**に厳格制限してください。
8. **一般的なトレンド・カルチャー・ライフスタイル検索のクエリ設計**: 「最近欧米のトレンドって何かある？」「最近の話題は？」等の一般的なトレンドを問われた際、経済・マクロ指標だけに偏らないよう、カルチャー、テクノロジー、ライフスタイル、旅行、社会動向など多様なトピックをカバーする英語クエリ（例: `["latest US Europe cultural lifestyle tech trends July 2026", "current consumer lifestyle trends US Europe 2026"]`）を作成してください。また、年始に書かれた過去の年間予測記事ばかりヒットしないよう、現在の日時を踏まえた時期キーワードや日付範囲（`after:YYYY-MM-DD`）を組み合わせて最新情報が取得できるようにしてください。

【判定ルール（優先順位順）】
1. 【最優先】「なんか熱い銘柄ない？」「今日熱い銘柄は？」など具体的なティッカー・セクター名が含まれない単純な「注目銘柄」の質問は `needs_search: false` としますが、ユーザーが「半導体」「リバランス」「ポートフォリオ」「決算」「インフレ」等のセクターや市場見通しに言及しながら組み入れ候補・今後の動向を尋ねている場合（例：「半導体は短期狙いだった。組み込むなら？」「半導体比率が高いのでリバランスしたい、何がいい？」等）は、必ず `needs_search: true` とし、「半導体株 ETF リバウンド 見通し 2026」「半導体セクター 注目銘柄 リバランス 2026」「semiconductor ETF stock outlook July 2026」のような検索用キーワードクエリ配列を出力してください。
2. 特定の話題やニュース、最近の出来事、あるいは過去の会話で提示されたおすすめ・選択肢内の個別作品名・曲名・製品・項目について尋ねられたり感想を言われた場合は、検索さぼりによる近接文脈バイアス・誤帰属を根絶するため、必ず `needs_search: true` として検索を実行してください。
2.5. 【スポーツ・競馬・レース等の実世界イベントのフォローアップ】競馬（馬名・騎手・オッズ・配当・血統）、スポーツ試合結果、レース結果などの実世界イベントについて、直前の会話で触れた話題への感想・追加質問・補足確認（例：「でも直前まで13倍以上ついてた」「騎手は誰？」「アルゴ入ってるのかな」）であっても、必ず `needs_search: true` とし、関連する英語または日本語の事実確認クエリを生成してください。検索さぼりによる騎手名・オッズ・記録のパラメトリック記憶ハルシネーションを防ぐためです。
3. 政治・経済・世界情勢・天気の質問も `true` にしてください。
4. AI自身の記憶や日常の挨拶・単純な雑談は `false` にしてください。

【検索プロバイダーの選択 (providers)】
- "news": 政治経済や世界情勢などの一般ニュース（RSSニュースデータベース）
- "brave": 上記以外のウェブ検索（SEC公式や開示ドキュメント、専門技術、ローカルな話題など）
- "weather": 天気情報を取得
- "wikipedia": Wikipediaで調べられるクエリ

【ユーザーからの特別ルール（最優先厳守）】
1. 一般的な「ニュース教えて」「今日の市場はどう？」「最近の話題は？」などのざっくりした要望や、マクロ経済・政治・社会の話題の場合は、必ず `providers: ["news", "brave"]` を優先して選択してください。"brave" 単体に偏ると一般ニュースが欠落し、"news" 単体だと日本市場など国内金融動向が欠損するため併用を厳守すること。
2. 特定のニッチな話題、個人の名前、特定の製品リリース、専門技術などの最新情報をピンポイントで調べる場合は、RSSには存在しない可能性が高いため `["brave"]` を優先してください。ユーザーが「RSS」と明示指定した場合は `["news"]` を強制します。
"""


async def plan_search(
    user_input: str,
    history_messages: list[dict],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    高速な実行モデル (LLM) を呼び出し、検索の必要性と最適なクエリを判定する。
    """
    from datetime import datetime, timezone, timedelta
    from app.core.prompt_builder.entity_resolution import is_finance_jargon_topic_shift

    recent_history = history_messages[-3:] if len(history_messages) >= 3 else history_messages

    # 金融ジャーゴン短文（介入/円安等）は前ターンの企業・銘柄履歴を planner に渡さない
    # （履歴バイアスで「前の銘柄の規制」等にクエリが吸着するのを防ぐ。特定企業向けではない）
    topic_reset = is_finance_jargon_topic_shift(user_input or "")
    if topic_reset:
        recent_history = []
        logger.info("Search Planner: 金融ジャーゴン話題転換のため会話履歴を検索計画から除外")

    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    current_date = now.strftime("%Y-%m-%d")
    # 表示用: July 27, 2026
    current_date_en = now.strftime("%B %d, %Y").replace(" 0", " ")

    # --- 市場「今日/本日」ショートサーキット（planner LLM 1往復を省略）---
    short = _market_today_shortcut(
        user_input or "", current_date, current_date_en, session_id=session_id
    )
    if short:
        logger.info(f"⚡ 市場今日系ショートサーキット: {short['search_queries']}")
        return short

    context_text = f"【現在の日付: {current_date}】\n\n【直近の会話履歴】\n"
    if not recent_history:
        context_text += "なし\n"
    else:
        for m in recent_history:
            role = "ユーザー" if m["role"] == "user" else "AI"
            content = m["content"]
            if len(content) > 800:
                content = content[:200] + "\n...[中略]...\n" + content[-600:]
            context_text += f"{role}: {content}\n"

    context_text += f"\n【最新のユーザー入力】\n{user_input}\n"
    context_text += "\nこの入力に答えるために外部Web検索が必要か判定し、**JSONのみ**を出力してください。"
    if topic_reset:
        context_text += (
            "\n※本入力は市場マクロ系の短い話題転換です。"
            "直前の個別銘柄・企業名を検索クエリに引き継がないこと。"
        )

    try:
        from app.routers.settings import app_settings
        settings = app_settings.get()
        provider = settings.get("planner_provider", "deepseek")
        model_name = settings.get("planner_model", "deepseek-v4-flash")

        # temperature は残す（call_model が対応していれば有効）
        response_text = await call_model(
            system_instruction=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context_text}],
            model_name=model_name,
            provider=provider,
            max_tokens=1600,
            temperature=0.3  # 残す
        )

        logger.debug(f"Search Planner Raw Response: {response_text}")

        needs_search = False
        search_queries = []
        providers = ["brave"]
        needs_deep_search = False
        recommended_mode = "chat"
        category = "general"

        if not response_text or not response_text.strip():
            logger.warning("Search Planner received an empty response from LLM.")
        else:
            # JSON抽出（ネスト対応の堅牢なパーサーを使用）
            from app.utils.parser import find_json_objects
            
            json_str = None
            # まずMarkdownのコードブロック内を探す
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                # ネスト対応のブレースカウントで抽出
                objs = find_json_objects(response_text)
                if objs:
                    json_str = objs[0]  # 最初のJSONオブジェクトを使用
                else:
                    logger.error(f"JSON not found in response: {response_text[:200]}")

            if json_str:
                json_str = json_str.strip()
                data = json.loads(json_str)

                needs_search = bool(data.get("needs_search", False))
                
                # search_queries のリストを取得し、もし古いフォーマットで search_query があればそれもリストに追加する
                search_queries = data.get("search_queries", [])
                if not search_queries and "search_query" in data and data["search_query"]:
                    search_queries = [str(data["search_query"])]
                search_queries = search_queries[:2]  # 最大2個に厳格制限

                providers = data.get("providers", ["brave"])
                needs_deep_search = bool(data.get("needs_deep_search", False))
                recommended_mode = str(data.get("recommended_mode", "chat"))
                category = str(data.get("category", "general"))

    except Exception as e:
        logger.error(f"Search Planner failed or invalid format: {e}")
        needs_search = False
        search_queries = []
        providers = ["brave"]
        needs_deep_search = False
        recommended_mode = "chat"
        category = "general"
    
    # 【強制ハードコード】ユーザーが明示的にRSSを求めた場合のみ強制上書き
    if "RSS" in user_input.upper():
        providers = ["news"]
        needs_search = True
        if not search_queries:
            search_queries = [user_input]
        logger.info(f"強制ルール適用: 'RSS' が含まれているため、providers を ['news']、needs_search を True に上書きしました。")

    # 【強制ハードコード】競馬・スポーツ実世界イベントのフォローアップは検索必須
    _SPORTS_EVENT_KW = [
        "競馬", "騎手", "単勝", "オッズ", "配当", "馬券", "G1", "GⅠ",
        "キングジョージ", "ダービー", "血統", "鞍上",
        "試合結果", "スコア", "優勝", "決勝",
    ]
    history_blob = " ".join(str(m.get("content", ""))[:300] for m in recent_history)
    if any(kw in user_input or kw in history_blob for kw in _SPORTS_EVENT_KW):
        # 挨拶のみは除外
        if not re.fullmatch(r"[\s　]*(おはよう|こんにちは|こんばんは|よろしく|ありがとう)[！!。．\s　]*", user_input or ""):
            if not needs_search:
                needs_search = True
                logger.info("強制ルール適用: スポーツ・競馬関連の実世界イベント言及のため needs_search=True")
            if not search_queries:
                search_queries = [user_input[:80]]

    # 【強制ハードコード】単独の「介入」は日本語市況では為替介入が既定読み
    # （規制・独禁・DMA・EU 等が明示されたときだけスキップ。個別銘柄名は条件に使わない）
    _REGULATORY_INTERVENTION_RE = re.compile(
        r"規制|独禁|独占|DMA|反トラスト|antitrust|EU罰金|独占禁止|当局|欧州委|"
        r"(?<![A-Za-z])EU(?![A-Za-z])",
        re.IGNORECASE,
    )
    if "介入" in (user_input or "") and not _REGULATORY_INTERVENTION_RE.search(user_input or ""):
        from app.core.chat_search import format_anchor_date_en

        d_iso = current_date
        d_en = format_anchor_date_en(now.date())
        needs_search = True
        search_queries = [
            f"為替介入 {d_iso}",
            f"日銀 ドル円 介入 {d_iso}",
            f"BOJ dollar yen intervention {d_en}",
        ]
        providers = ["tavily", "brave", "news"]
        category = "finance"
        logger.info("強制ルール適用: 単独『介入』→ 為替介入クエリ（銘柄非依存）")

    # Brave 月額枯渇時でも市況が動くよう、finance は Tavily を先頭に足す
    if needs_search and (
        category == "finance"
        or any(k in (user_input or "") for k in ("市場", "株", "市況", "日経", "ダウ", "ナスダック", "S&P", "介入", "為替"))
    ):
        providers = ["tavily"] + [p for p in (providers or []) if p != "tavily"]

    return {
        "needs_search": needs_search,
        "search_queries": search_queries,
        "providers": providers,
        "needs_deep_search": needs_deep_search,
        "recommended_mode": recommended_mode,
        "category": category
    }