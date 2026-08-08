import pytest
from app.core.fact_filters.financial import verify_actual_vs_guidance_hallucination

def test_msft_capex_hallucination():
    """
    過去のハルシネーション事例：MSFT Capex（設備投資）に関するテスト
    ソースには「設備投資の見通しはXドル」とあるのに、回答で「当四半期の設備投資の実績はXドル」
    と断定してしまうハルシネーションを防ぐ回帰テスト。
    """
    # ソースには「見通し (expect/guidance)」が含まれている
    source_text = "Microsoft Q3 earnings: We expect capital expenditures (Capex) to be $14 billion for the next quarter. Actual Q2 Capex was $12 billion."
    
    # 悪い回答例：見通しの数値を、実績として断定してしまっている
    bad_ai_answer = "Microsoftの第2四半期決算では、設備投資の実績は140億ドル（14 billion）でした。"
    
    # 関数を通す
    filtered_answer = verify_actual_vs_guidance_hallucination(bad_ai_answer, source_text=source_text)
    
    # フィルタが適切に介入し、警告文言や修正が加わっていることを確認する
    # 現在の実装では、ソース側に future マーカーがあり、回答に actual マーカーがある場合に、
    # 警告テキストが付加される仕様になっているはず。
    assert "⚠" in filtered_answer or "実績" not in filtered_answer or "見通し" in filtered_answer, \
        f"ハルシネーションがフィルタされませんでした: {filtered_answer}"

def test_no_hallucination_guidance_properly_stated():
    """
    AIが正しく「見通し」と述べている場合はフィルタが干渉しないことの確認。
    """
    source_text = "Microsoft expects Capex to be $14 billion."
    good_ai_answer = "Microsoftの設備投資の見通しは140億ドルです。"
    
    filtered_answer = verify_actual_vs_guidance_hallucination(good_ai_answer, source_text=source_text)
    
    # 変更されていないことを確認
    assert filtered_answer == good_ai_answer

