"""Спецификация большого интегрального опросника."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class QuestionnaireError(Exception):
    """Спецификация опросника некорректна."""


@dataclass(frozen=True)
class ScaleOption:
    score: int
    label: str


@dataclass(frozen=True)
class Question:
    id: str
    number: int
    text: str
    scale: tuple[ScaleOption, ...] | None
    block_scale: tuple[ScaleOption, ...]

    def options(self) -> tuple[ScaleOption, ...]:
        """Собственная шкала вопроса, иначе шкала блока."""
        return self.scale if self.scale else self.block_scale


@dataclass(frozen=True)
class Threshold:
    degree: str
    min: int | None
    max: int | None
    sex: str | None


@dataclass(frozen=True)
class Subscale:
    id: str
    title: str
    question_ids: tuple[str, ...]
    thresholds: tuple[Threshold, ...]


@dataclass(frozen=True)
class Block:
    id: str
    title: str
    part: str
    core: bool
    scale: tuple[ScaleOption, ...]
    questions: tuple[Question, ...]
    subscales: tuple[Subscale, ...]


@dataclass(frozen=True)
class Questionnaire:
    version: str
    blocks: tuple[Block, ...]

    def block(self, block_id: str) -> Block:
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise QuestionnaireError(f"в спецификации нет блока {block_id!r}")


def _scale(raw: list[dict] | None) -> tuple[ScaleOption, ...] | None:
    if raw is None:
        return None
    return tuple(ScaleOption(score=int(o["score"]), label=str(o["label"])) for o in raw)


def _threshold(raw: dict) -> Threshold:
    return Threshold(
        degree=str(raw["degree"]),
        min=None if raw.get("min") is None else int(raw["min"]),
        max=None if raw.get("max") is None else int(raw["max"]),
        sex=None if raw.get("sex") is None else str(raw["sex"]),
    )


def _block(raw: dict) -> Block:
    block_scale = _scale(raw["scale"])
    if not block_scale:
        raise QuestionnaireError(f"блок {raw['id']!r}: пустая шкала")

    questions = tuple(
        Question(
            id=str(q["id"]),
            number=int(q["number"]),
            text=str(q["text"]),
            scale=_scale(q.get("scale")),
            block_scale=block_scale,
        )
        for q in raw["questions"]
    )
    known = {q.id for q in questions}

    subscales = []
    for sub in raw["subscales"]:
        ids = tuple(str(i) for i in sub["question_ids"])
        for question_id in ids:
            if question_id not in known:
                raise QuestionnaireError(
                    f"блок {raw['id']!r}, подгруппа {sub['id']!r}: "
                    f"ссылка на неизвестный вопрос {question_id!r}"
                )
        subscales.append(
            Subscale(
                id=str(sub["id"]),
                title=str(sub["title"]),
                question_ids=ids,
                thresholds=tuple(_threshold(t) for t in sub["thresholds"]),
            )
        )

    return Block(
        id=str(raw["id"]),
        title=str(raw["title"]),
        part=str(raw["part"]),
        core=bool(raw["core"]),
        scale=block_scale,
        questions=questions,
        subscales=tuple(subscales),
    )


def load_questionnaire(path: Path) -> Questionnaire:
    """Прочитать спецификацию опросника из YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or "blocks" not in raw:
        raise QuestionnaireError(f"{path}: нет ключа 'blocks'")

    blocks = tuple(_block(b) for b in raw["blocks"])
    ids = [b.id for b in blocks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise QuestionnaireError(f"повторяющиеся идентификаторы блоков: {sorted(duplicates)}")

    return Questionnaire(version=str(raw["version"]), blocks=blocks)
