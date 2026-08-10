"""Графики динамики показателей в SVG.

Своим кодом, а не библиотекой: график простой — полоса коридора, линия,
точки, — а зависимость ради него была бы тяжёлой. SVG вставляется прямо в
HTML и печатается без промежуточных файлов.
"""

from __future__ import annotations

import html

from healthcoach.report.data import Series

PADDING_LEFT = 46
PADDING_RIGHT = 12
PADDING_TOP = 14
PADDING_BOTTOM = 26


class ChartError(Exception):
    """График построить нельзя."""


def _scale(series: Series) -> tuple[float, float]:
    """Нижняя и верхняя границы оси значений.

    Коридор включается в размах целиком: клиент должен видеть, куда
    показатель идёт относительно цели, а не только сами точки.
    """
    values = [p.value for p in series.points]
    if series.target is not None:
        if series.target.low is not None:
            values.append(series.target.low)
        if series.target.high is not None:
            values.append(series.target.high)

    low, high = min(values), max(values)
    if low == high:
        # Все значения совпали и коридора нет — иначе делить не на что.
        spread = abs(low) * 0.1 or 1.0
        low, high = low - spread, high + spread

    margin = (high - low) * 0.1
    return low - margin, high + margin


def chart_svg(series: Series, width: int = 520, height: int = 180) -> str:
    """Нарисовать динамику показателя."""
    if not series.has_dynamics:
        raise ChartError(
            f"{series.analyte_id}: по одной точке динамики нет — график не строится"
        )

    low, high = _scale(series)
    plot_w = width - PADDING_LEFT - PADDING_RIGHT
    plot_h = height - PADDING_TOP - PADDING_BOTTOM

    def x(i: int) -> float:
        return PADDING_LEFT + plot_w * i / (len(series.points) - 1)

    def y(value: float) -> float:
        return PADDING_TOP + plot_h * (1 - (value - low) / (high - low))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        f'<title>{html.escape(series.title)}</title>',
    ]

    if series.target is not None and series.target.low is not None and series.target.high is not None:
        top, bottom = y(series.target.high), y(series.target.low)
        parts.append(
            f'<rect x="{PADDING_LEFT}" y="{top:.1f}" width="{plot_w}" '
            f'height="{bottom - top:.1f}" fill="#e8f2e8"/>'
        )

    line = " ".join(f"{x(i):.1f},{y(p.value):.1f}" for i, p in enumerate(series.points))
    parts.append(f'<polyline points="{line}" fill="none" stroke="#4a7c59" stroke-width="2"/>')

    for i, point in enumerate(series.points):
        px, py = x(i), y(point.value)
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#4a7c59"/>')
        parts.append(
            f'<text x="{px:.1f}" y="{py - 9:.1f}" font-size="10" '
            f'text-anchor="middle" fill="#333">{point.value:g}</text>'
        )

    first, last = series.points[0], series.points[-1]
    parts.append(
        f'<text x="{PADDING_LEFT}" y="{height - 8}" font-size="9" fill="#666">'
        f'{first.taken_on.strftime("%m.%Y")}</text>'
    )
    parts.append(
        f'<text x="{width - PADDING_RIGHT}" y="{height - 8}" font-size="9" '
        f'text-anchor="end" fill="#666">{last.taken_on.strftime("%m.%Y")}</text>'
    )
    parts.append(
        f'<text x="4" y="{PADDING_TOP + 4}" font-size="9" fill="#666">{high:.0f}</text>'
    )
    parts.append(
        f'<text x="4" y="{height - PADDING_BOTTOM}" font-size="9" fill="#666">{low:.0f}</text>'
    )
    parts.append(
        f'<text x="4" y="{height - 8}" font-size="9" fill="#666">'
        f'{html.escape(series.units)}</text>'
    )

    parts.append("</svg>")
    return "".join(parts)
