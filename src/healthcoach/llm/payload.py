"""Сборка обезличенного входа модели.

Единственный способ получить текст для отправки. Проверку на утечку
зовёт сам, чтобы забыть её было невозможно: функция не возвращает ничего,
что эту проверку не прошло.
"""

from __future__ import annotations

from collections.abc import Sequence

from healthcoach.privacy.leak import assert_no_leak
from healthcoach.scoring.findings import KIND_ANALYTE, KIND_DERIVED, Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class PayloadError(Exception):
    """Вход модели собрать нельзя."""


UNRESOLVED_TITLE = "показатель из бланка, не распознан"
"""Заголовок находки-показателя, для которой не сработало правило.
Настоящий title для неё в общем случае — текст, списанный с бланка
(иногда OCR-ом с фотографии), и может содержать что угодно, вплоть до
имени клиента: путь в `check_measurements`/`_unresolved` подставляет туда
`measurement.label`, каким бы ни был `subject_id`. Модель всё равно не
может истолковать показатель, для которого правило не задано, поэтому
заменять его заголовок на общую формулировку ничего не теряет.

Заголовок опросника этим правилом не маскируется: он всегда берётся из
базы знаний коуча (название блока/подшкалы), а не из документа клиента,
даже когда степень не выставлена (`rule_missing=True`)."""


def finding_id(finding: Finding) -> str:
    """Устойчивый идентификатор находки — по нему раздел на неё ссылается."""
    return f"{finding.kind}/{finding.subject_id}"


def _finding_line(finding: Finding) -> str:
    value = "—" if finding.value is None else finding.value
    document_derived = finding.kind in (KIND_ANALYTE, KIND_DERIVED) and finding.rule_missing
    title = UNRESOLVED_TITLE if document_derived else finding.title
    parts = [
        f"[{finding_id(finding)}]",
        f"{title}:",
        f"{value} {finding.units}".strip(),
        f"— {finding.status}",
    ]
    if finding.target is not None:
        parts.append(f"(целевой коридор {finding.target.low}–{finding.target.high})")
    if finding.note:
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
