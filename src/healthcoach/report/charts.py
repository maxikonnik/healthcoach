"""Графики динамики показателей в SVG.

Своим кодом, а не библиотекой: график простой — полоса коридора, линия,
точки, — а зависимость ради него была бы тяжёлой. SVG вставляется прямо в
HTML и печатается без промежуточных файлов.
"""

from __future__ import annotations

import html
import math

from healthcoach.report.data import Series

PADDING_LEFT = 46
PADDING_RIGHT = 12
PADDING_TOP = 14
PADDING_BOTTOM = 26


class ChartError(Exception):
    """График построить нельзя."""


def _data_bounds(series: Series) -> tuple[float, float]:
    """Истинные границы диапазона — точки и коридор, без отступа геометрии.

    Это то, что печатается на оси: клиент должен увидеть настоящий минимум
    и максимум показателя, а не служебный запас места, который существует
    только затем, чтобы точки не липли к рамке.
    """
    values = [p.value for p in series.points]
    if series.target is not None:
        if series.target.low is not None:
            values.append(series.target.low)
        if series.target.high is not None:
            values.append(series.target.high)
    return min(values), max(values)


def _scale(series: Series) -> tuple[float, float]:
    """Нижняя и верхняя границы оси для геометрии — с отступом на разброс.

    Коридор включается в размах целиком: клиент должен видеть, куда
    показатель идёт относительно цели, а не только сами точки. Отступ нужен
    только геометрии — подписи оси печатаются по _data_bounds, без него.
    """
    low, high = _data_bounds(series)
    if low == high:
        # Все значения совпали и коридора нет — иначе делить не на что.
        spread = abs(low) * 0.1 or 1.0
        low, high = low - spread, high + spread

    margin = (high - low) * 0.1
    return low - margin, high + margin


def _label_decimals(span: float) -> int:
    """Сколько знаков после запятой нужно подписи оси при таком размахе.

    Размах меньше 10 требует одного знака, меньше 1 — двух, и так далее:
    иначе близкие значения (0.05 и 0.09) обе округлятся до одной и той же
    подписи, и подпись перестанет что-либо показывать.
    """
    if span <= 0:
        return 0
    return max(0, math.ceil(-math.log10(span)) + 1)


def _format_label(value: float, decimals: int) -> str:
    """Отформатировать подпись оси, не допуская врущего «-0»."""
    text = f"{value:.{decimals}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text


def chart_svg(series: Series, width: int = 520, height: int = 180) -> str:
    """Нарисовать динамику показателя."""
    if not series.has_dynamics:
        raise ChartError(
            f"{series.analyte_id}: по одной точке динамики нет — график не строится"
        )

    low, high = _scale(series)
    data_low, data_high = _data_bounds(series)
    decimals = _label_decimals(data_high - data_low)
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

    target = series.target
    if target is not None and (target.low is not None or target.high is not None):
        # Открытая сторона коридора клэмпится к краю поля — иначе клиент
        # видит пустое место без видимой цели там, где граница просто не
        # задана.
        top = y(target.high) if target.high is not None else PADDING_TOP
        bottom = y(target.low) if target.low is not None else PADDING_TOP + plot_h
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
    # Подпись печатается на той высоте, где её значение и нарисовано, а не
    # у края поля. У края она врала: между краями поля лежит размах с
    # запасом (_scale), а подписаны им границы данных (_data_bounds), и
    # клиент, читающий график линейкой между подписями, получал не то
    # число, которое стоит у точки. На настоящих данных ферритина —
    # точки 18 и 45, коридор 60–90 — точка с подписью «18» читалась по
    # оси как 24.
    parts.append(
        f'<text x="4" y="{y(data_high):.1f}" font-size="9" fill="#666">'
        f'{_format_label(data_high, decimals)}</text>'
    )
    parts.append(
        f'<text x="4" y="{y(data_low):.1f}" font-size="9" fill="#666">'
        f'{_format_label(data_low, decimals)}</text>'
    )
    parts.append(
        f'<text x="4" y="{height - 8}" font-size="9" fill="#666">'
        f'{html.escape(series.units)}</text>'
    )

    parts.append("</svg>")
    return "".join(parts)
