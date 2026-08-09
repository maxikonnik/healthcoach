import json
import sys

import pytest

from healthcoach.llm.provider import ClaudeCodeProvider, LLMError


class FakeRun:
    """Подмена subprocess.run: отдаёт заранее известный результат."""

    def __init__(self, stdout="", stderr="", returncode=0, raises=None):
        self.stdout, self.stderr, self.returncode, self.raises = (
            stdout, stderr, returncode, raises,
        )
        self.command = None

    def __call__(self, command, **kwargs):
        self.command = command
        if self.raises is not None:
            raise self.raises
        return self


def test_answer_is_taken_from_the_result_field(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "Ответ модели"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    assert ClaudeCodeProvider().complete("вопрос") == "Ответ модели"


def test_prompt_is_passed_headless(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "ок"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    ClaudeCodeProvider().complete("вопрос")

    assert "-p" in run.command
    assert "вопрос" in run.command
    assert "--output-format" in run.command


def test_reported_error_is_refused(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": True, "result": "лимит исчерпан"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="лимит исчерпан"):
        ClaudeCodeProvider().complete("вопрос")


def test_non_zero_exit_is_refused(monkeypatch):
    run = FakeRun(stdout="", stderr="claude: not logged in", returncode=1)
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="not logged in"):
        ClaudeCodeProvider().complete("вопрос")


def test_unparseable_output_is_refused(monkeypatch):
    run = FakeRun(stdout="это не json")
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не разобран"):
        ClaudeCodeProvider().complete("вопрос")


def test_empty_answer_is_refused(monkeypatch):
    """Пустой ответ — не ответ; подставлять вместо него пустоту нельзя."""
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "   "}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="пустой"):
        ClaudeCodeProvider().complete("вопрос")


def test_missing_binary_is_refused(monkeypatch):
    run = FakeRun(raises=FileNotFoundError("claude"))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не найден"):
        ClaudeCodeProvider().complete("вопрос")


def test_timeout_is_refused(monkeypatch):
    import subprocess

    run = FakeRun(raises=subprocess.TimeoutExpired("claude", 300))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не ответил"):
        ClaudeCodeProvider().complete("вопрос")


@pytest.mark.llm
def test_real_call_returns_text():
    """Живой вызов. Пропускается, если claude не установлен или не авторизован."""
    import shutil

    if shutil.which("claude") is None:
        pytest.skip("claude не установлен")
    try:
        answer = ClaudeCodeProvider(timeout=120).complete(
            "Ответь ровно одним словом: работает"
        )
    except LLMError as exc:
        pytest.skip(f"живой вызов недоступен: {exc}")
    assert answer.strip()
