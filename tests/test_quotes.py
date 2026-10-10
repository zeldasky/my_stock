"""시세 캐시 구간 테스트 — 지난 날짜를 조회해도 캐시에 빈 구간이 생기지 않아야 한다."""

from __future__ import annotations

import datetime as dt

from app.core.quotes import _fetch_window

D = dt.date
CACHED = (D(2025, 7, 3), D(2026, 10, 9))


def test_empty_cache_fetches_requested_range():
    assert _fetch_window(None, None, D(2025, 1, 1), D(2025, 1, 10)) == (
        D(2025, 1, 1),
        D(2025, 1, 10),
    )


def test_front_fill_reaches_cached_start_so_no_gap_is_left():
    # 2025-01 을 조회하면 2025-07-03 (캐시 첫날) 까지 이어 받는다.
    # 1월 열흘치만 받으면 2~6월이 비고, 3월 조회 때 1월 종가가 3월 종가로 쓰인다.
    assert _fetch_window(*CACHED, D(2024, 12, 22), D(2025, 1, 1)) == (
        D(2024, 12, 22),
        D(2025, 7, 3),
    )


def test_front_fill_overlapping_cache_keeps_requested_end():
    assert _fetch_window(*CACHED, D(2025, 6, 1), D(2025, 8, 1)) == (
        D(2025, 6, 1),
        D(2025, 8, 1),
    )


def test_range_wider_than_cache_fetches_everything():
    assert _fetch_window(*CACHED, D(2025, 1, 1), D(2026, 10, 10)) == (
        D(2025, 1, 1),
        D(2026, 10, 10),
    )


def test_past_range_inside_cache_needs_no_fetch():
    assert _fetch_window(*CACHED, D(2025, 9, 1), D(2025, 9, 11)) is None


def test_tail_fetch_starts_at_cached_end():
    # 마지막 날은 장중 값일 수 있어 다시 받는다
    assert _fetch_window(*CACHED, D(2026, 10, 1), D(2026, 10, 10)) == (
        D(2026, 10, 9),
        D(2026, 10, 10),
    )
    assert _fetch_window(*CACHED, D(2026, 10, 1), D(2026, 10, 9)) == (
        D(2026, 10, 9),
        D(2026, 10, 9),
    )
