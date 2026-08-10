"""Сборка черновика по разделам.

Каждый раздел помечается находками, на которых стоит: коуч видит цепочку и
может возразить в любом звене. Привязка считается кодом, а не выспрашивается
у модели — выспрошенная была бы ещё одним местом, где можно выдумать.

Отказ модели останавливает сборку. Половина черновика молча хуже отказа:
коуч решит, что модель сказала всё, что имела сказать.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from healthcoach.llm.payload import build_payload, finding_id
from healthcoach.llm.provider import LLMError, LLMProvider
from healthcoach.report.sections import SECTIONS, Section
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class DraftError(Exception):
    """Черновик собрать не удалось."""


@dataclass(frozen=True)
class GeneratedSection:
    section_id: str
    text: str
    finding_ids: tuple[str, ...]


def _section_findings(section: Section, findings: Sequence[Finding]) -> tuple[str, ...]:
    """Находки, на которых стоит раздел.

    Пустой ``section.kinds`` даёт пустой результат: привязка не
    подразумевается по умолчанию, её нужно объявить явно.
    """
    return tuple(finding_id(f) for f in findings if f.kind in section.kinds)


def _prompt(section: Section, payload: str) -> str:
    return (
        f"Ты помогаешь специалисту по здоровью собрать черновик отчёта для "
        f"клиента. Сейчас пиши только раздел «{section.title}».\n\n"
        f"{section.instruction}\n\n"
        f"Верни только текст раздела, без заголовка и без пояснений о том, "
        f"что ты делаешь.\n\n"
        f"ДАННЫЕ\n{payload}"
    )


def generate_draft(
    provider: LLMProvider,
    findings: Sequence[Finding],
    subject: Subject,
    request: str,
    specialties: Sequence[dict[str, str]],
    client: Client,
    on_section: Callable[[int, int], None] | None = None,
) -> list[GeneratedSection]:
    """Собрать черновик по разделам. Останавливается на первом отказе.

    `on_section` вызывается после каждого готового раздела числом готовых
    и общим числом. Сборка идёт минуты, и без этого экрану коуча нечего
    показать: разделы попадают в базу все разом и только в самом конце.
    """
    payload = build_payload(findings, subject, request, specialties, client)

    generated: list[GeneratedSection] = []
    for section in SECTIONS:
        try:
            text = provider.complete(_prompt(section, payload))
        except LLMError as exc:
            raise DraftError(
                f"раздел «{section.title}» ({section.id}) не собран: {exc}"
            ) from exc
        generated.append(
            GeneratedSection(
                section_id=section.id,
                text=text.strip(),
                finding_ids=_section_findings(section, findings),
            )
        )
        if on_section is not None:
            on_section(len(generated), len(SECTIONS))
    return generated
