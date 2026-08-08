"""Скоринг опросника по ключу коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import (
    Block,
    Questionnaire,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.sex import normalize_sex

Answers = dict[str, int]

MIN_ANSWERED_SHARE = 2 / 3
"""Ниже этой доли заполненности степень отклонения не выносится."""


class ScoringError(Exception):
    """Ответы не согласуются со спецификацией опросника."""


@dataclass(frozen=True)
class SubscaleScore:
    block_id: str
    block_title: str
    subscale_id: str
    subscale_title: str
    score: int
    degree: str | None
    degree_missing: str | None
    answered: int
    total: int


def _contains(threshold: Threshold, score: int) -> bool:
    if threshold.min is not None and score < threshold.min:
        return False
    if threshold.max is not None and score > threshold.max:
        return False
    return True


def _degree(
    thresholds: tuple[Threshold, ...], score: int, sex: str
) -> tuple[str | None, str | None]:
    """Степень отклонения и, если её нет, причина отсутствия.

    Причина `None` означает, что степени нет по существу: балл ниже самой
    лёгкой границы. Любая другая причина — это пробел, а не норма.
    """
    if not thresholds:
        return None, "пороги не заданы"

    applicable = [t for t in thresholds if t.sex is None or t.sex == sex]
    if not applicable:
        return None, f"нет порогов для пола {sex!r}"

    for threshold in applicable:
        if _contains(threshold, score):
            return threshold.degree, None

    lowest = min((t.min for t in applicable if t.min is not None), default=None)
    if lowest is not None and score < lowest:
        return None, None

    return None, f"балл {score} не попал ни в один диапазон"


def _validate(questionnaire: Questionnaire, answers: Answers) -> None:
    known: dict[str, set[int]] = {}
    for block in questionnaire.blocks:
        for question in block.questions:
            known[question.id] = {o.score for o in question.options()}

    for question_id, value in answers.items():
        if question_id not in known:
            raise ScoringError(f"вопроса {question_id!r} нет в спецификации опросника")
        if value not in known[question_id]:
            raise ScoringError(
                f"вопрос {question_id!r}: балл {value} вне шкалы "
                f"{sorted(known[question_id])}"
            )


def _score_subscale(
    block: Block, subscale: Subscale, answers: Answers, sex: str
) -> SubscaleScore | None:
    given = [answers[q] for q in subscale.question_ids if q in answers]
    if not given:
        return None

    total = len(subscale.question_ids)
    answered = len(given)
    score = sum(given)

    if answered / total >= MIN_ANSWERED_SHARE:
        degree, degree_missing = _degree(subscale.thresholds, score, sex)
    else:
        degree, degree_missing = None, f"отвечено {answered} из {total} вопросов"

    return SubscaleScore(
        block_id=block.id,
        block_title=block.title,
        subscale_id=subscale.id,
        subscale_title=subscale.title,
        score=score,
        degree=degree,
        degree_missing=degree_missing,
        answered=answered,
        total=total,
    )


def score_questionnaire(
    questionnaire: Questionnaire, answers: Answers, sex: str
) -> list[SubscaleScore]:
    """Посчитать суммы по подгруппам и вынести степени отклонения."""
    sex = normalize_sex(sex)
    _validate(questionnaire, answers)

    results: list[SubscaleScore] = []
    for block in questionnaire.blocks:
        for subscale in block.subscales:
            scored = _score_subscale(block, subscale, answers, sex)
            if scored is not None:
                results.append(scored)
    return results
