"""SKILL.md frontmatter とアクティブスキル読込。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple


def parse_skill_frontmatter(content: str) -> Tuple[dict, str]:
    """YAML風 frontmatter を簡易パース（PyYAML非依存）。"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    meta_raw, body = parts[1], parts[2]
    meta: dict = {}
    # keywords: ["a", "b"]
    kw_match = re.search(r"^keywords:\s*\[(.*?)\]", meta_raw, re.MULTILINE | re.DOTALL)
    if kw_match:
        inner = kw_match.group(1)
        meta["keywords"] = [
            m.group(1) for m in re.finditer(r'["\']([^"\']+)["\']', inner)
        ]
    name_m = re.search(r"^name:\s*[\"']?([^\n\"']+)", meta_raw, re.MULTILINE)
    if name_m:
        meta["name"] = name_m.group(1).strip()
    desc_m = re.search(r"^description:\s*[\"']?(.+?)[\"']?\s*$", meta_raw, re.MULTILINE)
    if desc_m:
        meta["description"] = desc_m.group(1).strip()
    return meta, body.lstrip("\n")


def skill_matches(user_input: str, folder_name: str, keywords: List[str]) -> bool:
    lower = (user_input or "").lower()
    if folder_name.lower() in lower or folder_name.replace("-", " ") in lower:
        return True
    for kw in keywords:
        if not kw:
            continue
        if kw.lower() in lower:
            return True
    return False
