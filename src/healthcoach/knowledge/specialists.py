"""Справочник специальностей и доверенных врачей коуча.

Контакты врачей никогда не покидают экран коуча: наружу — в клиентский отчёт
и в пакет для языковой модели — отдаётся только public_view().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class SpecialistsError(Exception):
    """Справочник специалистов некорректен."""


@dataclass(frozen=True)
class Doctor:
    name: str
    contacts: str
    format: str
    city: str | None
    note: str | None


@dataclass(frozen=True)
class Specialty:
    id: str
    name: str
    when: str
    doctors: tuple[Doctor, ...]


@dataclass(frozen=True)
class Specialists:
    specialties: tuple[Specialty, ...]

    def specialty(self, specialty_id: str) -> Specialty | None:
        for item in self.specialties:
            if item.id == specialty_id:
                return item
        return None

    def public_view(self) -> tuple[dict[str, str], ...]:
        """Специальности без врачей — безопасно отдавать наружу."""
        return tuple(
            {"id": s.id, "название": s.name, "когда": s.when} for s in self.specialties
        )


def _doctor(raw: dict, where: str) -> Doctor:
    for key in ("имя", "контакты", "формат"):
        if key not in raw:
            raise SpecialistsError(f"{where}: у врача нет ключа {key!r}")
    return Doctor(
        name=str(raw["имя"]),
        contacts=str(raw["контакты"]),
        format=str(raw["формат"]),
        city=raw.get("город"),
        note=raw.get("заметка"),
    )


def _specialty(raw: dict, position: int) -> Specialty:
    if "id" not in raw:
        name = raw.get("название")
        label = f"{name!r}" if name else f"на позиции {position}"
        raise SpecialistsError(f"у специальности {label} нет ключа 'id'")
    where = f"специальность {raw['id']!r}"
    for key in ("название", "когда"):
        if key not in raw:
            raise SpecialistsError(f"{where}: нет ключа {key!r}")
    return Specialty(
        id=str(raw["id"]),
        name=str(raw["название"]),
        when=str(raw["когда"]).strip(),
        doctors=tuple(_doctor(d, where) for d in (raw.get("врачи") or ())),
    )


def load_specialists(path: Path) -> Specialists:
    """Прочитать справочник специальностей из YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "специальности" not in raw:
        raise SpecialistsError(f"{path}: нет ключа 'специальности'")

    specialties = tuple(
        _specialty(s, i) for i, s in enumerate(raw["специальности"], start=1)
    )
    ids = [s.id for s in specialties]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SpecialistsError(f"повторяющиеся идентификаторы специальностей: {duplicates}")

    return Specialists(specialties=specialties)
