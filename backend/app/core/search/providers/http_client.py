"""
共有 httpx.AsyncClient シングルトン。
各検索プロバイダーが毎回クライアントを生成・破棄するのを防ぎ、
コネクションプールを再利用してパフォーマンスを向上させる。
"""
import httpx

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """httpx.AsyncClient のシングルトンを取得"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_http_client() -> None:
    """アプリ終了時にクライアントを閉じる"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
