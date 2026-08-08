from app.utils.logger import get_logger
from .heuristics import _detect_error

logger = get_logger(__name__)

async def _smart_compress_loop_history(loop_history: list[dict], max_total_chars: int = 30000) -> list[dict]:
    """ツール結果の重要度に基づいた賢い圧縮（Claude Code準拠）"""
    if len(loop_history) <= 6:
        return loop_history[:-1]  # 最新3ターン以内ならそのまま返す（最後の要素は別途処理されるため除外）
        
    recent = loop_history[-6:-1]  # 直近3ターン（最新の入力除く）は完全保持
    older = loop_history[:-6]
    
    compressed = []
    for msg in older:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))
        
        if role == "assistant":
            # 生成コードは模倣防止のため保持
            compressed.append(msg)
        else:
            # ツール結果の重要度判定
            has_error = _detect_error(content) is not None or "【テスト失敗】" in content or "エラー" in content
            is_file_read = "ファイル読み込み成功" in content or "📄" in content
            
            if has_error:
                # エラーメッセージは圧縮しない（原因追究の文脈を失わないため）
                compressed.append(msg)
            elif is_file_read and len(content) <= 3000:
                # ファイル内容も3000文字以内なら保持
                compressed.append(msg)
            elif len(content) > 500:
                # それ以外のディレクトリ一覧や長すぎる実行結果は要約
                compressed.append({
                    "role": role,
                    "content": content[:200] + f"\n...[ツール結果 ({len(content)}文字) キャッシュ効率・重要度判定により圧縮]...\n" + content[-200:]
                })
            else:
                compressed.append(msg)
                
    return compressed + recent

