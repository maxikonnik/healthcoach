"""Геометрия шкалы находки: проценты по горизонтальной оси.

Единственное место, где для экрана находок считается настоящая арифметика.
Всё, что отдаёт `scale_for`, — уже готовые целые проценты; шаблону
(Task 3) остаётся только их разложить, а не досчитывать. Это не стиль ради
стиля: тест `test_findings_dump_blocks_derived_index_across_snapshots`
требует, чтобы дробь вроде «2.5» не попадала на страницу нигде, даже в
атрибут style, — и если бы округление жило в шаблоне, дробь могла бы туда
просочиться по недосмотру. Округляя один раз здесь, мы делаем такую
дробь физически невозможной для вызывающего кода.
"""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.references import Interval

_AXIS_MARGIN = 0.08


@dataclass(frozen=True)
class Scale:
    """Готовая геометрия шкалы находки.

    Опорные точки оси идут парой представлений. `bound_low`/`bound_high` —
    честные концы `target`/`lab_range` без отступа; больше ни для чего не
    годятся, кроме подписи оси текстом (`findings_view._row_for`).
    `axis_low`/`axis_high` — те же точки, раздвинутые на `_AXIS_MARGIN`, —
    по ним и только по ним считаются все проценты (`value_pct`,
    `target_from_pct`, `target_to_pct`) и решается, вышло ли значение за
    край. Подписать ось `axis_low`/`axis_high` значило бы показать коучу
    числовой шум вроде «3.6» вместо осмысленного «10».
    """

    value_pct: int
    target_from_pct: int
    target_to_pct: int
    value_outside: bool
    bound_low: float
    bound_high: float
    axis_low: float
    axis_high: float


def _clamp_pct(raw_pct: float) -> int:
    return max(0, min(100, round(raw_pct)))


def scale_for(
    value: float | None, target: Interval | None, lab_range: Interval | None
) -> Scale | None:
    """Построить шкалу или честно отказаться, если строить её не из чего.

    Ось складывается только из конечных границ `target` и `lab_range` — не
    из самого значения: иначе одинокий выброс растянул бы ось так, что
    настоящий целевой коридор схлопнулся бы в невидимую полоску, а маркер
    потерял бы смысл. Поэтому значение, вышедшее за пределы такой оси,
    просто прижимается к ближнему краю (`value_outside = True`), и
    `value_pct` у него ровно 0 или 100 — по этому шаблон и определяет,
    в какую сторону смотрит стрелка, которую он рисует на этом месте
    вместо риски.

    Решение про `lab_range` без `target`: ось всё равно строится (маркер
    клиента показать честно можно — граница бланка это реальная опорная
    точка), но полоса коридора выходит нулевой ширины — а такую шаблон не
    рисует вовсе, потому что у неё есть рамка и «полосы нет» иначе
    выглядело бы как «полоса в самом низу оси». Лабораторный
    диапазон — это норма бланка, а не решение коуча; закрасить его как
    целевой коридор значило бы выдать чужую норму за коучинговую, а
    инструмент не угадывает.
    """
    if value is None:
        return None

    bounds: set[float] = set()
    for interval in (target, lab_range):
        if interval is None:
            continue
        if interval.low is not None:
            bounds.add(interval.low)
        if interval.high is not None:
            bounds.add(interval.high)

    if len(bounds) < 2:
        # Меньше двух разных опорных точек (включая случай, когда обе
        # границы, что дали target и lab_range, сходятся в одной точке, —
        # вырожденная ось нулевой ширины) — рисовать её было бы выдумкой.
        return None

    raw_low, raw_high = min(bounds), max(bounds)
    margin = (raw_high - raw_low) * _AXIS_MARGIN
    axis_low, axis_high = raw_low - margin, raw_high + margin
    axis_span = axis_high - axis_low

    def pct(x: float) -> int:
        return _clamp_pct((x - axis_low) / axis_span * 100)

    if value < axis_low:
        value_pct, value_outside = 0, True
    elif value > axis_high:
        value_pct, value_outside = 100, True
    else:
        value_pct, value_outside = pct(value), False

    if target is None:
        target_from_pct = target_to_pct = 0
    else:
        target_low = target.low if target.low is not None else axis_low
        target_high = target.high if target.high is not None else axis_high
        target_from_pct = pct(target_low)
        target_to_pct = pct(target_high)

    return Scale(
        value_pct=value_pct,
        target_from_pct=target_from_pct,
        target_to_pct=target_to_pct,
        value_outside=value_outside,
        bound_low=raw_low,
        bound_high=raw_high,
        axis_low=axis_low,
        axis_high=axis_high,
    )
