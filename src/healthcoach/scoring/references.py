"""Сверка измерений с целевыми коридорами коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, Interval, References, Target
from healthcoach.knowledge.sex import normalize_sex
from healthcoach.knowledge.units import units_match

STATUS_DEFICIT = "дефицит"
STATUS_BELOW = "ниже целевого"
STATUS_WITHIN = "в целевом"
STATUS_ABOVE = "выше целевого"
STATUS_EXCESS = "избыток"
STATUS_NO_RULE = "правило не задано"
STATUS_UNIT_MISMATCH = "единицы не сопоставлены"
STATUS_NOT_COMPUTED = "не удалось вычислить"
STATUS_NO_VALUE = "значение не распознано"


@dataclass(frozen=True)
class Subject:
    sex: str
    age: int
    cycle_phase: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sex", normalize_sex(self.sex))


@dataclass(frozen=True)
class Measurement:
    analyte_id: str
    value: float
    units: str
    label: str = ""
    """Как показатель назван в бланке. Нужен нераспознанным: их
    analyte_id пуст, и без подписи находка была бы безымянной."""
    row_id: int | None = None
    """Идентификатор строки измерения в срезе. Нужен нераспознанным: их
    analyte_id пуст, и без него две нераспознанные находки получают один
    и тот же идентификатор. Идентификатор строки не меняется, пока срез
    жив, — поэтому раздел черновика, сославшийся на находку, найдёт её и
    после перезагрузки страницы."""


@dataclass(frozen=True)
class AnalyteVerdict:
    analyte_id: str
    title: str
    value: float | None
    units: str
    status: str
    target: Interval | None
    lab_range: Interval | None
    note: str | None
    rule_missing: bool
    row_id: int | None = None
    """Строка измерения, из которой вердикт получился. У производных её нет."""
    title_from_document: bool = False
    """title списан с бланка (`measurement.label`), а не взят из базы знаний.

    `rule_missing` для этого не годится: он поднят на четырёх разных путях,
    и только на одном из них — `_unresolved` — заголовок приходит из
    документа клиента. На остальных трёх (единицы не сопоставлены, нет
    целевого значения для пола и возраста, производный не посчитан) это
    `analyte.name`/`derived.name` из базы знаний коуча, и прятать его
    от модели значит запретить ей назвать показатель, который она обязана
    назвать."""
    note_private: bool = False
    """note — заметка коуча из базы знаний, а не пояснение, посчитанное кодом.

    Коуч пишет её себе: «смотреть вместе с СРБ», «направить к врачу:
    Петров И.Л., +7 916 555-11-22». Это рабочая подсказка специалиста, и
    наружу — ни модели, ни в клиентский PDF — она не идёт, ровно как
    контакты врачей из `Specialists.public_view()`. Пояснения, которые
    сочинил код («нет целевого значения для этого пола и возраста»,
    «не удалось вычислить»), этим флагом не помечены: они безопасны и
    объясняют модели, почему находка не истолкована."""
    units_from_document: bool = False
    """units — то, что написано в бланке, а не объявленные единицы показателя.

    Поднят там, где сохранённые единицы заведомо не сведены к референсным:
    показатель не распознан вовсе и сверять не с чем, либо единицы с
    референсом не сопоставились. Ручной ввод сохраняет подпись единиц
    дословно, так что там может оказаться что угодно, вплоть до строки с
    именем клиента."""


def select_target(analyte: Analyte, subject: Subject) -> Target | None:
    """Первое целевое значение, чьё условие подошло. Порядок задаёт приоритет."""
    for target in analyte.targets:
        if target.condition.matches(subject.sex, subject.age, subject.cycle_phase):
            return target
    return None


def _status(target: Target, value: float) -> str:
    if target.deficient is not None and target.deficient.contains(value):
        return STATUS_DEFICIT
    if target.excessive is not None and target.excessive.contains(value):
        return STATUS_EXCESS
    if target.optimal.contains(value):
        return STATUS_WITHIN
    if target.optimal.low is not None and value < target.optimal.low:
        return STATUS_BELOW
    return STATUS_ABOVE


def _unresolved(measurement: Measurement, status: str) -> AnalyteVerdict:
    """Вердикт по измерению, которое не с чем сверить.

    Единственное место, где заголовок и единицы берутся из бланка клиента,
    а не из базы знаний коуча, — поэтому оба флага «из документа» поднимает
    только оно.
    """
    return AnalyteVerdict(
        analyte_id=measurement.analyte_id,
        title=measurement.label or measurement.analyte_id,
        value=measurement.value,
        units=measurement.units,
        status=status,
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
        row_id=measurement.row_id,
        title_from_document=True,
        units_from_document=True,
    )


def check_measurements(
    references: References, measurements: list[Measurement], subject: Subject
) -> list[AnalyteVerdict]:
    """Сверить измерения с референсами. Ничего не отбрасывать молча."""
    verdicts: list[AnalyteVerdict] = []

    for measurement in measurements:
        if measurement.value is None:
            verdicts.append(_unresolved(measurement, STATUS_NO_VALUE))
            continue

        analyte = references.resolve(measurement.analyte_id)
        if analyte is None:
            verdicts.append(_unresolved(measurement, STATUS_NO_RULE))
            continue

        if not units_match(analyte, measurement.units):
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_UNIT_MISMATCH,
                    target=None,
                    lab_range=analyte.lab_range,
                    note=(
                        f"референс задан в единицах {analyte.units!r}, "
                        f"измерение пришло в {measurement.units!r}"
                    ),
                    rule_missing=True,
                    row_id=measurement.row_id,
                    # Название — из базы знаний: показатель распознан.
                    # Единицы — из бланка: с референсными они не сошлись.
                    title_from_document=False,
                    units_from_document=True,
                )
            )
            continue

        target = select_target(analyte, subject)
        if target is None:
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_NO_RULE,
                    target=None,
                    lab_range=analyte.lab_range,
                    note="нет целевого значения для этого пола и возраста",
                    rule_missing=True,
                    row_id=measurement.row_id,
                )
            )
            continue

        verdicts.append(
            AnalyteVerdict(
                analyte_id=analyte.id,
                title=analyte.name,
                value=measurement.value,
                units=measurement.units,
                status=_status(target, measurement.value),
                target=target.optimal,
                lab_range=analyte.lab_range,
                note=analyte.note,
                rule_missing=False,
                row_id=measurement.row_id,
                # Заметка здесь — текст коуча из базы знаний, а не
                # пояснение кода: наружу её выпускать нельзя.
                note_private=True,
            )
        )

    return verdicts
