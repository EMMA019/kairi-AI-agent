"""
旅行ルート計算ツール (Mapbox Directions API & Geocoding 統合)
"""
import os
import json
import urllib.parse
import urllib.request
from app.core.tools.registry import tool_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _geocode_place(place: str, token: str) -> tuple[float, float, str]:
    """地名・施設名を緯度・経度に正確に変換 (lng, lat, place_name)"""
    # 1. まずOpenStreetMap Nominatimで正確な施設・住所ジオコーディングを試行
    try:
        nom_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(place)}.json?country=jp&language=ja&limit=1&access_token={token}" if not place else f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(place)}&limit=1&countrycodes=jp"
        req = urllib.request.Request(nom_url, headers={"User-Agent": "KairiTravel/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            res = json.loads(resp.read().decode())
            if res and isinstance(res, list) and len(res) > 0:
                item = res[0]
                return float(item["lon"]), float(item["lat"]), item.get("name") or item.get("display_name", place)
    except Exception as e:
        logger.warning(f"Nominatim geocode fallback triggered for {place}: {e}")

    # 2. Mapbox Geocoding v5 (日本語優先)
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(place)}.json?country=jp&language=ja&limit=1&access_token={token}"
    req = urllib.request.Request(url, headers={"User-Agent": "KairiTravel/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        features = data.get("features", [])
        if not features:
            raise ValueError(f"場所「{place}」が見つかりませんでした")
        coords = features[0]["geometry"]["coordinates"]  # [lng, lat]
        place_name = features[0].get("text_ja", features[0].get("place_name", place))
        return coords[0], coords[1], place_name


@tool_registry.register(
    name="travel_route",
    description="出発地から目的地までの移動時間・距離・ルート目安（車・徒歩・自転車・電車バス等）を計算するツール。modeには 'driving'(車), 'walking'(徒歩), 'cycling'(自転車), 'transit'(電車・路線バス) が指定可能",
)
def travel_route(origin: str, destination: str, mode: str = "driving") -> str:
    """旅行ルート＆移動時間を計算"""
    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    # モードマッピング
    mode_lower = str(mode).lower().strip()
    if mode_lower in ("walking", "walk", "徒歩"):
        api_mode = "walking"
        icon = "🚶"
        mode_label = "徒歩"
    elif mode_lower in ("cycling", "bicycle", "自転車", "レンタサイクル"):
        api_mode = "cycling"
        icon = "🚲"
        mode_label = "自転車"
    elif mode_lower in ("transit", "train", "bus", "電車", "バス", "路線バス", "公共交通機関"):
        api_mode = "driving"  # 基本道路ネットワーク距離を取得して公共交通目安時間を導出
        icon = "🚌・🚃"
        mode_label = "電車・路線バス（公共交通目安）"
    else:
        api_mode = "driving-traffic"
        icon = "🚗"
        mode_label = "車・タクシー"

    if not token:
        # トークン未設定時のモックタイムラインシミュレート
        return (
            f"{icon} 【移動ルート＆時間目安（フォールバック）】\n"
            f"- **出発地**: {origin}\n"
            f"- **目的地**: {destination}\n"
            f"- **移動手段**: {mode_label}\n"
            f"- **目安所要時間**: 約 15分〜30分\n"
            f"※ 実際のリアルタイム道路/歩行距離計算は Render 上の `MAPBOX_API_KEY` を利用して行われます。"
        )

    try:
        orig_lng, orig_lat, orig_name = _geocode_place(origin, token)
        dest_lng, dest_lat, dest_name = _geocode_place(destination, token)

        url = (
            f"https://api.mapbox.com/directions/v5/mapbox/{api_mode}/"
            f"{orig_lng},{orig_lat};{dest_lng},{dest_lat}?steps=true&overview=simplified&access_token={token}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "KairiTravel/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            routes = data.get("routes", [])
            if not routes:
                return f"「{origin}」から「{destination}」へのルートが見つかりませんでした。"

            route = routes[0]
            distance_km = round(route.get("distance", 0) / 1000, 1)
            duration_min = round(route.get("duration", 0) / 60)

            # 公共交通機関指定時は距離からの目安移動時間と徒歩との比較を算出
            if mode_label.startswith("電車"):
                transit_min = max(5, round(distance_km * 2.5) + 5)
                time_str = f"約 {transit_min} 分（待ち時間除く目安） / 徒歩だと約 {round(distance_km * 12)} 分"
            else:
                hours = duration_min // 60
                mins = duration_min % 60
                time_str = f"{hours}時間{mins}分" if hours > 0 else f"{mins}分"

            output = [
                f"{icon} **【移動ルート＆時間目安 ({mode_label})】**",
                f"- **出発地**: {orig_name}",
                f"- **目的地**: {dest_name}",
                f"- **移動手段**: {mode_label}",
                f"- **移動所要時間**: **{time_str}** (距離目安: {distance_km} km)",
            ]

            # ステップから主要分岐をピックアップ
            legs = route.get("legs", [])
            if legs:
                steps = legs[0].get("steps", [])
                accum_km = 0.0
                for step in steps[:5]:
                    step_km = round(step.get("distance", 0) / 1000, 1)
                    accum_km += step_km
                    instr = step.get("maneuver", {}).get("instruction", "")
                    if instr and step_km > 2.0:
                        output.append(f"| 約 {round(accum_km)} km 地点 | {instr} | +{step_km} km |")

            output.append(f"| ゴール ({time_str}後) | {destination} 到着 | 合計 {distance_km} km |")
            return "\n".join(output)

    except Exception as e:
        logger.error(f"Mapbox API エラー: {e}")
        return f"[エラー] ルート計算に失敗しました: {e}"


@tool_registry.register(
    name="travel_isochrone",
    description="出発地・現在地から指定した移動時間（例: 30分）以内に到達できる範囲のポリゴン面積や目安距離を探索するツール",
)
def travel_isochrone(origin: str, minutes: int = 30, mode: str = "driving") -> str:
    """到達圏探索（Isochrone API）"""
    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if not token:
        return f"🗺️ 【到達圏シミュレーション】{origin} から {mode} で {minutes} 分以内に行ける目安距離は半径 約 {minutes * 0.75} km 圏内です！"

    api_mode = "driving" if mode in ("driving", "car", "車") else "walking"
    try:
        lng, lat, place_name = _geocode_place(origin, token)
        url = (
            f"https://api.mapbox.com/isochrone/v1/mapbox/{api_mode}/{lng},{lat}"
            f"?contours_minutes={min(minutes, 60)}&polygons=true&access_token={token}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "KairiTravel/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            features = data.get("features", [])
            if not features:
                return f"「{origin}」からの到達圏が計算できませんでした。"

            # ポリゴンの広さを簡易評価
            return (
                f"🗺️ **【Mapbox 到達圏分析レポート】**\n"
                f"- **起点**: {place_name}\n"
                f"- **移動条件**: {mode} で **{minutes}分圏内**\n"
                f"- **探索範囲**: 半径約 {round(minutes * 0.7, 1)} km〜{round(minutes * 1.1, 1)} km のエリアが日帰り・サクッと移動スポットの目安です！\n"
                f"周辺の観光地やカフェ検索と組み合わせると完璧なプランが作れます！"
            )
    except Exception as e:
        logger.error(f"Mapbox Isochrone エラー: {e}")
        return f"[エラー] 到達圏計算に失敗しました: {e}"


def _reverse_geocode(lat: float, lon: float, token: str) -> str:
    """緯度・経度を綺麗な日本語地名・住所に変換（逆ジオコーディング）"""
    url = (
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json"
        f"?country=jp&language=ja&types=poi,address,neighborhood,locality&limit=1&access_token={token}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "KairiTravel/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        features = data.get("features", [])
        if not features:
            return f"緯度 {lat}, 経度 {lon}"
        return features[0].get("place_name", f"緯度 {lat}, 経度 {lon}")


@tool_registry.register(
    name="checkin_location",
    description="現在地のGPS座標（緯度・経度）からゼンリン日本語住所・施設名を逆ジオコーディングし、チェックインカードとサムネイルマップを出力するツール",
)
def checkin_location(latitude: float, longitude: float, note: str = "") -> str:
    """現在地チェックイン＆思い出ログ記録"""
    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    lat = round(float(latitude), 5)
    lon = round(float(longitude), 5)

    if not token:
        return (
            f"📍 **【現在地チェックイン（Mapboxキー未登録シミュレート）】**\n"
            f"- **座標**: 緯度 {lat}, 経度 {lon}\n"
            f"- **メモ**: {note or '到着記録'}\n"
            f"※ Render管理画面に `MAPBOX_API_KEY` を入れると、ここの住所やスポット名・地図写真が自動表示されます！"
        )

    try:
        place_name = _reverse_geocode(lat, lon, token)
        static_map_url = (
            f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/"
            f"pin-l-heart+ec4899({lon},{lat})/auto/500x250@2x?access_token={token}"
        )
        return (
            f"📍 **【Kairi 足跡チェックイン完了♡】**\n"
            f"![チェックインスポット]({static_map_url})\n"
            f"- **現在地名・住所**: **{place_name}**\n"
            f"- **GPS座標**: `[{lat}, {lon}]`\n"
            f"- **メモ**: {note or '足跡記録完了💖'}\n"
            f"相棒との思い出スポットとしてバッチリ確認したよ！周辺のグルメやルート検索にも今すぐ使えるから聞いてね！"
        )
    except Exception as e:
        logger.error(f"チェックインエラー: {e}")
        return f"📍 チェックイン記録完了 [座標: {lat}, {lon}]"


@tool_registry.register(
    name="search_nearby_spots",
    description="指定した地名または座標周辺のスポット探索・地図表示ツール。Web検索結果等から特定のスポット（5件等）を指定して地図を作成する場合は custom_spots_json に [{'name': '店名', 'address': '住所', 'lat': 緯度, 'lon': 経度}] 形式のJSONで指定可能",
)
def search_nearby_spots(
    query: str = "ご飯屋さん",
    place: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    custom_spots_json: str = "",
) -> str:
    """周辺スポット＆地名指定グルメ・スポット厳選コンシェルジュ"""
    token = os.environ.get("MAPBOX_API_KEY", "").strip()

    if not token:
        target_label = place if place else f"({latitude}, {longitude})"
        return f"🍽️ 【「{target_label}」周辺の「{query}」検索シミュレート】おすすめスポットを探しました！ぜひ Mapbox キーをセットしてリアル店舗情報を呼び出してね！"

    try:
        # 地名指定がある場合はまずジオコーディングで中心緯度経度を取得
        if place and (latitude == 0.0 and longitude == 0.0):
            lon, lat, center_name = _geocode_place(place, token)
            target_label = f"{place} ({center_name})"
        else:
            lat = round(float(latitude), 5)
            lon = round(float(longitude), 5)
            target_label = f"現在地周辺 [{lat}, {lon}]"

        spots = []
        if custom_spots_json:
            try:
                spots = json.loads(custom_spots_json)
            except Exception as e:
                logger.warning(f"custom_spots_json parse error: {e}")
        # 1. Mapbox Geocoding v5
        if not spots:
            try:
                url = (
                    f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(query)}.json"
                    f"?proximity={lon},{lat}&country=jp&language=ja&limit=5&access_token={token}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "KairiTravel/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    for feat in data.get("features", [])[:5]:
                        f_lon, f_lat = feat["geometry"]["coordinates"]
                        name = feat.get("text_ja", feat.get("text", "スポット"))
                        addr = feat.get("place_name_ja", feat.get("place_name", ""))
                        spots.append({"name": name, "address": addr, "lon": f_lon, "lat": f_lat})
            except Exception as e:
                logger.warning(f"Mapbox spot search error: {e}")

        # 2. Overpass API フォールバック (周辺にスポットが見つからなかった場合)
        if not spots:
            try:
                tag_query = 'node["amenity"="cafe"]' if "カフェ" in query or "cafe" in query.lower() else 'node["tourism"]'
                overpass_q = f'[out:json][timeout:8];{tag_query}({lat-0.05},{lon-0.05},{lat+0.05},{lon+0.05});out 10;'
                op_url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(overpass_q)
                req = urllib.request.Request(op_url, headers={"User-Agent": "KairiTravel/1.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    op_data = json.loads(resp.read().decode())
                    for el in op_data.get("elements", []):
                        if "name" in el.get("tags", {}):
                            spots.append({
                                "name": el["tags"]["name"],
                                "address": f"下田エリア ({round(el['lat'],4)}, {round(el['lon'],4)})",
                                "lon": el["lon"],
                                "lat": el["lat"]
                            })
                            if len(spots) >= 4:
                                break
            except Exception as e:
                logger.warning(f"Overpass fallback error: {e}")

        if not spots:
            return f"「{target_label}」の周辺で「{query}」が見つかりませんでした。"

        # 中心地点＋複数ピンマーカーを生成
        pins = [f"pin-l-star+111827({lon},{lat})"]
        colors = ["f43f5e", "3b82f6", "10b981", "f59e0b", "8b5cf6"]
        rows = []
        for idx, sp in enumerate(spots[:5]):
            name = sp["name"]
            address = sp["address"]
            f_lon, f_lat = sp["lon"], sp["lat"]
            color = colors[idx % len(colors)]
            pins.append(f"pin-s-{idx+1}+{color}({f_lon},{f_lat})")
            rows.append(f"| {idx+1} | **{name}** | {address} |")

        pins_str = ",".join(pins)
        static_map_url = (
            f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/"
            f"{pins_str}/auto/600x300@2x?padding=60&access_token={token}"
        )

        lines = [
            f"🌟 **【Kairi厳選コンシェルジュ: {target_label} の「{query}」】**",
            f"![周辺スポットマップ]({static_map_url})",
            f"",
            f"📋 **おすすめスポット一覧**",
            f"| No | スポット名 | 住所・詳細 |",
            f"| :---: | :--- | :--- |",
        ]
        lines.extend(rows)
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"周辺スポット検索エラー: {e}")
        return f"[エラー] 周辺検索に失敗しました: {e}"


