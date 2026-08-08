"""
fact_filter.py (Wrapper)

このファイルは後方互換性のためのラッパーです。
実際のフィルタリングロジックはドメイン別に分割され、
app.core.fact_filters パッケージ配下に移動しました。
"""
from app.core.fact_filters import *
