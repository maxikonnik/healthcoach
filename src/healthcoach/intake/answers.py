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
    """Результат разбора файла ответов.

    `skipped` и `not_asked` разделены намеренно: первое — вопросы, которые
    клиент видел и оставил пустыми, и с ними коучу есть что делать; второе —
    вопросы из блоков, которые этому клиенту вовсе не отправляли. Сваленные
    в одну кучу, они превращали бы список в шум: необязательных вопросов в
    спецификации больше двух сотен.
    """

    client_code: str
    shown_blocks: tuple[str, ...]
    answers: dict[str, int]
    skipped: tuple[str, ...]
    not_asked: tuple[str, ...]


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

    raw_blocks = body.get("блоки")
    if not isinstance(raw_blocks, list) or not all(
        isinstance(b, str) for b in raw_blocks
    ):
        raise AnswersError("в файле ответов нет списка 'блоки' со строками")

    known_blocks = {block.id for block in questionnaire.blocks}
    unknown = [b for b in raw_blocks if b not in known_blocks]
    if unknown:
        raise AnswersError(
            f"в спецификации нет блоков {sorted(unknown)}; "
            f"вероятно, опросник собран по другой версии"
        )
    shown_blocks = tuple(raw_blocks)

    scales: dict[str, set[int]] = {}
    asked: set[str] = set()
    for block in questionnaire.blocks:
        for question in block.questions:
            scales[question.id] = {o.score for o in question.options()}
            if block.id in shown_blocks:
                asked.add(question.id)

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

    answered_outside = sorted(answers.keys() - asked)
    if answered_outside:
        raise AnswersError(
            f"есть ответы на вопросы из блоков, которые клиенту не показывали: "
            f"{answered_outside}"
        )

    return ImportedAnswers(
        client_code=str(body.get("клиент", "")),
        shown_blocks=shown_blocks,
        answers=answers,
        skipped=tuple(qid for qid in scales if qid in asked and qid not in answers),
        not_asked=tuple(qid for qid in scales if qid not in asked),
    )
