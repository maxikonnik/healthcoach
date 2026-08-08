"""Разбор файла с ответами, присланного клиентом."""

from __future__ import annotations

import json
from dataclasses import dataclass

from healthcoach.intake.questionnaire_html import PAYLOAD_VERSION
from healthcoach.knowledge.questionnaire import Questionnaire


class AnswersError(Exception):
    """Файл ответов непригоден."""


@dataclass(frozen=True)
class ImportedAnswers:
    client_code: str
    answers: dict[str, int]
    skipped: tuple[str, ...]


def parse_answers(questionnaire: Questionnaire, payload: str | bytes) -> ImportedAnswers:
    """Разобрать и проверить файл ответов.

    Пропущенные вопросы — нормально: они перечисляются отдельно. Балл вне
    шкалы или вопрос вне спецификации — ошибка: это расхождение версий,
    и увидеть его надо сразу, а не после подсчёта.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AnswersError(f"файл ответов не разобран как JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise AnswersError("файл ответов должен содержать объект")

    version = body.get("версия")
    if version != PAYLOAD_VERSION:
        raise AnswersError(
            f"версия файла ответов {version!r} не поддерживается, "
            f"ожидается {PAYLOAD_VERSION!r}"
        )

    raw_answers = body.get("ответы")
    if not isinstance(raw_answers, dict):
        raise AnswersError("в файле ответов нет объекта 'ответы'")

    spec_version = body.get("спецификация")
    if spec_version != questionnaire.version:
        raise AnswersError(
            f"файл собран по спецификации {spec_version!r}, "
            f"а загружена {questionnaire.version!r}"
        )

    scales: dict[str, set[int]] = {}
    for block in questionnaire.blocks:
        for question in block.questions:
            scales[question.id] = {o.score for o in question.options()}

    answers: dict[str, int] = {}
    for question_id, score in raw_answers.items():
        if question_id not in scales:
            raise AnswersError(
                f"вопроса {question_id!r} нет в спецификации; "
                f"вероятно, опросник собран по другой версии"
            )
        if not isinstance(score, int) or isinstance(score, bool):
            raise AnswersError(
                f"вопрос {question_id!r}: балл должен быть целым числом, "
                f"получено {score!r}"
            )
        if score not in scales[question_id]:
            raise AnswersError(
                f"вопрос {question_id!r}: балл {score} вне шкалы "
                f"{sorted(scales[question_id])}"
            )
        answers[question_id] = score

    skipped = tuple(qid for qid in scales if qid not in answers)
    return ImportedAnswers(
        client_code=str(body.get("клиент", "")),
        answers=answers,
        skipped=skipped,
    )
