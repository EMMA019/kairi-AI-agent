"""
News Scheduler — 現在はオンデマンド取得に移行したためスタブ。
定期RSS巡回は廃止。全てのニュース取得はユーザーのリクエスト時に実行。
"""
from app.utils.logger import get_logger

logger = get_logger(__name__)


def setup_scheduler():
    """定期スケジューラは無効化（オンデマンド取得に移行）"""
    logger.info("⏰ News Scheduler: 定期RSS巡回は廃止されました。オンデマンド取得モードで動作します。")


def shutdown_scheduler():
    """スタブ"""
    pass