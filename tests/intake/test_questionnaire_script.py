# -*- coding: utf-8 -*-
"""Скрипт страницы-опросника исполняется по-настоящему, а не ищется в тексте.

Сохранение прогресса — единственное, что отделяет клиента от потери часов
работы, и живёт оно целиком в javascript. Проверка подстрокой («есть ли в
файле слово localStorage») не отличает работающий код от вычеркнутого:
исходная пропажа ответов на телефоне такую проверку проходила.

Заглушка браузера — `tests/intake/js/harness.js`: она собирает дерево из
той самой разметки, которую выдал генератор, исполняет скрипт и
возвращает, что получилось.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from healthcoach.intake.questionnaire_html import render_questionnaire
from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
)

HARNESS = Path(__file__).parent / "js" / "harness.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="нет node — скрипт страницы не исполнить",
)


def _questionnaire(count: int = 3) -> Questionnaire:
    scale = (
        ScaleOption(score=0, label="нет"),
        ScaleOption(score=1, label="иногда"),
        ScaleOption(score=2, label="часто"),
    )
    questions = tuple(
        Question(
            id=f"blok.a.{number}",
            number=number,
            text=f"вопрос {number}",
            scale=None,
            block_scale=scale,
        )
        for number in range(1, count + 1)
    )
    block = Block(
        id="blok",
        title="Блок",
        part="1",
        core=True,
        scale=scale,
        questions=questions,
        subscales=(
            Subscale(
                id="a",
                title="Шкала",
                question_ids=tuple(q.id for q in questions),
                thresholds=(),
            ),
        ),
    )
    return Questionnaire(version="тест-1", blocks=(block,))


@pytest.fixture
def questionnaire() -> Questionnaire:
    return _questionnaire()


@pytest.fixture
def long_questionnaire() -> Questionnaire:
    """Напоминание приходит после пятнадцати несохранённых ответов, поэтому
    трёх вопросов для него мало: на трёх вопросах видно только то, что
    пятнадцать нажатий — это не пятнадцать ответов."""
    return _questionnaire(20)


def _script_of(page: str) -> str:
    found = re.search(r"<script>\n(.*)</script>", page, re.S)
    assert found, "в странице нет скрипта"
    return found.group(1)


def run(page: str, plan: dict, tmp_path: Path) -> dict:
    (tmp_path / "page.html").write_text(page, encoding="utf-8")
    (tmp_path / "script.js").write_text(_script_of(page), encoding="utf-8")
    (tmp_path / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )
    done = subprocess.run(
        [
            "node",
            str(HARNESS),
            str(tmp_path / "page.html"),
            str(tmp_path / "script.js"),
            str(tmp_path / "plan.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def answers_file(client: str, spec: str, answers: dict) -> str:
    return json.dumps(
        {
            "версия": "1.1",
            "клиент": client,
            "спецификация": spec,
            "блоки": ["blok"],
            "ответы": answers,
        },
        ensure_ascii=False,
    )


def test_saved_file_brings_the_answers_back(questionnaire, tmp_path):
    """Главное: ответы возвращаются из файла — путь, который переживает
    закрытие страницы на телефоне, в отличие от хранилища браузера."""
    page = render_questionnaire(questionnaire, "CL-0417")
    saved = run(page, {"steps": [{"answer": ["blok.a.1", 2]}, {"download": True}]},
                tmp_path)
    assert saved["saved"], "файл не собрался"

    back = run(page, {"steps": [{"load": saved["saved"]}]}, tmp_path)
    assert back["checked"] == ["blok.a.1=2"]
    assert "Загружено ответов: 1" in back["warning"]


def test_loading_a_draft_does_not_erase_newer_answers(questionnaire, tmp_path):
    """Клиент мог ответить на пару вопросов до того, как вспомнил про файл.
    Загрузка черновика дополняет, а не стирает: терять эти ответы незачем."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "steps": [
                {"answer": ["blok.a.2", 1]},
                {"load": answers_file("CL-0417", "тест-1", {"blok.a.1": 2})},
            ]
        },
        tmp_path,
    )
    assert sorted(result["checked"]) == ["blok.a.1=2", "blok.a.2=1"]


def test_another_clients_file_is_refused(questionnaire, tmp_path):
    """Ответы одного человека в опроснике другого — то, о чём специалист
    узнал бы в лучшем случае по несуразным находкам."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"steps": [{"load": answers_file("CL-0999", "тест-1", {"blok.a.1": 2})}]},
        tmp_path,
    )
    assert result["checked"] == []
    assert "CL-0999" in result["warning"]
    assert result["warningKind"] == "warn"


def test_a_file_from_another_questionnaire_version_is_refused(
    questionnaire, tmp_path
):
    """Вопросы могли измениться: тот же идентификатор мог получить другой
    смысл, и перенос ответа подставил бы балл не туда."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"steps": [{"load": answers_file("CL-0417", "другая", {"blok.a.1": 2})}]},
        tmp_path,
    )
    assert result["checked"] == []
    assert "другой версии" in result["warning"]


def test_a_file_that_is_not_answers_is_refused_without_a_crash(
    questionnaire, tmp_path
):
    page = render_questionnaire(questionnaire, "CL-0417")
    for text in ("не json вовсе", json.dumps({"что-то": 1})):
        result = run(page, {"steps": [{"load": text}]}, tmp_path)
        assert result["checked"] == []
        assert result["warning"], "молчаливого отказа быть не должно"


def test_answers_for_questions_that_are_not_here_are_counted_not_dropped(
    questionnaire, tmp_path
):
    """Молча проглотить лишние ответы нельзя: клиент должен понять, что
    файл подошёл не целиком."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "steps": [
                {
                    "load": answers_file(
                        "CL-0417", "тест-1", {"blok.a.1": 2, "чужой.вопрос": 1}
                    )
                }
            ]
        },
        tmp_path,
    )
    assert result["checked"] == ["blok.a.1=2"]
    assert "Не подошло: 1" in result["warning"]


def test_phone_is_told_upfront_that_progress_may_not_survive(
    questionnaire, tmp_path
):
    """Страница, открытая из мессенджера, живёт по file://. Обещать там
    сохранность нельзя — об этом говорится до того, как ответы пропали."""
    page = render_questionnaire(questionnaire, "CL-0417")
    phone = run(page, {"protocol": "file:", "steps": []}, tmp_path)
    assert "Телефон может забыть прогресс" in phone["warning"]

    desktop = run(page, {"protocol": "http:", "steps": []}, tmp_path)
    assert desktop["warningHidden"], "на обычной странице пугать нечем"


def test_unsaved_answers_are_nudged_on_a_phone(long_questionnaire, tmp_path):
    """Напоминание приходит по мере накопления, а не раз в начале: за
    пятнадцать ответов клиент успевает забыть предупреждение."""
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    result = run(page, {"protocol": "file:", "steps": steps}, tmp_path)
    assert "Сохраните файл" in result["warning"]
    assert "15" in result["warning"]


def test_the_nudge_counts_answers_not_taps(questionnaire, tmp_path):
    """Пятнадцать касаний одного вопроса — один ответ. «Накопилось 15
    ответов» рядом с «Отвечено 1 из 3» было неправдой, а неправда здесь
    стоит дороже молчания: ей перестают верить."""
    page = render_questionnaire(questionnaire, "CL-0417")
    steps = [{"answer": ["blok.a.1", 1]}] * 15
    result = run(page, {"protocol": "file:", "steps": steps}, tmp_path)
    assert result["progress"] == "Отвечено 1 из 3"
    assert "Сохраните файл" not in result["warning"]


def test_saving_resets_the_nudge(long_questionnaire, tmp_path):
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    result = run(
        page, {"protocol": "file:", "steps": steps + [{"download": True}]}, tmp_path
    )
    assert "Сохраните файл" not in result["warning"]
    assert "ответы-CL-0417.json" in result["warning"]


def test_saving_restarts_the_count_of_unsaved_answers(
    long_questionnaire, tmp_path
):
    """После сохранения счёт начинается заново: иначе напоминание приходит
    на каждый следующий ответ и перестаёт что-либо значить."""
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    steps += [{"download": True}, {"answer": ["blok.a.16", 1]}]
    result = run(page, {"protocol": "file:", "steps": steps}, tmp_path)
    assert "Сохраните файл" not in result["warning"], (
        "счёт несохранённого не начался заново"
    )


def test_download_survives_phone_browsers(questionnaire, tmp_path):
    """Часть браузеров телефона не скачивает по ссылке вне документа и
    обрывает скачивание, если адрес отозвать в тот же миг."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(page, {"steps": [{"answer": ["blok.a.1", 2]}, {"download": True}]},
                 tmp_path)
    (download,) = result["downloads"]
    assert download["inDom"], "ссылка не попала в документ"
    assert download["name"] == "ответы-CL-0417.json"
    assert result["revoked"] == 0, "адрес отозван слишком рано"


def test_broken_storage_does_not_stop_the_questionnaire(questionnaire, tmp_path):
    """Приватный режим и переполненная квота не должны мешать заполнять:
    путь через файл остаётся."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"storageThrows": True, "steps": [{"answer": ["blok.a.1", 2]}]},
        tmp_path,
    )
    assert result["checked"] == ["blok.a.1=2"]
    assert "не запоминает" in result["warning"]


def test_progress_and_marks_follow_the_answers(questionnaire, tmp_path):
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"steps": [{"answer": ["blok.a.1", 2]}, {"answer": ["blok.a.3", 0]}]},
        tmp_path,
    )
    assert result["progress"] == "Отвечено 2 из 3"
    assert result["done"] == 2


def test_the_picker_is_reset_so_the_same_file_can_be_chosen_twice(
    questionnaire, tmp_path
):
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"steps": [{"load": answers_file("CL-0417", "тест-1", {"blok.a.1": 2})}]},
        tmp_path,
    )
    assert result["pickerReset"]


def test_the_file_picker_does_not_filter_by_extension(questionnaire):
    """Фильтр на телефоне чаще мешает, чем помогает: Safari сохраняет
    скачанное то с расширением, то без, и файл, который страница сама и
    выдала, оказывался бы недоступен. Содержимое проверяется целиком —
    фильтровать нечего."""
    page = render_questionnaire(questionnaire, "CL-0417")
    picker = re.search(r'<input type="file" id="picker"[^>]*>', page)
    assert picker, "выборщика файла нет"
    assert "accept" not in picker.group(0)


def test_continue_opens_the_file_picker(questionnaire, tmp_path):
    """«Продолжить» — единственный вход в восстановление. Кнопка невидимого
    выборщика не нажимает сама себя: без этой проводки клиент не может
    вернуть заполненное, а кроме неё об этом сказать некому."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(page, {"steps": [{"cancel": True}]}, tmp_path)
    assert result["pickerOpened"] == 1, "кнопка не дошла до выборщика файла"
    assert not result["crashed"]


def test_closing_the_picker_without_a_file_changes_nothing(questionnaire, tmp_path):
    """Диалог закрыли, файл не выбрали: это не повод терять ответы или
    пугать клиента."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"protocol": "http:", "steps": [{"answer": ["blok.a.1", 2]}, {"cancel": True}]},
        tmp_path,
    )
    assert result["checked"] == ["blok.a.1=2"]
    assert result["warningHidden"]


def test_the_blob_address_is_released_only_much_later(questionnaire, tmp_path):
    """Часть браузеров телефона обрывает скачивание, если адрес отозвать в
    тот же миг. Отзыв отложен — и всё же случается, а не теряется."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(page, {"steps": [{"download": True}]}, tmp_path)
    assert result["revoked"] == 0, "адрес отозван слишком рано"
    assert result["timerDelays"] == [60000]

    drained = run(page, {"steps": [{"download": True}, {"timers": True}]}, tmp_path)
    assert drained["revoked"] == 1, "адрес не освобождается никогда"


def _storage_key(questionnaire, tmp_path) -> str:
    """Ключ хранилища спрашивается у самой страницы: тест не должен знать,
    как он собран, иначе проверка версии в ключе окажется проверкой
    совпадения двух строк, списанных друг с друга."""
    page = render_questionnaire(questionnaire, "CL-0417")
    first = run(page, {"steps": [{"answer": ["blok.a.1", 2]}]}, tmp_path)
    (key,) = first["stored"].keys()
    return key


def test_storage_holds_the_same_thing_as_the_file(questionnaire, tmp_path):
    """Хранилище и файл — один формат и одни проверки. Пока в хранилище
    лежали голые ответы, применить их можно было только вслепую: ни чей
    они, ни от какой версии опросника, узнать было не из чего."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(page, {"steps": [{"answer": ["blok.a.1", 2]}]}, tmp_path)
    (key,) = result["stored"].keys()
    kept = json.loads(result["stored"][key])
    assert kept["клиент"] == "CL-0417"
    assert kept["спецификация"] == "тест-1"
    assert kept["ответы"] == {"blok.a.1": 2}
    assert "тест-1" in key, "версия опросника не попала в ключ хранилища"


def test_storage_from_another_questionnaire_version_is_not_applied(
    questionnaire, tmp_path
):
    """Проверено в WebKit: ответы от другой версии опросника молча
    применялись, и неверные баллы доходили до отчёта. Файл такое отвергал,
    хранилище — нет."""
    page = render_questionnaire(questionnaire, "CL-0417")
    key = _storage_key(questionnaire, tmp_path)
    stale = answers_file("CL-0417", "другая", {"blok.a.1": 2})
    result = run(page, {"storage": {key: stale}, "steps": []}, tmp_path)
    assert result["checked"] == [], "ответы от другой версии встали в опросник"
    assert "другой версии" in result["warning"]


def test_storage_from_another_client_is_not_applied(questionnaire, tmp_path):
    page = render_questionnaire(questionnaire, "CL-0417")
    key = _storage_key(questionnaire, tmp_path)
    alien = answers_file("CL-0999", "тест-1", {"blok.a.1": 2})
    result = run(page, {"storage": {key: alien}, "steps": []}, tmp_path)
    assert result["checked"] == []
    assert "CL-0999" in result["warning"]


def test_storage_that_is_not_readable_points_at_continue(questionnaire, tmp_path):
    """«Придётся заполнить заново» больше не правда: файл ответов
    возвращает заполненное."""
    page = render_questionnaire(questionnaire, "CL-0417")
    key = _storage_key(questionnaire, tmp_path)
    result = run(page, {"storage": {key: "не json вовсе"}, "steps": []}, tmp_path)
    assert "заново" not in result["warning"]
    assert "Продолжить" in result["warning"]


def test_storage_reports_answers_that_did_not_fit(questionnaire, tmp_path):
    """Счёт неподошедших ответов из хранилища выбрасывался: вопросы могли
    исчезнуть из опросника, а клиент об этом не узнавал."""
    page = render_questionnaire(questionnaire, "CL-0417")
    key = _storage_key(questionnaire, tmp_path)
    mixed = answers_file("CL-0417", "тест-1", {"blok.a.1": 2, "чужой.вопрос": 1})
    result = run(page, {"storage": {key: mixed}, "steps": []}, tmp_path)
    assert result["checked"] == ["blok.a.1=2"]
    assert "Не подошло: 1" in result["warning"]


def test_an_answer_on_screen_is_never_replaced_by_the_file(questionnaire, tmp_path):
    """«Слияние» обещало не терять свежие ответы, но варианты одного
    вопроса снимают друг друга: старый черновик молча заменял ответ,
    который клиент только что дал."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "steps": [
                {"answer": ["blok.a.1", 2]},
                {"load": answers_file(
                    "CL-0417", "тест-1", {"blok.a.1": 0, "blok.a.2": 1})},
            ]
        },
        tmp_path,
    )
    assert sorted(result["checked"]) == ["blok.a.1=2", "blok.a.2=1"]
    assert "Загружено ответов: 1" in result["warning"]
    assert "1" in result["warning"] and "экране" in result["warning"]


def test_a_strange_value_in_the_file_does_not_break_the_load(
    questionnaire, tmp_path
):
    """Балл подставлялся в селектор без экранирования. Кавычка в чужом или
    испорченном файле роняла загрузку на середине, и клиент видел прежнюю
    подсказку, как будто ничего не случилось."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "steps": [
                {"load": answers_file(
                    "CL-0417", "тест-1", {"blok.a.1": '2"]', "blok.a.2": 1})},
            ]
        },
        tmp_path,
    )
    assert not result["crashed"], "загрузка умерла молча: " + str(result["crashed"])
    assert result["checked"] == ["blok.a.2=1"]
    assert "Не подошло: 1" in result["warning"]


def test_a_failure_inside_the_load_is_told_to_the_client(questionnaire, tmp_path):
    """Бросок внутри чтения файла никому не передаётся: страница остаётся с
    наполовину применённой загрузкой, а на экране висит прежнее сообщение.
    Молчания быть не должно."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "breakTreeAt": 2,
            "steps": [{"load": answers_file("CL-0417", "тест-1", {"blok.a.1": 2})}],
        },
        tmp_path,
    )
    assert not result["crashed"], "сбой не поймали: " + str(result["crashed"])
    assert "не удалось" in result["warning"] or "Сбой" in result["warning"]
    assert result["warningKind"] == "warn"


def test_the_file_goes_through_the_share_sheet_when_there_is_one(
    questionnaire, tmp_path
):
    """В встроенном браузере мессенджера скачивания часто нет вовсе: клик по
    ссылке не делает ничего и об этом не сообщает — ровно то окружение, для
    которого всё и затевалось. Лист отправки отдаёт файл прямо в чат."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "canShare": True,
            "steps": [{"answer": ["blok.a.1", 2]}, {"download": True}],
        },
        tmp_path,
    )
    (sent,) = result["shared"]
    assert sent["name"] == "ответы-CL-0417.json"
    assert json.loads(sent["text"])["ответы"] == {"blok.a.1": 2}
    assert result["downloads"] == [], "файл ушёл дважды"
    assert "отправлен" in result["warning"]
    assert result["warningKind"] == "hint"


def test_a_cancelled_share_is_not_called_saved(long_questionnaire, tmp_path):
    """Лист отправки можно закрыть, не отправив. Это не сохранение, и
    говорить о сохранении не о чем: ответы остались только на странице."""
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    result = run(
        page,
        {
            "canShare": True,
            "shareFails": True,
            "protocol": "file:",
            "steps": steps + [{"download": True}, {"answer": ["blok.a.16", 1]}],
        },
        tmp_path,
    )
    assert "Сохраните файл" in result["warning"], (
        "непрошедшая отправка сошла за сохранение"
    )


def test_download_does_not_promise_what_it_cannot_check(questionnaire, tmp_path):
    """Страница не может узнать, что браузер скачал файл. Прежнее зелёное
    «Файл сохранён» было обещанием, которого код не держит: при сломанном
    хранилище клиент отвечал дальше под надписью «сохранено» и терял всё."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {"steps": [{"answer": ["blok.a.1", 2]}, {"download": True}]},
        tmp_path,
    )
    assert "сохранён" not in result["warning"]
    assert "загрузк" in result["warning"], "клиенту не сказано, что проверить"
    assert result["warningKind"] == "warn"


def test_saving_does_not_erase_the_broken_storage_warning(questionnaire, tmp_path):
    """Отказ переживает подсказки: он единственная причина, по которой
    клиент вообще нажмёт «Сохранить ответы»."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "storageThrows": True,
            "steps": [{"answer": ["blok.a.1", 2]}, {"download": True}],
        },
        tmp_path,
    )
    assert "не запоминает" in result["warning"]
    assert result["warningKind"] == "warn"


def test_the_nudge_does_not_erase_the_broken_storage_warning(
    long_questionnaire, tmp_path
):
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    result = run(
        page,
        {"storageThrows": True, "protocol": "file:", "steps": steps},
        tmp_path,
    )
    assert "не запоминает" in result["warning"]
    assert "Сохраните файл" in result["warning"]


def test_a_green_message_does_not_outlive_the_next_answer(questionnaire, tmp_path):
    """После загрузки зелёное «загружено» висело, пока копились
    несохранённые ответы: сообщение о прошлом действии перестаёт быть
    правдой, как только появился новый ответ."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "steps": [
                {"load": answers_file("CL-0417", "тест-1", {"blok.a.1": 2})},
                {"answer": ["blok.a.2", 1]},
            ]
        },
        tmp_path,
    )
    assert "Загружено" not in result["warning"]
    assert result["warningHidden"]


def test_answers_that_came_from_the_file_are_not_counted_as_unsaved(
    long_questionnaire, tmp_path
):
    """Клиент только что загрузил свой файл — требовать сохранить его
    обратно не за что: эти ответы в файле и лежат."""
    page = render_questionnaire(long_questionnaire, "CL-0417")
    answers = {f"blok.a.{n}": 1 for n in range(1, 16)}
    result = run(
        page,
        {
            "protocol": "file:",
            "steps": [
                {"load": answers_file("CL-0417", "тест-1", answers)},
                {"answer": ["blok.a.16", 1]},
            ],
        },
        tmp_path,
    )
    assert result["progress"] == "Отвечено 16 из 20"
    assert "Сохраните файл" not in result["warning"]


def test_a_sent_file_restarts_the_count_of_unsaved_answers(
    long_questionnaire, tmp_path
):
    """Отправленный файл — единственное, про что страница знает наверняка:
    он ушёл, и счёт несохранённого начинается заново."""
    page = render_questionnaire(long_questionnaire, "CL-0417")
    steps = [{"answer": [f"blok.a.{n}", 1]} for n in range(1, 16)]
    steps += [{"download": True}, {"answer": ["blok.a.16", 1]}]
    result = run(
        page, {"canShare": True, "protocol": "file:", "steps": steps}, tmp_path
    )
    assert "Сохраните файл" not in result["warning"]


def test_a_share_sheet_that_does_not_work_falls_back_to_a_download(
    questionnaire, tmp_path
):
    """Встроенный браузер может объявить лист отправки и не справиться.
    Отказ человека и неработающая отправка — разные вещи: во втором случае
    остаться без файла нельзя, иначе «Сохранить ответы» не делает ничего и
    молчит об этом — то самое, ради чего всё затевалось."""
    page = render_questionnaire(questionnaire, "CL-0417")
    result = run(
        page,
        {
            "canShare": True,
            "shareBroken": True,
            "steps": [{"answer": ["blok.a.1", 2]}, {"download": True}],
        },
        tmp_path,
    )
    assert len(result["shared"]) == 1, "отправку даже не попробовали"
    (download,) = result["downloads"]
    assert download["name"] == "ответы-CL-0417.json"
    assert download["inDom"]
    assert json.loads(result["saved"])["ответы"] == {"blok.a.1": 2}
    assert "загрузк" in result["warning"]
