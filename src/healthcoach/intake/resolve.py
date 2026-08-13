"""Распознавание показателя по строке из бланка анализов.

Строка приходит в живом виде: «Ферритин (S-Ferritin)», «ФЕРРИТИН, нг/мл»,
«Ферритин*». Совпадение ищется точное, по очищенной строке; неоднозначность
не разрешается угадыванием — кандидаты возвращаются коучу на сверку.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, References

Cleaner = Callable[[str], str]
"""Одна из двух форм написания: уточнённая (`_clean_qualified`) или общая
(`_clean`). Название с бланка и написания из базы знаний обязаны чиститься
одной и той же — иначе сравниваются разные формы одной строки."""

_NOISE = re.compile(r"[*†‡]|\(.*?\)|\[.*?\]")
_TRAILING = re.compile(r"[\s,;:.\-–—]+$")
_SPACES = re.compile(r"\s+")
LAB_CODE = re.compile(
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
вырезается: в этом случае терять нечего.

Единственный экземпляр этого правила во всём проекте: lab_table.py разбирает
строку выгрузки раньше, чем сюда попадает имя, и раньше держал свою — более
жадную — копию, которая эту защиту сводила на нет. Теперь он импортирует
именно этот объект вместо второй копии."""


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


def _strip_noise(raw_name: str) -> str:
    """Общее для обеих попыток: код номенклатуры, сноски, скобочные уточнения.

    Чистится одинаково и там, и там — иначе уточнённая попытка спотыкалась
    бы о код номенклатуры перед названием, а заметно это стало бы только на
    строках с запятой.
    """
    return _NOISE.sub(" ", LAB_CODE.sub("", raw_name))


def _finish(text: str) -> str:
    return _SPACES.sub(" ", _TRAILING.sub("", text)).strip().casefold()


def _clean_qualified(raw_name: str) -> str:
    """Полное написание — вместе с тем, что стоит после запятой.

    Запятая становится пробелом, а не границей: «Лимфоциты (LYMPH), %» и
    «Лимфоциты %» — одно написание, разделённое по-разному разными
    лабораториями.
    """
    return _finish(_strip_noise(raw_name).replace(",", " "))


def _clean(raw_name: str) -> str:
    """Общее написание: всё после первой запятой отброшено.

    Хвост чаще всего единицы («Гемоглобин, г/л»), и колонка единиц несёт
    то же самое, так что терять его безопасно. Но не всегда — см.
    `_clean_qualified` и порядок попыток в `resolve_analyte`.
    """
    return _finish(_strip_noise(raw_name).split(",")[0])


def _keys(analyte: Analyte, clean: Cleaner) -> set[str]:
    return {
        clean(name) for name in (analyte.id, analyte.name, *analyte.synonyms) if name
    }


def _match(references: References, cleaned: str, clean: Cleaner) -> tuple[Analyte, ...]:
    return tuple(a for a in references.analytes if cleaned in _keys(a, clean))


def resolve_analyte(references: References, raw_name: str) -> Resolution:
    """Найти показатель по строке бланка.

    Две попытки, уточнённая раньше общей. Хвост после запятой бывает не
    единицами, а именем самой величины: лейкоцитарная формула печатает
    «Лимфоциты (LYMPH), %» и «Лимфоциты (LYMPH), абсолютное количество» —
    две разные величины в разных единицах. Обрезав хвост сразу, обе строки
    приходили к одному написанию «лимфоциты», обе находили процентный
    показатель, и абсолютный счёт отвергался жалобой «единицы не
    сопоставлены» — то есть коуч видел спор о единицах там, где на самом
    деле стоял другой показатель.

    Общая попытка остаётся запасной и работает ровно как раньше, поэтому
    «Гемоглобин, г/л» и всё, что находилось до сих пор, находится и теперь.
    """
    qualified = _clean_qualified(raw_name)
    if qualified:
        matched = _match(references, qualified, _clean_qualified)
        if len(matched) == 1:
            return Resolution(analyte=matched[0], candidates=matched, raw_name=raw_name)

    cleaned = _clean(raw_name)
    if not cleaned:
        return Resolution(analyte=None, candidates=(), raw_name=raw_name)

    matched = _match(references, cleaned, _clean)
    if len(matched) == 1:
        return Resolution(analyte=matched[0], candidates=matched, raw_name=raw_name)
    return Resolution(analyte=None, candidates=matched, raw_name=raw_name)
