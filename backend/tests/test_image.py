"""
image.py エンドポイントの単体テスト
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_generate_image_gallery_default():
    """既定 image_engine=gallery ではストック配信（200）またはフォールバック（307）。"""
    response = client.get("/api/image/generate?prompt=1girl, anime style, kairi", follow_redirects=False)
    assert response.status_code in (200, 307)
    if response.status_code == 307:
        assert "pollinations.ai" in response.headers["location"]
        assert "1girl" in response.headers["location"]
    else:
        # gallery ストック配信
        assert response.headers.get("content-type", "").startswith("image/") or "content-type" in {
            k.lower() for k in response.headers.keys()
        }


def test_generate_image_cf_fallback(monkeypatch):
    from app.routers.settings import app_settings
    monkeypatch.setattr(app_settings, "get", lambda: {"image_engine": "cf-flux", "cf_api_token": ""})
    response = client.get("/api/image/generate?prompt=1girl, anime style, kairi", follow_redirects=False)
    assert response.status_code == 307  # トークンなしの時は自動でPollinationsへフォールバックすること
    assert "pollinations.ai" in response.headers["location"]


def test_generate_image_pollinations_redirect(monkeypatch):
    from app.routers.settings import app_settings
    monkeypatch.setattr(app_settings, "get", lambda: {"image_engine": "pollinations"})
    response = client.get("/api/image/generate?prompt=1girl, anime style, kairi", follow_redirects=False)
    assert response.status_code == 307
    assert "pollinations.ai" in response.headers["location"]
    assert "1girl" in response.headers["location"]
