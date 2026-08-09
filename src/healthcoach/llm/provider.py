"""Вызов языковой модели.

Движок вынесен за интерфейс: сегодня это Claude Code в headless-режиме на
подписке коуча, без оплаты по токенам. Сборка черновика от движка не
зависит и переписываться при его смене не должна.

Ничего не проглатывается молча: недоступная модель, ненулевой код
возврата, неразобранный вывод и пустой ответ — всё это ошибки, о которых
коуч узнаёт.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Protocol

BINARY = "claude"
DEFAULT_TIMEOUT = 300


class LLMError(Exception):
    """Модель не ответила или ответила ошибкой."""


class LLMProvider(Protocol):
    """Провайдер языковой модели. Меняется целиком, не по частям."""

    def complete(self, prompt: str) -> str: ...


class ClaudeCodeProvider:
    """Claude Code в headless-режиме на подписке коуча."""

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._model = model
        self._timeout = timeout

    def _command(self, prompt: str) -> list[str]:
        command = [BINARY, "-p", prompt, "--output-format", "json"]
        if self._model:
            command += ["--model", self._model]
        return command

    def complete(self, prompt: str) -> str:
        try:
            completed = subprocess.run(
                self._command(prompt),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(
                f"{BINARY} не найден: интерпретация недоступна, "
                f"черновик придётся написать вручную"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f"{BINARY} не ответил за {self._timeout} с"
            ) from exc

        if completed.returncode != 0:
            raise LLMError(
                f"{BINARY} завершился с кодом {completed.returncode}: "
                f"{completed.stderr.strip() or 'без сообщения'}"
            )

        try:
            body = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"ответ {BINARY} не разобран как JSON: {exc}") from exc

        answer = str(body.get("result", ""))
        if body.get("is_error"):
            raise LLMError(f"модель вернула ошибку: {answer or 'без сообщения'}")
        if not answer.strip():
            raise LLMError("модель вернула пустой ответ")
        return answer
