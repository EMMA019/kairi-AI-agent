import httpx
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def geocode(place: str) -> tuple[float, float] | None:
    """地名→座標変換（OpenStreetMap Nominatim）"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": place, "format": "json", "limit": 1}
    headers = {"User-Agent": "Antigravity/2.1"}
    
    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(url, params=params, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
            
        if not data:
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.error(f"Geocodingエラー ({place}): {e}")
        return None

async def get_weather(place: str) -> dict | None:
    """Open-Meteo公式APIから天気情報を取得"""
    coords = await geocode(place)
    if not coords:
        return None
    lat, lon = coords

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "current_weather": True,
        "timezone":        "Asia/Tokyo",
    }
    
    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()

        cw = data.get("current_weather", {})
        
        # WMOコード→日本語天気の簡易変換
        wmo_map = {
            0: "晴れ", 1: "ほぼ晴れ", 2: "一部曇り", 3: "曇り",
            45: "霧", 48: "霧",
            51: "小雨", 53: "雨", 55: "強雨",
            61: "小雨", 63: "雨", 65: "強雨",
            71: "小雪", 73: "雪", 75: "大雪",
            80: "にわか雨", 81: "雨", 82: "強雨",
            95: "雷雨", 96: "雷雨", 99: "雷雨",
        }
        weather_code = cw.get("weathercode", -1)
        weather_desc = wmo_map.get(weather_code, "不明")

        return {
            "place":       place,
            "temperature": cw.get("temperature"),
            "windspeed":   cw.get("windspeed"),
            "weather":     weather_desc,
            "source":      "open-meteo",
        }
    except Exception as e:
        logger.error(f"天気APIエラー ({place}): {e}")
        return None

def format_weather_for_prompt(weather: dict) -> str:
    """天気情報をプロンプト注入用テキストに整形"""
    if not weather:
        return "（天気情報取得失敗）"
    return (
        f"{weather['place']}の現在の天気: {weather['weather']}、"
        f"気温 {weather['temperature']}℃、"
        f"風速 {weather['windspeed']}km/h"
    )
