"""Сборка обезличенного входа модели.

Единственный способ получить текст для отправки. Проверку на утечку
зовёт сам, чтобы забыть её было невозможно: функция не возвращает ничего,
что эту проверку не прошло.
"""

from __future__ import annotations

from collections.abc import Sequence

from healthcoach.privacy.leak import assert_no_leak
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class PayloadError(Exception):
    """Вход модели собрать нельзя."""


UNRESOLVED_TITLE = "показатель из бланка, не распознан"
"""Заголовок находки, чей настоящий title списан с бланка клиента
(`measurement.label`, иногда OCR-ом с фотографии) и может содержать что
угодно, вплоть до имени клиента. Модель всё равно не может истолковать
показатель, которого нет в базе знаний, поэтому общая формулировка
ничего не теряет.

Маскируется ровно то, что помечено `title_from_document`, — и ничего
больше. `rule_missing` для этой роли не годится: он поднят на четырёх
разных путях, а заголовок из документа приходит только с одного
(`scoring/references.py`, `_unresolved`). На трёх остальных — единицы не
сопоставлены, нет целевого значения для пола и возраста, производный не
посчитан — заголовок это `analyte.name`/`derived.name` из базы знаний
коуча. Раздел «показатели» обязан такие находки назвать, а под маской
назвать их нечем. Заголовок опросника из документа не приходит никогда."""

DOCUMENT_UNITS = "единицы из бланка"
"""Чем заменяются единицы, списанные с бланка. Ручной ввод сохраняет их
дословно, так что маска на заголовке без маски на единицах не закрывает
строку: `units` и отголосок исходного написания в `note` идут в той же
строке, что и заголовок."""


def finding_id(finding: Finding) -> str:
    """Устойчивый идентификатор находки — по нему раздел на неё ссылается.

    У нераспознанного показателя `subject_id` пуст: в базе знаний коуча
    его нет, и назвать его нечем. Различает такие находки идентификатор
    строки измерения — он не меняется, пока жив срез, поэтому раздел,
    сохранивший ссылку, после перезагрузки страницы указывает на ту же
    находку. Название из бланка идентификатором быть не может: оно уходит
    модели вместе с ним.
    """
    if finding.subject_id:
        return f"{finding.kind}/{finding.subject_id}"
    if finding.row_id is None:
        raise PayloadError(
            "нераспознанная находка без идентификатора строки: две таких "
            "получили бы один идентификатор, и раздел сослался бы не на ту"
        )
    return f"{finding.kind}/строка-{finding.row_id}"


def _finding_line(finding: Finding) -> str:
    value = "—" if finding.value is None else finding.value
    title = UNRESOLVED_TITLE if finding.title_from_document else finding.title
    units = DOCUMENT_UNITS if finding.units_from_document else finding.units
    parts = [
        f"[{finding_id(finding)}]",
        f"{title}:",
        f"{value} {units}".strip(),
        f"— {finding.status}",
    ]
    if finding.target is not None:
        parts.append(f"(целевой коридор {finding.target.low}–{finding.target.high})")
    # note на этом пути пересказывает исходное написание единиц
    # («измерение пришло в …»), то есть проносит текст документа мимо
    # маски. Статус «единицы не сопоставлены» остаётся — модель знает,
    # что показатель не истолковать.
    if finding.note and not finding.units_from_document:
        parts.append(f"({finding.note})")
    if finding.partial:
        parts.append(f"[заполнено {finding.answered} из {finding.total}]")
    return " ".join(str(p) for p in parts)


def build_payload(
    findings: Sequence[Finding],
    subject: Subject,
    request: str,
    specialties: Sequence[dict[str, str]],
    client: Client,
) -> str:
    """Собрать вход модели и не выпустить ничего, что выдаёт клиента."""
    if not findings:
        raise PayloadError("находок нет — интерпретировать нечего")

    human_line = f"пол: {subject.sex}, возраст: {subject.age}"
    if subject.cycle_phase:
        human_line += f", фаза цикла: {subject.cycle_phase}"

    lines = [
        "ЧЕЛОВЕК",
        human_line,
        "",
        "ЗАПРОС И ЦЕЛИ (словами клиента, вычитаны специалистом)",
        request or "не указан",
        "",
        "НАХОДКИ (посчитаны кодом, не пересчитывать)",
    ]
    lines.extend(_finding_line(f) for f in findings)
    lines += ["", "СПЕЦИАЛЬНОСТИ, КУДА МОЖНО НАПРАВИТЬ"]
    lines.extend(
        f"[{s['id']}] {s['название']} — {s['когда']}" for s in specialties
    )

    payload = "\n".join(lines)
    assert_no_leak(payload, client)
    return payload
