"""ファイルアップロード API ルーター"""
from fastapi import APIRouter, UploadFile, File, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    アップロードされたファイルからテキストを抽出する。
    今回はローカルLLMへのプロンプト埋め込み用として、テキスト抽出のみを行う。
    """
    try:
        content_bytes = await file.read()
        
        mime_type = file.content_type
        
        if mime_type and mime_type.startswith("image/"):
            import base64
            # 画像の場合はBase64エンコードして返す
            text = base64.b64encode(content_bytes).decode('utf-8')
        else:
            # テキストとしてデコードを試みる
            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    # 日本語Windows環境でありがちなShift-JIS
                    text = content_bytes.decode("shift_jis")
                except UnicodeDecodeError:
                    raise HTTPException(
                        status_code=400, 
                        detail="テキストファイルとして読み込めませんでした。現在はテキスト（UTF-8/Shift-JIS）と画像のみサポートしています。"
                    )

        return {
            "filename": file.filename,
            "content": text,
            "mime_type": mime_type,
            "size": len(content_bytes)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ファイルアップロードエラー: {e}")
        raise HTTPException(status_code=500, detail="ファイルの処理中にエラーが発生しました。")
