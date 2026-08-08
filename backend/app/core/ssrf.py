"""SSRF 対策: プライベートIP・メタデータエンドポイントへの fetch を拒否。"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}


def is_blocked_url(url: str) -> bool:
    """内部向け・リンクローカル・クラウドメタデータ等への URL なら True。"""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().strip()
        if not host:
            return True
        if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
            return True
        # IPv4/IPv6 リテラル
        try:
            ip = ipaddress.ip_address(host)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                return True
            # AWS/GCP/Azure メタデータ
            if str(ip) == "169.254.169.254":
                return True
            return False
        except ValueError:
            pass

        # ホスト名解決してプライベートIPか確認（DNSリバインディング緩和）
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                addr = info[4][0]
                ip = ipaddress.ip_address(addr)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or str(ip) == "169.254.169.254"
                ):
                    return True
        except socket.gaierror:
            # 解決不能は拒否（安全側）
            return True
        return False
    except Exception as e:
        logger.warning(f"SSRF URL判定エラー ({url}): {e}")
        return True
