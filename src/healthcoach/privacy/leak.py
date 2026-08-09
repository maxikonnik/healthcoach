"""Сторож: ничто из того, что мы знаем про клиента, не уходит наружу.

Он не чинит текст — он не пускает его. Всё, что отправляется модели,
проходит здесь, и обойти это нечем: у функции нет параметра, отключающего
проверку, и добавлять его нельзя. Отладочный флаг однажды останется
включённым.
"""

from __future__ import annotations

import re

from healthcoach.privacy.redact import needles
from healthcoach.storage.clients import Client


class LeakError(Exception):
    """В отправляемых данных найдено то, что позволяет узнать клиента."""


def assert_no_leak(payload: str, client: Client) -> None:
    """Поднять LeakError, если в payload есть данные клиента."""
    found = [
        needle
        for needle in needles(client)
        if re.search(re.escape(needle), payload, re.IGNORECASE)
    ]
    if found:
        raise LeakError(
            f"в данных для модели найдено то, что позволяет узнать клиента "
            f"{client.code}: {', '.join(sorted(set(found)))} — отправка не выполнена"
        )
