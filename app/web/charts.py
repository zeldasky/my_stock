"""자산추이 SVG 차트 생성.

차트 라이브러리를 쓰지 않는 이유:
  - CDN 없이 오프라인에서도 그려져야 한다 (집 PC 구동)
  - 배포 시 정적 자산 의존이 없다
  - 이 정도 선 그래프는 좌표 계산이 전부다
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

WIDTH = 1000
HEIGHT = 300
PAD_LEFT = 8
PAD_RIGHT = 8
PAD_TOP = 16
PAD_BOTTOM = 28


def format_krw_short(value: Decimal | float) -> str:
    """1억 이상은 억, 1만 이상은 만 단위로 줄여 쓴다."""
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 100_000_000:
        return f"{sign}{number / 100_000_000:,.2f}억"
    if number >= 10_000:
        return f"{sign}{number / 10_000:,.0f}만"
    return f"{sign}{number:,.0f}"


@dataclass
class ChartPoint:
    x: float
    y: float
    date: dt.date
    value: float
    cost: float
    return_pct: float


@dataclass
class ChartData:
    width: int = WIDTH
    height: int = HEIGHT
    line: str = ""
    area: str = ""
    cost_line: str = ""
    points: list[ChartPoint] = field(default_factory=list)
    y_ticks: list[tuple[float, str]] = field(default_factory=list)
    x_ticks: list[tuple[float, str]] = field(default_factory=list)
    is_empty: bool = True

    @property
    def points_json(self) -> list[dict]:
        """툴팁용. 템플릿에서 |tojson 으로 내려보낸다."""
        return [
            {
                "x": p.x,
                "y": p.y,
                "d": p.date.strftime("%Y.%m.%d"),
                "v": format_krw_short(p.value),
                "c": format_krw_short(p.cost),
                "r": f"{p.return_pct:+.1f}%",
            }
            for p in self.points
        ]


def build_chart(history: list) -> ChartData:
    """DailyPoint 목록 -> SVG 좌표."""
    if len(history) < 2:
        return ChartData()

    values = [float(p.market_value_krw) for p in history]
    costs = [float(p.cost_krw) for p in history]

    low = min(min(values), min(costs))
    high = max(max(values), max(costs))
    if high == low:  # 평평한 구간이면 강제로 폭을 준다
        high = low + 1

    span = high - low
    low -= span * 0.08
    high += span * 0.08
    span = high - low

    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    last_index = len(history) - 1

    def to_x(i: int) -> float:
        return PAD_LEFT + plot_w * i / last_index

    def to_y(v: float) -> float:
        return PAD_TOP + plot_h * (1 - (v - low) / span)

    points: list[ChartPoint] = []
    for i, point in enumerate(history):
        points.append(
            ChartPoint(
                x=round(to_x(i), 2),
                y=round(to_y(values[i]), 2),
                date=point.date,
                value=values[i],
                cost=costs[i],
                return_pct=float(point.return_pct),
            )
        )

    line = "M" + " L".join(f"{p.x},{p.y}" for p in points)
    baseline = HEIGHT - PAD_BOTTOM
    area = f"{line} L{points[-1].x},{baseline} L{points[0].x},{baseline} Z"
    cost_line = "M" + " L".join(
        f"{round(to_x(i), 2)},{round(to_y(c), 2)}" for i, c in enumerate(costs)
    )

    y_ticks = []
    for step in range(5):
        value = low + span * step / 4
        y_ticks.append((round(to_y(value), 2), format_krw_short(value)))

    x_ticks = []
    tick_count = min(6, len(history))
    for step in range(tick_count):
        index = round(last_index * step / (tick_count - 1)) if tick_count > 1 else 0
        day = history[index].date
        x_ticks.append((round(to_x(index), 2), day.strftime("%y.%m")))

    return ChartData(
        line=line,
        area=area,
        cost_line=cost_line,
        points=points,
        y_ticks=y_ticks,
        x_ticks=x_ticks,
        is_empty=False,
    )
