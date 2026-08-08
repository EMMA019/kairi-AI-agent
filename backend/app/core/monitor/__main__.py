"""
Proactive Market Radar CLI Entrypoint

使い方:
  python -m app.core.monitor [--dry-run] [--test]
"""
import sys
import asyncio
import argparse
from app.utils.logger import get_logger
from app.core.monitor.engine import run_radar_loop_once

logger = get_logger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Proactive Market Radar — 初動監視バッチ実行")
    parser.add_argument("--dry-run", action="store_true", help="Discordへ送信せずドライランログ出力")
    parser.add_argument("--test", action="store_true", help="ダミーのテストニュースデータを使用して動作検証")
    args = parser.parse_args()

    test_feed = None
    if args.test:
        test_feed = [
            {
                "guid": "test-en-1",
                "title": "SK Hynix Faces Emergency Margin Call Pressures After Semiconductor Export Restrictions",
                "summary": "SK Hynix ($142.50) is experiencing forced liquidation and margin calls due to sudden US chip export controls.",
                "url": "https://www.reuters.com/technology/sk-hynix-margin-call-test",
                "source": "Reuters",
                "published": "2026-07-18T03:00:00Z"
            },
            {
                "guid": "test-jp-1",
                "title": "東証寄り付き直前、キオクシア見通し下方修正による半導体セクター急落予兆",
                "summary": "東京エレクトロンとアドバンテストにも売り先行。サーキットブレーカーへの警戒感。",
                "url": "https://www.nikkei.com/article/test-jp",
                "source": "Nikkei",
                "published": "2026-07-18T03:15:00Z"
            },
            {
                "guid": "test-kr-1",
                "title": "[단독] SK하이닉스·삼성전자 서킷브레이커 발동 우려, 반대매매 급증",
                "summary": "코스피(^KS11) 개장 전 반도체주 레버리지 청산(마진콜) 경보.",
                "url": "https://www.chosunbiz.com/test-kr",
                "source": "ChosunBiz",
                "published": "2026-07-18T03:20:00Z"
            }
        ]
        logger.info("🧪 [TestMode] 日英韓3ヶ国語のダミーテストフィードを使用します")

    await run_radar_loop_once(dry_run=args.dry_run or args.test, test_feed=test_feed)

if __name__ == "__main__":
    asyncio.run(main())
