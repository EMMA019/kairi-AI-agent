"""途切れ検知・旅行免責誤爆の回帰テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.markup import looks_incomplete_output
from app.core.fact_filters.safety import enforce_variable_numerical_claims
from app.routers.settings import app_settings


def test_looks_incomplete_trailing_backtick():
    text = (
        "ツール\t用途\n"
        "<run_command>\tコマンド実行\n"
        "`\n"
    )
    assert looks_incomplete_output(text)


def test_looks_incomplete_markdown_table_mid_cell():
    text = (
        "項目\t詳細\n"
        "---|---\n"
        "| ツール実行能力 | コマンド実行（`<run_command>`）・URLスクレイピング（`\n"
    )
    # pipe table variant
    text2 = "| ツール実行能力 | URLスクレイピング（`"
    assert looks_incomplete_output(text2)


def test_looks_incomplete_japanese_no_period():
    text = "これは十分な長さのある日本語の文章ですが、途中で切れて句点や閉じ括弧なしで終わっている状態そのものです"
    assert looks_incomplete_output(text)


def test_complete_japanese_ok():
    text = "これは十分な長さのある日本語の文章で、きちんと句点で終わります。"
    assert not looks_incomplete_output(text)


def test_self_intro_no_travel_disclaimer():
    """能力説明の『観光』＋禁止例『70%』でもお出かけ免責を付けない。"""
    text = (
        "私はWeb検索・情報収集として最新ニュースや市場データ、観光情報などの収集ができます。"
        "投資助言はしません。「70%上昇」等の確度の数値化もしません。"
    )
    out = enforce_variable_numerical_claims(text, "", user_input="あなたってどんなAI？")
    assert "お出かけ前" not in out
    assert "店舗へ直接" not in out
    assert "※一部の比率" not in out
    assert "Some ratios, market indicators" not in out


def test_ai_diff_meta_no_finance_disclaimer():
    """他AIとの違いの説明で『100%一貫』『確度70%』『市場分析』があっても金融免責を付けない。"""
    text = (
        "金融・市場分析における厳格なルールとして、投資助言や「確度70%」などの数値化は行いません。"
        "口調の100%一貫維持も徹底します。"
    )
    out = enforce_variable_numerical_claims(text, "", user_input="ほかのAIエージェントとの違いは？")
    assert "※一部の比率" not in out
    assert "Some ratios, market indicators" not in out
    assert "お出かけ前" not in out


def test_travel_query_keeps_travel_disclaimer():
    """ユーザーが旅行を聞いているときは従来どおりお出かけ注記。"""
    app_settings.update({"locale": "ja"})
    text = "ホテル周辺のカフェは徒歩5分です。ランチは70%が予約必須との情報があります。"
    out = enforce_variable_numerical_claims(text, "", user_input="下田のホテル周辺の観光スポット教えて")
    assert "お出かけ前" in out


def test_market_query_keeps_finance_disclaimer():
    """ユーザーが市場を聞いているときは金融免責を付ける。"""
    app_settings.update({"locale": "ja"})
    text = "日経平均は一時700円超下落。半導体セクターは約4%安となりました。"
    out = enforce_variable_numerical_claims(text, "", user_input="今日の日本市場どうだった？")
    assert "※一部の比率" in out or "公式開示" in out


def test_market_query_finance_disclaimer_english_locale():
    """locale=en なら金融免責は英語（user_input の金融意図検出は従来どおり）。"""
    app_settings.update({"locale": "en"})
    text = "日経平均は一時700円超下落。半導体セクターは約4%安となりました。"
    out = enforce_variable_numerical_claims(text, "", user_input="今日の日本市場どうだった？")
    assert "Some ratios, market indicators" in out
    assert "official disclosures" in out
    assert "※一部の比率" not in out
