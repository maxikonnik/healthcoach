"""Скоринг опросника по ключу коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import (
    Block,
    Questionnaire,
    Subscale,
    Threshold,
)

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
    answered: int
    total: int


def _contains(threshold: Threshold, score: int) -> bool:
    if threshold.min is not None and score < threshold.min:
        return False
    if threshold.max is not None and score > threshold.max:
        return False
    return True


def _degree(thresholds: tuple[Threshold, ...], score: int, sex: str) -> str | None:
    applicable = [t for t in thresholds if t.sex is None or t.sex == sex]
    for threshold in applicable:
        if _contains(threshold, score):
            return threshold.degree
    return None


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
        degree = _degree(subscale.thresholds, score, sex)
    else:
        degree = None

    return SubscaleScore(
        block_id=block.id,
        block_title=block.title,
        subscale_id=subscale.id,
        subscale_title=subscale.title,
        score=score,
        degree=degree,
        answered=answered,
        total=total,
    )


def score_questionnaire(
    questionnaire: Questionnaire, answers: Answers, sex: str
) -> list[SubscaleScore]:
    """Посчитать суммы по подгруппам и вынести степени отклонения."""
    _validate(questionnaire, answers)

    results: list[SubscaleScore] = []
    for block in questionnaire.blocks:
        for subscale in block.subscales:
            scored = _score_subscale(block, subscale, answers, sex)
            if scored is not None:
                results.append(scored)
    return results
