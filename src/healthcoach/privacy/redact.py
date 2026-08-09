"""Вычистка идентифицирующих данных клиента из текста.

Это помощник, а не защита. Он убирает то, что умеет распознать, и
перечисляет убранное, чтобы коуч видел работу и мог возразить. Защита —
`healthcoach.privacy.leak`, и обойти её нечем.

Общая задача «убрать все персональные данные» нерешаема: «работаю в школе
№ 1234» не поймает ни одно правило. Решаемая — убрать то, что мы про
этого клиента знаем.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.storage.clients import Client

MIN_PART = 4
"""Части имени короче этого не вычищаются: «Ли» съело бы пол-текста."""

_MASK = "[убрано]"


@dataclass(frozen=True)
class Redaction:
    text: str
    removed: tuple[str, ...]
    """Что именно найдено и убрано — для показа коучу."""


def name_stems(client: Client) -> list[str]:
    """Основы частей имени: фамилия склоняется, окончание отбрасываем."""
    stems: list[str] = []
    for part in client.full_name.split():
        if len(part) < MIN_PART:
            continue
        stems.append(part[:-2] if len(part) > MIN_PART + 1 else part)
    return stems


def date_forms(client: Client) -> list[str]:
    """Дата рождения во всех записях, встречающихся в бланках."""
    d = client.birth_date
    if d is None:
        return []
    return [
        d.isoformat(),
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}.{d.month}.{d.year}",
    ]


def contact_forms(client: Client) -> list[str]:
    """Контакты целиком и длинные цифровые последовательности из них.

    Короткие обрывки цифр брать нельзя: «916» из телефона совпало бы со
    значением анализа, и сторож отверг бы отправку из-за ферритина 916.
    Шесть цифр подряд — уже номер, а не результат измерения.
    """
    if not client.contacts:
        return []
    forms = [item.strip() for item in client.contacts.split(",") if item.strip()]
    digits = re.findall(r"\d{6,}", client.contacts)
    return forms + digits


def needles(client: Client) -> list[str]:
    """Всё, что мы знаем про этого клиента и не выпускаем наружу."""
    found = [client.code, *name_stems(client), *date_forms(client), *contact_forms(client)]
    return [item for item in found if item]


def redact(text: str, client: Client) -> Redaction:
    """Убрать из текста всё, что позволяет узнать этого клиента."""
    removed: list[str] = []
    result = text
    for needle in sorted(needles(client), key=len, reverse=True):
        pattern = re.compile(re.escape(needle) + r"\w*", re.IGNORECASE)
        if pattern.search(result):
            removed.append(needle)
            result = pattern.sub(_MASK, result)
    return Redaction(text=result, removed=tuple(removed))
