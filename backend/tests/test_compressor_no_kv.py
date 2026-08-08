"""会話圧縮が永続KVへ書き込まないことの回帰テスト。"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_compress_does_not_call_kv_store_set():
    from app.core.context_compressor import compress_messages_stage2

    messages = [
        {"role": "user", "content": f"古いメッセージ{i} " + ("x" * 500)}
        for i in range(12)
    ] + [
        {"role": "user", "content": "直近の質問"},
        {"role": "assistant", "content": "直近の回答"},
    ]

    fake_json = (
        '{"summary": "市場の話", "key_facts": ['
        '{"target": "日経平均", "note": "終値61434"},'
        '{"target": "日銀", "note": "7/31会合"}'
        "]}"
    )

    async def _run():
        mock_set = AsyncMock()
        with patch("app.core.llm_client.call_model", new_callable=AsyncMock) as mock_llm, \
             patch("app.routers.settings.get_settings", new_callable=AsyncMock) as mock_settings, \
             patch("app.core.kv_store.kv_store") as mock_kv:
            mock_llm.return_value = fake_json
            mock_settings.return_value = {
                "planner_model": "test-model",
                "planner_provider": "test",
            }
            mock_kv.set = mock_set
            result = await compress_messages_stage2(messages, max_keep=2)
            mock_set.assert_not_called()
            # 要約先頭に key_facts が折り込まれる
            head = result[0]["content"]
            assert "引き継ぎファクト" in head or "日経平均" in head
            assert "日銀" in head

    asyncio.run(_run())
