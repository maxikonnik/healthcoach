"""Распознавание показателя по строке из бланка анализов.

Строка приходит в живом виде: «Ферритин (S-Ferritin)», «ФЕРРИТИН, нг/мл»,
«Ферритин*». Совпадение ищется точное, по очищенной строке; неоднозначность
не разрешается угадыванием — кандидаты возвращаются коучу на сверку.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, References

_NOISE = re.compile(r"[*†‡]|\(.*?\)|\[.*?\]")
_TRAILING = re.compile(r"[\s,;:.\-–—]+$")
_SPACES = re.compile(r"\s+")
_LAB_CODE = re.compile(
    r"\bA\d{2}\.\d{2}\.\d{3}\b\s*\(\s*Приказ[^()]*\)"
    r"|"
    r"\bA\d{2}\.\d{2}\.\d{3}\b(?!\s*\()",
    re.IGNORECASE,
)
"""Код номенклатуры медицинских услуг: «Ферритин A09.05.076 (Приказ …)».

Код со скобкой любого другого рода рядом — например, «Кальций A09.05.206
(ионизированный)» — не трогается вовсе: стереть код и оставить чистить
скобку общему _NOISE значило бы стереть «ионизированный» и перепутать
общий кальций с ионизированным. Код без скобки вообще (голый) по-прежнему
вырезается: в этом случае терять нечего."""


@dataclass(frozen=True)
class Resolution:
    """Итог распознавания одной строки бланка."""

    analyte: Analyte | None
    candidates: tuple[Analyte, ...]
    raw_name: str

    def __post_init__(self) -> None:
        if self.analyte is not None and self.candidates != (self.analyte,):
            raise ValueError(
                "распознанный показатель должен быть единственным кандидатом"
            )
        if self.analyte is None and len(self.candidates) == 1:
            raise ValueError(
                "единственный кандидат — это распознанный показатель, "
                "он должен быть указан в analyte"
            )

    @property
    def is_certain(self) -> bool:
        return self.analyte is not None

    @property
    def is_ambiguous(self) -> bool:
        return self.analyte is None and len(self.candidates) > 1

    @property
    def is_unknown(self) -> bool:
        return self.analyte is None and not self.candidates


def _clean(raw_name: str) -> str:
    """Убрать сноски, скобочные уточнения и хвостовые единицы."""
    text = _LAB_CODE.sub("", raw_name)
    text = _NOISE.sub(" ", text)
    text = text.split(",")[0]
    text = _TRAILING.sub("", text)
    return _SPACES.sub(" ", text).strip().casefold()


def _keys(analyte: Analyte) -> set[str]:
    return {
        _clean(name) for name in (analyte.id, analyte.name, *analyte.synonyms) if name
    }


def resolve_analyte(references: References, raw_name: str) -> Resolution:
    """Найти показатель по строке бланка."""
    cleaned = _clean(raw_name)
    if not cleaned:
        return Resolution(analyte=None, candidates=(), raw_name=raw_name)

    matched = tuple(
        analyte for analyte in references.analytes if cleaned in _keys(analyte)
    )
    if len(matched) == 1:
        return Resolution(analyte=matched[0], candidates=matched, raw_name=raw_name)
    return Resolution(analyte=None, candidates=matched, raw_name=raw_name)
