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
        self.kwargs = None

    def __call__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return self


def test_answer_is_taken_from_the_result_field(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "Ответ модели"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    assert ClaudeCodeProvider().complete("вопрос") == "Ответ модели"


def test_prompt_is_delivered_via_stdin_not_argv(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "ок"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    ClaudeCodeProvider().complete("вопрос")

    assert "-p" in run.command
    assert "--output-format" in run.command
    assert "вопрос" not in run.command
    assert run.kwargs["input"] == "вопрос"


def test_prompt_starting_with_dashes_is_delivered_unchanged(monkeypatch):
    """Позиционный токен с "-" claude принял бы за неизвестный флаг —
    поэтому промпт не может попадать в argv ни в каком виде."""
    prompt = "--this-is-not-a-real-flag-zzz"
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "ок"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    ClaudeCodeProvider().complete(prompt)

    assert prompt not in run.command
    assert run.kwargs["input"] == prompt


def test_prompt_with_newlines_and_quotes_survives(monkeypatch):
    prompt = 'первая строка\nвторая "строка" с \'кавычками\''
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "ок"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    ClaudeCodeProvider().complete(prompt)

    assert run.kwargs["input"] == prompt


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


def test_null_result_is_refused(monkeypatch):
    """JSON null не должен превращаться в текстовую строку "None"."""
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": None}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не строка"):
        ClaudeCodeProvider().complete("вопрос")


def test_non_string_result_is_refused(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": ["x"]}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не строка"):
        ClaudeCodeProvider().complete("вопрос")


def test_non_object_body_is_refused(monkeypatch):
    run = FakeRun(stdout=json.dumps([1, 2, 3]))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не объект"):
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
