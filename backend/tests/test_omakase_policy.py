"""おまかせ開発依頼ポリシーの単体テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.omakase_policy import (
    contains_forbidden_skill_question,
    is_omakase,
    is_omakase_dev_request,
    is_dev_or_monetize_request,
)
from app.core.fact_filters.format import (
    strip_omakase_skill_questions,
    strip_unrequested_memory_mentions,
)
from app.core.fact_filters.pipeline import apply_grounding_pipeline


def test_omakase_dev_request_detection():
    text = "開発依頼です。＄20を当初予算として稼げるシステムを考えてください。全部おまかせします"
    assert is_omakase(text)
    assert is_dev_or_monetize_request(text)
    assert is_omakase_dev_request(text)


def test_plain_question_is_not_omakase_dev():
    assert not is_omakase_dev_request("今日の天気どう？")
    assert not is_omakase_dev_request("おまかせします")  # 開発文脈なし


def test_forbidden_skill_questions():
    assert contains_forbidden_skill_question("Naoは普段どんなスキルや作業が得意ですか？コードを書けますか？")
    assert contains_forbidden_skill_question("なるべくノーコードでいきたい感じでしょうか？")
    assert contains_forbidden_skill_question("コーディングは可能ですか？")
    assert not contains_forbidden_skill_question("この方針で進めてよいかだけ教えてください。")


def test_omakase_response_must_not_leak_hobbies_or_ask_skills():
    """浅い提案（趣味パーソナライズ＋スキル質問）は後処理で除去される。"""
    user = "開発依頼です。＄20予算で稼げるシステム。全部おまかせします"
    raw = (
        "$20予算でドメイン取得＋無料ホスティングの案です。"
        "Naoさんの趣味（競馬、サッカー、猫など）をテーマにすればよいと思います。"
        "コーディングは可能ですか？それともノーコード志向でしょうか？"
    )
    cleaned = apply_grounding_pipeline(raw, "", user)
    assert "競馬" not in cleaned
    assert "猫" not in cleaned
    assert "コードを書けますか" not in cleaned
    assert "ノーコード" not in cleaned
    assert "$20" in cleaned or "ドメイン" in cleaned


def test_supervisor_prompt_contains_omakase_ban():
    from pathlib import Path
    prompt = (Path(__file__).resolve().parents[1] / "app" / "prompts" / "supervisor_prompt.md").read_text(encoding="utf-8")
    assert "hearing" in prompt and "おまかせ" in prompt
    assert "hearing 禁止" in prompt or "hearing` を絶対に使わない" in prompt or "mode=hearing` を絶対に使わない" in prompt
    assert "Payhip" in prompt
    assert "アフィリエイトブログ" in prompt
