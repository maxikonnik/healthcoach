"""Кто подписывает отчёт.

Отдельный файл, а не поле в настройках: имя специалиста печатается на
титуле клиентского PDF и меняется вместе с базой знаний, под контролем
версий.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class CoachError(Exception):
    """Профиль специалиста непригоден."""


@dataclass(frozen=True)
class Coach:
    name: str
    title: str
    signature: str


def load_coach(path: Path) -> Coach:
    """Прочитать профиль специалиста."""
    if not path.is_file():
        raise CoachError(f"{path}: файл профиля специалиста не найден")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(raw.get("имя", "")).strip()
    if not name:
        raise CoachError(f"{path}: не указано имя специалиста — титул подписать нечем")

    return Coach(
        name=name,
        title=str(raw.get("должность", "") or "").strip(),
        signature=str(raw.get("подпись", "") or "").strip(),
    )
