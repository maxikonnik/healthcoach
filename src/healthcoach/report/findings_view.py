"""Раскладка находок по группам для экрана коуча.

Никакой HTML тут не строится (Task 3) — только готовые группы, тона и
текст, которые шаблону останется разложить. Группировка и форматирование
переиспользуют уже существующее знание домена (`scoring.findings.severity`,
`report.pdf.interval_text`), а не заводят вторую копию, которая рано или
поздно разъедется с оригиналом.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from healthcoach.report.pdf import NOTHING, format_number, interval_text
from healthcoach.report.scale import Scale, scale_for
from healthcoach.scoring.findings import KIND_QUESTIONNAIRE, Finding, severity

_TONE_BY_SEVERITY = {
    0: "bad",
    1: "bad",
    2: "warn",
    3: "ok",
    4: "muted",
    5: "muted",
}
"""severity 0-1 → bad, 3 → ok, 4-5 → muted (см. план). Промежуточная
тяжесть 2 бывает только у степени «низкая» опросника — сюда же добавлен
`warn`, единственный тон `.tag`, для которого иначе не нашлось бы правила."""


def _tone_for(status: str) -> str:
    return _TONE_BY_SEVERITY.get(severity(status), "muted")


def _value_text(finding: Finding) -> str:
    """«18 нг/мл», «— нг/мл» при отсутствии значения — как в таблице PDF."""
    value = NOTHING if finding.value is None else format_number(finding.value)
    return f"{value} {finding.units}".strip()


@dataclass(frozen=True)
class Row:
    finding: Finding
    scale: Scale | None
    target_text: str
    lab_text: str
    value_text: str
    tone: str
    axis_low_text: str
    """Честная подпись левого конца оси; пусто, если шкалы нет."""
    axis_high_text: str
    """Честная подпись правого конца оси; пусто, если шкалы нет."""


@dataclass(frozen=True)
class Group:
    title: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class FindingsView:
    attention: Group
    normal: Group
    unjudged: Group
    questionnaire: Group
    missing_rules: tuple[str, ...]


def _row_for(finding: Finding) -> Row:
    scale = scale_for(finding.value, finding.target, finding.lab_range)
    axis_low_text, axis_high_text = (
        (format_number(scale.bound_low), format_number(scale.bound_high))
        if scale is not None
        else ("", "")
    )
    return Row(
        finding=finding,
        scale=scale,
        target_text=interval_text(finding.target),
        lab_text=interval_text(finding.lab_range),
        value_text=_value_text(finding),
        tone=_tone_for(finding.status),
        axis_low_text=axis_low_text,
        axis_high_text=axis_high_text,
    )


def build_view(findings: Iterable[Finding]) -> FindingsView:
    """Разложить плоский список находок по группам экрана."""
    attention: list[Row] = []
    normal: list[Row] = []
    unjudged: list[Row] = []
    questionnaire: list[Row] = []
    missing_rules: list[str] = []

    for finding in findings:
        if finding.rule_missing:
            missing_rules.append(finding.title)

        row = _row_for(finding)
        if finding.kind == KIND_QUESTIONNAIRE:
            # У шкал опросника нет ни коридора, ни единиц в привычном
            # смысле — сравнивать их со степенью показателя крови значит
            # сравнивать несравнимое, поэтому своя группа независимо от
            # тяжести.
            questionnaire.append(row)
            continue

        level = severity(finding.status)
        if level <= 1:
            attention.append(row)
        elif level == 3:
            normal.append(row)
        else:
            unjudged.append(row)

    return FindingsView(
        attention=Group("Требуют внимания", tuple(attention)),
        normal=Group("В норме", tuple(normal)),
        unjudged=Group("Оценить не удалось", tuple(unjudged)),
        questionnaire=Group("Шкалы опросника", tuple(questionnaire)),
        missing_rules=tuple(missing_rules),
    )
