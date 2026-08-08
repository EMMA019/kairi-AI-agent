"""ローカルストック画像のテーママッチ・決定的選択の単体テスト。"""
from pathlib import Path

from app.routers.image import (
    _detect_theme,
    _select_stock_image,
    _theme_of_file,
)


def _fake_stock() -> list[Path]:
    return [
        Path("kairi_school_1.png"),
        Path("kairi_school_2.png"),
        Path("kairi_beach_1.png"),
        Path("kairi_room_1.png"),
        Path("kairi_casual_1.png"),
        Path("kairi_happening_1.png"),
    ]


def test_detect_theme_keywords():
    assert _detect_theme("school uniform classroom") == "school"
    assert _detect_theme("bikini beach ocean") == "beach"
    assert _detect_theme("bedroom selfie indoors") == "room"
    assert _detect_theme("cafe street casual") == "casual"
    assert _detect_theme("just smile") is None


def test_theme_of_file():
    assert _theme_of_file(Path("kairi_school_1785020315_2.png")) == "school"
    assert _theme_of_file(Path("kairi_happening_x.png")) == "happening"
    # WebP 圧縮後も stem ベースでテーマ判定できること
    assert _theme_of_file(Path("kairi_beach_123.webp")) == "beach"
    assert _theme_of_file(Path("kairi_room_selfie_1.webp")) == "room"


def test_select_matches_theme_and_is_deterministic():
    imgs = _fake_stock()
    a = _select_stock_image("school classroom uniform", imgs)
    b = _select_stock_image("school classroom uniform", imgs)
    assert a == b
    assert _theme_of_file(a) == "school"


def test_happening_excluded_unless_requested():
    imgs = _fake_stock()
    for _ in range(20):
        # 同じプロンプトだと決定的なので、別プロンプトを少し変えて複数試す
        pass
    picks = [
        _select_stock_image(f"cafe street casual look {i}", imgs)
        for i in range(12)
    ]
    assert all(_theme_of_file(p) != "happening" for p in picks)

    h = _select_stock_image("happening bikini classroom accident", imgs)
    assert _theme_of_file(h) == "happening"


def test_no_theme_excludes_happening():
    imgs = _fake_stock()
    picks = [_select_stock_image(f"cute smile pose {i}", imgs) for i in range(10)]
    assert all(_theme_of_file(p) != "happening" for p in picks)
