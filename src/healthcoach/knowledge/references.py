"""Кастомные превентивные референсы коуча."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ReferenceError(Exception):
    """Файл референсов некорректен."""


@dataclass(frozen=True)
class Interval:
    low: float | None
    high: float | None

    def contains(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True


@dataclass(frozen=True)
class Condition:
    sex: str | None
    age_min: int | None
    age_max: int | None
    cycle_phase: str | None

    def matches(
        self, sex: str | None, age: int | None, cycle_phase: str | None
    ) -> bool:
        if self.sex is not None and self.sex != sex:
            return False
        if self.age_min is not None and (age is None or age < self.age_min):
            return False
        if self.age_max is not None and (age is None or age > self.age_max):
            return False
        if self.cycle_phase is not None and self.cycle_phase != cycle_phase:
            return False
        return True


@dataclass(frozen=True)
class Target:
    condition: Condition
    optimal: Interval
    deficient: Interval | None
    excessive: Interval | None


@dataclass(frozen=True)
class Analyte:
    id: str
    name: str
    synonyms: tuple[str, ...]
    units: str
    lab_range: Interval | None
    targets: tuple[Target, ...]
    interpret_with: tuple[str, ...]
    note: str | None


@dataclass(frozen=True)
class Derived:
    id: str
    name: str
    formula: str
    optimal: Interval
    note: str | None


@dataclass(frozen=True)
class References:
    analytes: tuple[Analyte, ...]
    derived: tuple[Derived, ...]
    _index: dict[str, Analyte] = field(default_factory=dict, repr=False, compare=False)

    def analyte(self, analyte_id: str) -> Analyte | None:
        for item in self.analytes:
            if item.id == analyte_id:
                return item
        return None

    def resolve(self, name: str) -> Analyte | None:
        """Найти показатель по идентификатору, названию или синониму."""
        return self._index.get(name.strip().casefold())


def _interval(raw, where: str) -> Interval | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2:
        raise ReferenceError(f"{where}: интервал должен быть списком из двух значений")
    low, high = raw
    return Interval(
        low=None if low is None else float(low),
        high=None if high is None else float(high),
    )


def _condition(raw: dict | None) -> Condition:
    raw = raw or {}
    age = raw.get("возраст")
    if age is not None and (not isinstance(age, list) or len(age) != 2):
        raise ReferenceError("условие: 'возраст' должен быть списком [от, до]")
    return Condition(
        sex=raw.get("пол"),
        age_min=None if age is None or age[0] is None else int(age[0]),
        age_max=None if age is None or age[1] is None else int(age[1]),
        cycle_phase=raw.get("фаза_цикла"),
    )


def _target(raw: dict, where: str) -> Target:
    if "оптимум" not in raw:
        raise ReferenceError(f"{where}: у целевого значения нет ключа 'оптимум'")
    optimal = _interval(raw["оптимум"], where)
    assert optimal is not None
    return Target(
        condition=_condition(raw.get("условие")),
        optimal=optimal,
        deficient=_interval(raw.get("дефицит"), where),
        excessive=_interval(raw.get("избыток"), where),
    )


def _analyte(raw: dict) -> Analyte:
    analyte_id = str(raw["id"])
    where = f"показатель {analyte_id!r}"
    targets = tuple(_target(t, where) for t in raw["целевые"])
    if not targets:
        raise ReferenceError(f"{where}: нет ни одного целевого значения")
    return Analyte(
        id=analyte_id,
        name=str(raw["название"]),
        synonyms=tuple(str(s) for s in raw.get("синонимы", ())),
        units=str(raw["единицы"]),
        lab_range=_interval(raw.get("лабораторный_интервал"), where),
        targets=targets,
        interpret_with=tuple(str(s) for s in raw.get("трактовать_с", ())),
        note=raw.get("заметка"),
    )


def _derived(raw: dict) -> Derived:
    where = f"производный {raw['id']!r}"
    optimal = _interval(raw["оптимум"], where)
    assert optimal is not None
    return Derived(
        id=str(raw["id"]),
        name=str(raw["название"]),
        formula=str(raw["формула"]),
        optimal=optimal,
        note=raw.get("заметка"),
    )


def load_references(directory: Path) -> References:
    """Прочитать все YAML-файлы референсов из папки."""
    analytes: list[Analyte] = []
    derived: list[Derived] = []

    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            analytes.extend(_analyte(a) for a in raw.get("показатели", ()))
            derived.extend(_derived(d) for d in raw.get("производные", ()))
        except (KeyError, TypeError) as exc:
            raise ReferenceError(f"{path.name}: {exc}") from exc

    ids = [a.id for a in analytes] + [d.id for d in derived]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ReferenceError(f"повторяющиеся идентификаторы показателей: {duplicates}")

    index: dict[str, Analyte] = {}
    for analyte in analytes:
        for key in (analyte.id, analyte.name, *analyte.synonyms):
            index[key.strip().casefold()] = analyte

    return References(analytes=tuple(analytes), derived=tuple(derived), _index=index)
