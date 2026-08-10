"""Сборка обезличенного входа модели.

Единственный способ получить текст для отправки. Проверку на утечку
зовёт сам, чтобы забыть её было невозможно: функция не возвращает ничего,
что эту проверку не прошло.
"""

from __future__ import annotations

from collections.abc import Sequence

from healthcoach.privacy.findings import FOR_MODEL, safe_finding
from healthcoach.privacy.leak import assert_no_leak
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class PayloadError(Exception):
    """Вход модели собрать нельзя."""


_MULTI_DATE_WARNING = (
    "ВНИМАНИЕ: набор охватывает несколько разных дат измерения — у "
    "каждой находки своя дата рядом с ней. Не пишите так, будто все "
    "значения получены сегодня."
)


def _dates_warning(findings: Sequence[Finding]) -> str | None:
    """Предупреждение о разных датах — один раз на весь запрос, а не за
    находку и не за раздел (правило задачи 6).

    Живёт здесь, а не в сборке черновика, по одной причине: сторож утечки
    зовётся в конце `build_payload`, и текст, приписанный к запросу после
    него, ушёл бы модели непроверенным. Сегодня строка статична, но
    первая же правка «подставить сюда сами даты» открыла бы дорогу мимо
    сторожа. Всё, что уходит модели, собирается до проверки.

    Считаются даты всех находок, включая анкету: с тех пор как находки
    опросника несут дату своего среза, отчёт по одному срезу тоже может
    получить предупреждение — бланк сдан 20.08, а анкета подшита к срезу
    от 01.09. Это честно: даты у находок и правда разные. Находки вовсе
    без даты (вызовы до многосрезового отчёта) предупреждения не дают.
    """
    dates = {f.taken_on for f in findings if f.taken_on is not None}
    if len(dates) > 1:
        return _MULTI_DATE_WARNING
    return None


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
    # Единственная маска на оба пути наружу — вход модели и клиентский
    # отчёт. Своей копии здесь нет намеренно: она уже однажды разошлась с
    # копией в report/data.py.
    safe = safe_finding(finding, audience=FOR_MODEL)
    value = "—" if safe.value is None else safe.value
    parts = [
        f"[{finding_id(safe)}]",
        f"{safe.title}:",
        f"{value} {safe.units}".strip(),
        f"— {safe.status}",
    ]
    if safe.taken_on is not None:
        # Дата измерения — без неё модель примет мартовский анализ за
        # сегодняшний и напишет «сейчас у вас ферритин 18».
        parts.append(f"(от {safe.taken_on.strftime('%d.%m.%Y')})")
    if safe.target is not None:
        parts.append(f"(целевой коридор {safe.target.low}–{safe.target.high})")
    if safe.note:
        parts.append(f"({safe.note})")
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

    warning = _dates_warning(findings)
    if warning is not None:
        lines += ["", warning]

    payload = "\n".join(lines)
    assert_no_leak(payload, client)
    return payload
