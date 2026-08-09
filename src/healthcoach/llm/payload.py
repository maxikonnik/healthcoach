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


def finding_id(finding: Finding) -> str:
    """Устойчивый идентификатор находки — по нему раздел на неё ссылается."""
    return f"{finding.kind}/{finding.subject_id}"


def _finding_line(finding: Finding) -> str:
    value = "—" if finding.value is None else finding.value
    parts = [
        f"[{finding_id(finding)}]",
        f"{finding.title}:",
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

    lines = [
        "ЧЕЛОВЕК",
        f"пол: {subject.sex}, возраст: {subject.age}",
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
