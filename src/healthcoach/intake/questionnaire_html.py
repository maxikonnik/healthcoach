"""Генератор автономного HTML-опросника для клиента.

Один файл без внешних ссылок: коуч отправляет его в мессенджере, клиент
открывает в браузере, в том числе на телефоне. Прогресс держится в
localStorage, чтобы можно было закрыть и вернуться. По завершении клиент
скачивает JSON и присылает его обратно.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from healthcoach.knowledge.questionnaire import Block, Questionnaire

PAYLOAD_VERSION = "1.0"


class QuestionnaireHtmlError(Exception):
    """Опросник под клиента собрать нельзя."""


_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 0 1rem 6rem;
       max-width: 44rem; margin-inline: auto; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.1rem; margin-top: 2.5rem; border-bottom: 1px solid;
     padding-bottom: .3rem; }
h3 { font-size: .95rem; font-weight: 600; opacity: .75; margin: 1.5rem 0 .5rem; }
.q { margin: 1.25rem 0; }
.q p { margin: 0 0 .4rem; }
.opts { display: grid; gap: .35rem; }
label { display: flex; gap: .5rem; align-items: flex-start; cursor: pointer; }
.bar { position: fixed; inset: auto 0 0 0; padding: .75rem 1rem;
       background: Canvas; border-top: 1px solid; display: flex; gap: 1rem;
       align-items: center; justify-content: space-between; flex-wrap: wrap; }
button { font: inherit; padding: .5rem 1rem; cursor: pointer; }
.done { opacity: .55; }
#warning { flex-basis: 100%; order: -1; margin: 0; font-size: .9rem;
           background: #fff3cd; color: #4a3b00; padding: .5rem .7rem;
           border-radius: .3rem; }
#warning[hidden] { display: none; }
"""

_SCRIPT = """
const KEY = 'healthcoach-' + CLIENT_CODE;
const form = document.getElementById('form');

function collect() {
  const data = {};
  for (const el of form.querySelectorAll('input[type=radio]:checked')) {
    data[el.name] = Number(el.value);
  }
  return data;
}

function total() {
  return new Set(
    [...form.querySelectorAll('input[type=radio]')].map((el) => el.name)
  ).size;
}

function refresh() {
  const answered = Object.keys(collect()).length;
  document.getElementById('progress').textContent =
    'Отвечено ' + answered + ' из ' + total();
  for (const q of form.querySelectorAll('.q')) {
    const name = q.dataset.q;
    q.classList.toggle('done', form.querySelector(
      'input[name="' + name + '"]:checked') !== null);
  }
}

// Хранилище может быть недоступно: приватный режим, переполненная квота,
// запрет сторонних данных. Молча потерять ответы клиента нельзя — он
// заполняет опросник за несколько подходов и узнает о потере слишком поздно.
let storageBroken = false;

function warn(text) {
  const el = document.getElementById('warning');
  el.textContent = text;
  el.hidden = false;
}

function noStorage() {
  storageBroken = true;
  warn('Браузер не сохраняет прогресс: не закрывайте страницу и нажмите ' +
       '«Скачать ответы», когда закончите.');
}

function save() {
  if (!storageBroken) {
    try {
      localStorage.setItem(KEY, JSON.stringify(collect()));
    } catch (e) {
      noStorage();
    }
  }
  refresh();
}

function restore() {
  let raw = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch (e) {
    noStorage();
    return refresh();
  }
  if (!raw) return refresh();
  let data = null;
  try {
    data = JSON.parse(raw);
  } catch (e) {
    data = null;
  }
  if (!data || typeof data !== 'object') {
    warn('Сохранённые ответы не читаются, придётся заполнить заново.');
    return refresh();
  }
  for (const [name, score] of Object.entries(data)) {
    const el = form.querySelector(
      'input[name="' + name + '"][value="' + score + '"]');
    if (el) el.checked = true;
  }
  refresh();
}

function download() {
  // Ключи в двойных кавычках намеренно: страница сама объявляет формат,
  // который потом разбирает импорт, и тест ищет это объявление в тексте файла.
  const payload = {
    "версия": PAYLOAD_VERSION,
    "клиент": CLIENT_CODE,
    "спецификация": SPEC_VERSION,
    "ответы": collect(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                        { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ответы-' + CLIENT_CODE + '.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

form.addEventListener('change', save);
document.getElementById('download').addEventListener('click', download);
restore();
"""


def _selected_blocks(
    questionnaire: Questionnaire, extra_block_ids: Sequence[str]
) -> list[Block]:
    by_id = {block.id: block for block in questionnaire.blocks}
    for block_id in extra_block_ids:
        if block_id not in by_id:
            raise QuestionnaireHtmlError(f"в спецификации нет блока {block_id!r}")
        if by_id[block_id].core:
            raise QuestionnaireHtmlError(
                f"блок {block_id!r} входит в ядро и включается всегда"
            )
    wanted = set(extra_block_ids)
    return [b for b in questionnaire.blocks if b.core or b.id in wanted]


def _render_question(question, subscale_title: str | None) -> str:
    options = "\n".join(
        f'<label><input type="radio" name="{html.escape(question.id)}" '
        f'value="{option.score}"><span>{html.escape(option.label)}</span></label>'
        for option in question.options()
    )
    return (
        f'<div class="q" data-q="{html.escape(question.id)}">'
        f"<p>{question.number}. {html.escape(question.text)}</p>"
        f'<div class="opts">{options}</div></div>'
    )


def render_questionnaire(
    questionnaire: Questionnaire,
    client_code: str,
    extra_block_ids: Sequence[str] = (),
) -> str:
    """Собрать автономный HTML-опросник под конкретного клиента."""
    blocks = _selected_blocks(questionnaire, extra_block_ids)

    sections: list[str] = []
    for block in blocks:
        parts = [f"<h2>{html.escape(block.title)}</h2>"]
        multi = len(block.subscales) > 1
        for subscale in block.subscales:
            ids = set(subscale.question_ids)
            questions = [q for q in block.questions if q.id in ids]
            if not questions:
                continue
            if multi:
                parts.append(f"<h3>{html.escape(subscale.title)}</h3>")
            parts.extend(_render_question(q, subscale.title) for q in questions)
        sections.append("\n".join(parts))

    script = (
        f"const CLIENT_CODE = {json.dumps(client_code, ensure_ascii=False)};\n"
        f"const SPEC_VERSION = {json.dumps(questionnaire.version)};\n"
        f"const PAYLOAD_VERSION = {json.dumps(PAYLOAD_VERSION)};\n"
        f"{_SCRIPT}"
    )

    return (
        "<!doctype html>\n"
        '<html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Опросник — {html.escape(client_code)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<main>"
        "<h1>Большой интегральный опросник</h1>"
        "<p>Отвечайте по своему состоянию за последний месяц. "
        "Прогресс сохраняется в браузере — можно закрыть страницу и вернуться. "
        "Когда закончите, нажмите «Скачать ответы» и пришлите файл специалисту.</p>"
        f'<form id="form">{"".join(sections)}</form>'
        "</main>"
        '<div class="bar"><p id="warning" hidden></p>'
        '<span id="progress"></span>'
        '<button type="button" id="download">Скачать ответы</button></div>'
        f"<script>{script}</script>"
        "</body></html>"
    )
