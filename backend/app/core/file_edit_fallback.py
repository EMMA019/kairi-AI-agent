"""
File Edit Fallback — ファイル編集のフォールバックチェーン

【目的】
<replace> のSEARCH対象が見つからない場合に、段階的なフォールバックで
修正を試みる。最終手段としてExecutorにファイルの最新状態を通知。

【フォールバックチェーン】
1. 完全一致で置換（通常）
2. 句読点/改行を正規化して再試行
3. 前後5行を広げて再試行
4. ファイル全体を読み直してExecutorに通知
"""
import re
import os
from typing import Optional, Tuple
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_whitespace(text: str) -> str:
    """空白・改行を正規化して比較しやすくする"""
    # 改行を統一
    text = text.replace('\r\n', '\n')
    # 行末のスペースを削除
    lines = [line.rstrip() for line in text.split('\n')]
    # 空行の連続を1つに
    result = []
    prev_empty = False
    for line in lines:
        if not line.strip():
            if not prev_empty:
                result.append(line)
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False
    return '\n'.join(result)


def _normalize_japanese_punctuation(text: str) -> str:
    """日本語の句読点を正規化"""
    text = text.replace('，', ',').replace('．', '.')
    text = text.replace('　', ' ')
    # 全角スペース→半角
    text = text.replace('\u3000', ' ')
    return text


def fuzzy_replace(
    file_content: str,
    search_text: str,
    replace_text: str,
) -> Optional[str]:
    """
    段階的なフォールバック置換。
    
    Returns:
        成功した場合は新しいファイル内容、失敗した場合は None
    """
    # Step 1: 完全一致
    if search_text in file_content:
        logger.info("✅ 完全一致で置換成功")
        return file_content.replace(search_text, replace_text, 1)
    
    # Step 2: 空白正規化後
    normalized_file = _normalize_whitespace(file_content)
    normalized_search = _normalize_whitespace(search_text)
    if normalized_search in normalized_file:
        logger.info("✅ 空白正規化後で置換成功")
        # 元のファイルで該当位置を見つけて置換
        idx = normalized_file.find(normalized_search)
        # 元のファイルの該当位置にマッピング
        file_lines = file_content.split('\n')
        norm_lines = normalized_file.split('\n')
        
        # 行ベースで置換
        search_lines = normalized_search.split('\n')
        file_lines_joined = '\n'.join(file_lines)
        norm_file_joined = '\n'.join(norm_lines)
        
        norm_idx = norm_file_joined.find(normalized_search)
        if norm_idx >= 0:
            # 行番号を特定
            prefix = norm_file_joined[:norm_idx]
            start_line = prefix.count('\n')
            end_line = start_line + len(search_lines)
            
            # 元のファイルで置換（複数行のreplace_text対応）
            replace_lines = replace_text.split('\n')
            result_lines = file_lines[:start_line] + replace_lines + file_lines[end_line:]
            return '\n'.join(result_lines)
    
    # Step 3: 句読点も正規化
    punct_file = _normalize_japanese_punctuation(file_content)
    punct_search = _normalize_japanese_punctuation(search_text)
    if punct_search in punct_file:
        logger.info("✅ 句読点正規化後で置換成功")
        idx = punct_file.find(punct_search)
        pre = file_content[:idx]
        post = file_content[idx + len(search_text):]
        # 実際の位置はsearch_textの長さを使う（search_textは元のテキスト）
        return pre + replace_text + post
    
    # Step 4: 前後5行を広げて検索
    search_lines = search_text.split('\n')
    file_lines = file_content.split('\n')
    
    # 最初の行と最後の行がユニークならそれで検索
    first_line = search_lines[0].strip()
    last_line = search_lines[-1].strip()
    
    if first_line and last_line:
        for i in range(len(file_lines)):
            if file_lines[i].strip() == first_line:
                # 前後5行の範囲でlast_lineを探す
                for j in range(i, min(i + len(search_lines) + 10, len(file_lines))):
                    if j < len(file_lines) and file_lines[j].strip() == last_line:
                        # この範囲が目的のブロックとみなす
                        logger.info(f"✅ 範囲マッチで置換成功 (lines {i}-{j})")
                        replace_lines = replace_text.split('\n')
                        result_lines = file_lines[:i] + replace_lines + file_lines[j+1:]
                        return '\n'.join(result_lines)
    
    # すべて失敗
    return None


def try_replace_with_context(
    file_path: Path,
    search_text: str,
    replace_text: str,
) -> Tuple[bool, Optional[str]]:
    """
    ファイルの置換を試み、失敗時はファイル全文を返す。
    
    Returns:
        (success, new_content または ファイル全文 if failed)
    """
    if not file_path.exists():
        return False, f"[エラー: ファイルが見つかりません: {file_path}]"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        file_content = f.read()
    
    # フォールバック置換
    new_content = fuzzy_replace(file_content, search_text, replace_text)
    
    if new_content is not None:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True, None
    
    # 全失敗 → ファイル全文を返す
    return False, file_content