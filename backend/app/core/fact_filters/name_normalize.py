"""
固有名の表記ゆれ正規化・ゆるい一致。

Murphy / O. Murphy / マーフィー などを同一視し、
正しい出典付き主張を誤って不確実化しないための軽量ヒューリスティック。
完全な日英固有名辞書は持たない。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# カタカナ→ローマ字（基本＋よく使う拗音・外来語音）
_KANA_ROMA: dict[str, str] = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "o", "ン": "n",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo", "ッ": "t",
    "ー": "-",
}

_DIGRAPHS: list[tuple[str, str]] = [
    ("キャ", "kya"), ("キュ", "kyu"), ("キョ", "kyo"),
    ("ギャ", "gya"), ("ギュ", "gyu"), ("ギョ", "gyo"),
    ("シャ", "sha"), ("シュ", "shu"), ("ショ", "sho"),
    ("ジャ", "ja"), ("ジュ", "ju"), ("ジョ", "jo"),
    ("チャ", "cha"), ("チュ", "chu"), ("チョ", "cho"),
    ("ニャ", "nya"), ("ニュ", "nyu"), ("ニョ", "nyo"),
    ("ヒャ", "hya"), ("ヒュ", "hyu"), ("ヒョ", "hyo"),
    ("ビャ", "bya"), ("ビュ", "byu"), ("ビョ", "byo"),
    ("ピャ", "pya"), ("ピュ", "pyu"), ("ピョ", "pyo"),
    ("ミャ", "mya"), ("ミュ", "myu"), ("ミョ", "myo"),
    ("リャ", "rya"), ("リュ", "ryu"), ("リョ", "ryo"),
    ("ファ", "fa"), ("フィ", "fi"), ("フェ", "fe"), ("フォ", "fo"),
    ("ティ", "ti"), ("ディ", "di"), ("トゥ", "tu"), ("ドゥ", "du"),
    ("ウェ", "we"), ("ウィ", "wi"), ("ウォ", "wo"),
    ("ヴァ", "va"), ("ヴィ", "vi"), ("ヴェ", "ve"), ("ヴォ", "vo"),
    ("クァ", "qa"), ("クィ", "qi"), ("クォ", "qo"),
]

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
_KATA_TOKEN_RE = re.compile(r"[ァ-ヶー]{3,}")

# 一般語カタカナ（固有名候補から除外）
_KATA_STOP = {
    "アルゴリズム", "データ", "システム", "コンピュータ", "コンピューター",
    "インターネット", "サーバー", "クライアント", "プログラム", "アプリケーション",
    "ニュース", "マーケット", "ポートフォリオ", "セクター", "インフレ",
    "オッズ", "配当", "レース", "タイトル", "シリーズ", "シーズン",
}


def normalize_alnum(text: str) -> str:
    """小文字化・アクセント除去・区切り記号除去。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[\s\.・･\-_'’`]+", "", s)
    return s


def phonetic_fold_latin(text: str) -> str:
    """英語側のゆるい音韻折りたたみ（ph→f 等）。"""
    s = normalize_alnum(text)
    s = s.replace("ph", "f").replace("ck", "k").replace("ll", "l")
    s = s.replace("ough", "o").replace("igh", "i")
    # y を母音寄りに
    s = s.replace("y", "i")
    return s


def katakana_to_romaji(text: str) -> str:
    """カタカナを簡易ローマ字へ。長音は直前母音の延長として扱う。"""
    if not text:
        return ""
    s = text
    for kana, roma in _DIGRAPHS:
        s = s.replace(kana, roma)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _KANA_ROMA:
            roma = _KANA_ROMA[ch]
            if roma == "-":
                # 長音: 直前の母音を伸ばす（記号は出さない）
                if out:
                    prev = out[-1]
                    for v in ("a", "i", "u", "e", "o"):
                        if prev.endswith(v):
                            out[-1] = prev + v
                            break
                i += 1
                continue
            out.append(roma)
            i += 1
            continue
        # すでにローマ字断片
        if "a" <= ch.lower() <= "z":
            out.append(ch.lower())
        i += 1
    return "".join(out)


def extract_latin_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _LATIN_TOKEN_RE.finditer(text or "")]


def extract_katakana_tokens(text: str) -> list[str]:
    tokens = []
    for m in _KATA_TOKEN_RE.finditer(text or ""):
        t = m.group(0).strip("ー")
        if len(t) >= 3 and t not in _KATA_STOP:
            tokens.append(m.group(0))
    return tokens


def names_likely_match(a: str, b: str) -> bool:
    """2つの固有名表記が同一人物・同一呼称っぽいか。"""
    if not a or not b:
        return False
    if a == b or a.lower() == b.lower():
        return True
    na, nb = normalize_alnum(a), normalize_alnum(b)
    # 部分一致は「短い方が十分長く、長い方の大部分を占める」ときだけ
    if na and nb and min(len(na), len(nb)) >= 4:
        shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
        if shorter in longer and len(shorter) / len(longer) >= 0.72:
            return True

    a_is_kata = bool(re.search(r"[ァ-ヶ]", a))
    b_is_kata = bool(re.search(r"[ァ-ヶ]", b))

    roma_a = katakana_to_romaji(a) if a_is_kata else phonetic_fold_latin(a)
    roma_b = katakana_to_romaji(b) if b_is_kata else phonetic_fold_latin(b)
    if not roma_a or not roma_b:
        return False
    # 短すぎるトークン（Man 等）との偶然一致を防ぐ
    if min(len(roma_a), len(roma_b)) < 4:
        return False
    len_ratio = min(len(roma_a), len(roma_b)) / max(len(roma_a), len(roma_b))
    if roma_a in roma_b or roma_b in roma_a:
        if len_ratio >= 0.72:
            return True
    ratio = SequenceMatcher(None, roma_a, roma_b).ratio()
    # 類似度が高く、かつ長さが大きく違わないこと（Zebra ≉ ゼブラトン）
    if ratio >= 0.55 and len_ratio >= 0.72:
        return True
    # 先頭一致＋長さ近傍の救済は厳しめ
    if (
        roma_a[0] == roma_b[0]
        and abs(len(roma_a) - len(roma_b)) <= 2
        and ratio >= 0.5
        and len_ratio >= 0.75
        and min(len(roma_a), len(roma_b)) >= 5
    ):
        return True
    return False


def source_mentions_name(name: str, source_text: str) -> bool:
    """ソースが当該固有名（表記ゆれ含む）に言及しているか。"""
    if not name or not source_text:
        return False
    if name in source_text or name.lower() in source_text.lower():
        return True
    nn = normalize_alnum(name)
    sn = normalize_alnum(source_text)
    if nn and len(nn) >= 3 and nn in sn:
        return True

    # ソース側トークン（短すぎる一般語・全小文字は除外）
    latin_toks = [
        t for t in extract_latin_tokens(source_text)
        if len(t) >= 3 and (t[0].isupper() or len(t) >= 5)
    ]
    candidates = latin_toks + extract_katakana_tokens(source_text)
    # 複合名のパーツ（O. Murphy → Murphy）
    for tok in list(candidates):
        for part in re.split(r"[\s\.・\-]+", tok):
            if len(part) >= 3 and (part[0].isupper() or len(part) >= 4):
                candidates.append(part)
    # 隣接する2 CapWord のみ連結（全連結は ZebraStakes≈ゼブラトン の誤一致を招く）
    caps = [t for t in latin_toks if t[0].isupper()]
    for i in range(len(caps) - 1):
        pair = normalize_alnum(caps[i]) + normalize_alnum(caps[i + 1])
        if len(pair) >= 6:
            # ペアは包含一致のみ（SequenceMatcher は使わない）
            roma = katakana_to_romaji(name) if re.search(r"[ァ-ヶ]", name) else phonetic_fold_latin(name)
            if roma and len(roma) >= 5 and (
                (roma in pair or pair in roma)
                and min(len(roma), len(pair)) / max(len(roma), len(pair)) >= 0.8
            ):
                return True

    for cand in candidates:
        if names_likely_match(name, cand):
            return True

    # カタカナ名 ↔ ソース全体の音韻折りたたみ
    if re.search(r"[ァ-ヶ]", name):
        roma = katakana_to_romaji(name)
        folded_src = phonetic_fold_latin(source_text)
        if roma and len(roma) >= 4 and (roma in folded_src or roma in sn):
            return True
        for tok in extract_latin_tokens(source_text):
            if names_likely_match(name, tok):
                return True
    return False
