"""Генератор автономного HTML-опросника для клиента.

Один файл без внешних ссылок: коуч отправляет его в мессенджере, клиент
открывает в браузере, в том числе на телефоне. По завершении клиент
скачивает JSON и присылает его обратно.

Заполнение идёт за несколько подходов, и хранилище браузера на телефоне
этого не переживает: страница, открытая из мессенджера, живёт по адресу
file:// — встроенный просмотрщик заводит хранилище заново на каждый
показ. Поэтому надёжный способ вернуться к заполненному здесь один —
тот же файл ответов: страница умеет не только его отдавать, но и
загружать обратно. Отдаёт она его листом отправки, если он есть, — в
встроенном браузере мессенджера скачивания может не быть вовсе, а лист
отправки ещё и сообщает, что файл ушёл. Память браузера осталась быстрым
путём там, где она работает, но обещаний на ней больше не строится, и
применяется сохранённое по тем же проверкам, что файл.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from healthcoach.knowledge.questionnaire import Block, Questionnaire

PAYLOAD_VERSION = "1.1"
"""1.1 добавила ключ «блоки»: без него нельзя отличить вопрос, который
клиент пропустил, от вопроса, который ему не показывали."""


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
.actions { display: flex; gap: .5rem; }
#warning { flex-basis: 100%; order: -1; margin: 0; font-size: .9rem;
           padding: .5rem .7rem; border-radius: .3rem; }
#warning.warn { background: #fff3cd; color: #4a3b00; }
#warning.hint { background: #e8f2e8; color: #2d5a3d; }
#warning[hidden] { display: none; }
"""

_SCRIPT = """
// Версия опросника — часть ключа: вопрос мог поменять смысл, сохранив
// идентификатор, и ответы прошлой версии превратились бы в баллы этой.
const KEY = 'healthcoach-' + CLIENT_CODE + '-' + SPEC_VERSION;
const form = document.getElementById('form');

// Варианты каждого вопроса собираются один раз, по именам. Селектор,
// собранный из имени или балла, пришедшего из файла, — это либо брошенное
// исключение на кавычке, либо поиск не того, что искали; сравнить значение
// в коде и проще, и не бросает.
const groups = new Map();
for (const el of form.querySelectorAll('input[type=radio]')) {
  if (!groups.has(el.name)) groups.set(el.name, []);
  groups.get(el.name).push(el);
}

// Страница, открытая из мессенджера или «Файлов», живёт по адресу file://.
// Там браузер телефона хранилищу не хозяин: встроенный просмотрщик заводит
// его заново на каждый показ, а iOS вдобавок стирает хранилище страниц,
// которые не открывали неделю. Проверить это изнутри страницы нельзя —
// запись проходит успешно, пропажа обнаруживается лишь при следующем
// открытии, — поэтому обещать сохранность здесь нельзя, и файл ответов
// объявляется главным способом не потерять работу.
const FRAGILE = location.protocol === 'file:';
const NUDGE_AFTER = 15;

let storageBroken = false;

// Отказ — сломанная память браузера — не стирается подсказками и не
// отменяется ничем: подсказка приходит по ходу заполнения, а отказ остаётся
// единственной причиной, по которой клиент вообще нажмёт «Сохранить
// ответы». Поэтому он не замещается, а сопровождает всё остальное.
let refusal = '';

// Что уже лежит в файле у клиента. Несохранённое считается по ответам, а не
// по нажатиям: пятнадцать касаний одного вопроса — это один ответ, и
// «накопилось 15 ответов» рядом с «отвечено 1 из 3» было неправдой.
let inFile = new Map();

function say(text, kind) {
  const el = document.getElementById('warning');
  const full = text && refusal ? text + ' ' + refusal : (text || refusal);
  el.textContent = full;
  el.className = refusal ? 'warn' : (kind || 'warn');
  el.hidden = !full;
}

function noStorage() {
  storageBroken = true;
  refusal = 'Браузер не запоминает ответы: вернуться к заполненному можно ' +
            'только через файл — «Сохранить ответы», потом «Продолжить».';
  say('');
}

function snapshot(answers) {
  inFile = new Map();
  for (const name of Object.keys(answers)) {
    inFile.set(name, String(answers[name]));
  }
}

function unsavedCount() {
  const now = collect();
  let count = 0;
  for (const name of Object.keys(now)) {
    if (inFile.get(name) !== String(now[name])) count += 1;
  }
  return count;
}

function collect() {
  const data = {};
  for (const [name, options] of groups) {
    for (const el of options) {
      if (el.checked) data[name] = Number(el.value);
    }
  }
  return data;
}

function refresh() {
  const answered = Object.keys(collect()).length;
  document.getElementById('progress').textContent =
    'Отвечено ' + answered + ' из ' + groups.size;
  for (const q of form.querySelectorAll('.q')) {
    const options = groups.get(q.dataset.q) || [];
    q.classList.toggle('done', options.some((el) => el.checked));
  }
}

function save() {
  if (!storageBroken) {
    try {
      // В памяти браузера лежит то же, что в файле: иначе применить
      // сохранённое можно только вслепую — ни чьи это ответы, ни от какой
      // версии опросника, узнать не из чего.
      localStorage.setItem(KEY, JSON.stringify(payload()));
    } catch (e) {
      noStorage();
    }
  }
  // Сообщение о прошлом действии перестаёт быть правдой, как только появился
  // новый ответ: зелёное «загружено» висело на экране, пока рядом копились
  // несохранённые ответы.
  say('');
  const unsaved = unsavedCount();
  if (FRAGILE && unsaved >= NUDGE_AFTER) {
    say('Несохранённых ответов: ' + unsaved + '. Сохраните файл, чтобы не ' +
        'потерять их, если страница закроется.');
  }
  refresh();
}

function mismatch(data) {
  // Один ответ на один вопрос — можно ли применять этот набор ответов, — и
  // для файла, и для памяти браузера. Две проверки, решавшие это
  // по-разному, и привели к тому, что ответы прошлой версии опросника молча
  // становились баллами отчёта: файл такое отвергал, память — нет.
  if (!data || typeof data !== 'object' || typeof data["ответы"] !== 'object'
      || data["ответы"] === null) {
    return 'это не ответы этого опросника';
  }
  // Чужие ответы загружать нельзя: они оказались бы в опроснике другого
  // человека, и специалист узнал бы об этом в лучшем случае по несуразным
  // находкам.
  if (data["клиент"] && data["клиент"] !== CLIENT_CODE) {
    return 'они заполнены по другому опроснику (' + data["клиент"] + ')';
  }
  if (data["спецификация"] && data["спецификация"] !== SPEC_VERSION) {
    return 'они заполнены по другой версии опросника — вопросы могли ' +
           'измениться, и балл встал бы не туда';
  }
  return null;
}

function apply(answers) {
  // Ответ, который уже стоит на экране, не заменяется: вариант отмечается
  // взамен прежнего, поэтому старый черновик молча затирал бы ответ,
  // который клиент только что дал.
  let applied = 0;
  let kept = 0;
  let unknown = 0;
  for (const name of Object.keys(answers)) {
    const options = groups.get(name);
    if (!options) {
      unknown += 1;
    } else if (options.some((el) => el.checked)) {
      kept += 1;
    } else {
      const wanted = options.filter(
        (el) => String(el.value) === String(answers[name]));
      if (wanted.length) {
        wanted[0].checked = true;
        applied += 1;
      } else {
        unknown += 1;
      }
    }
  }
  return { applied: applied, kept: kept, unknown: unknown };
}

function tale(result, lead) {
  let text = lead + ': ' + result.applied + '.';
  if (result.kept) {
    text += ' Оставлено как на экране: ' + result.kept +
            ' — отвеченное здесь и сейчас важнее сохранённого.';
  }
  if (result.unknown) {
    text += ' Не подошло: ' + result.unknown +
            ' — таких вопросов или таких ответов в опроснике нет.';
  }
  return text;
}

function restore() {
  let raw = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch (e) {
    noStorage();
    return refresh();
  }
  if (!raw) {
    if (FRAGILE) {
      say('Телефон может забыть прогресс, когда страница закроется. ' +
          'Сохраняйте файл ответов — через «Продолжить» вы вернётесь ' +
          'к заполненному.', 'hint');
    }
    return refresh();
  }
  let data = null;
  try {
    data = JSON.parse(raw);
  } catch (e) {
    data = null;
  }
  const why = mismatch(data);
  if (why) {
    say('Сохранённое в браузере не подошло: ' + why + '. Нажмите ' +
        '«Продолжить» и выберите файл ответов — заполненное встанет ' +
        'на место.');
    return refresh();
  }
  const result = apply(data["ответы"]);
  refresh();
  let text = tale(result, 'Вернулось ответов из памяти браузера');
  if (FRAGILE) {
    text += ' Браузер телефона может их забыть — сохраните файл ответов.';
  }
  say(text, result.unknown ? 'warn' : 'hint');
}

function payload() {
  // Ключи в двойных кавычках намеренно: страница сама объявляет формат,
  // который потом разбирает импорт, и тест ищет это объявление в тексте файла.
  return {
    "версия": PAYLOAD_VERSION,
    "клиент": CLIENT_CODE,
    "спецификация": SPEC_VERSION,
    "блоки": SHOWN_BLOCKS,
    "ответы": collect(),
  };
}

function download() {
  const data = payload();
  const text = JSON.stringify(data, null, 2);
  const name = 'ответы-' + CLIENT_CODE + '.json';
  const file = shareable(name, text);
  if (file) return handOver(file, name, text, data["ответы"]);
  deliver(name, text, data["ответы"]);
}

function shareable(name, text) {
  // В встроенном браузере мессенджера скачивания часто нет вовсе: клик по
  // ссылке не делает ничего и об этом не сообщает — а это и есть то
  // окружение, ради которого всё затевалось. Лист отправки на телефоне
  // отдаёт файл прямо в чат, и он единственный путь, про который страница
  // узнаёт, что файл действительно ушёл.
  if (typeof navigator === 'undefined' || !navigator.canShare
      || typeof File !== 'function') {
    return null;
  }
  try {
    const file = new File([text], name, { type: 'application/json' });
    return navigator.canShare({ files: [file] }) ? file : null;
  } catch (e) {
    return null;
  }
}

function handOver(file, name, text, answers) {
  const answered = Object.keys(answers).length;
  navigator.share({ files: [file], title: name }).then(function () {
    snapshot(answers);
    say('Файл с ' + answered + ' ответами отправлен. Сохраните его у себя: ' +
        'через «Продолжить» он вернёт заполненное.', 'hint');
  }, function (e) {
    // Отказ человека и неработающая отправка — разные вещи. Закрыли лист
    // отправки — AbortError, и сохранением это не стало. А вот встроенный
    // браузер, объявивший отправку и не справившийся, не повод оставить
    // клиента без файла: иначе «Сохранить ответы» снова ничего не делает и
    // молчит об этом.
    if (e && e.name === 'AbortError') {
      return say('Файл не отправлен. Ответы остались только на этой ' +
                 'странице — нажмите «Сохранить ответы» ещё раз.');
    }
    deliver(name, text, answers);
  });
}

function deliver(name, text, answers) {
  const blob = new Blob([text], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  // Ссылка добавляется в документ, а адрес освобождается не сразу: часть
  // браузеров телефона не скачивает по ссылке вне документа и обрывает
  // скачивание, если адрес отозвать в тот же миг.
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
  snapshot(answers);
  // Что файл скачался, страница проверить не может: браузер мог не начать
  // скачивание и ничего об этом не сказать. Поэтому не «сохранено», а что
  // проверить и что делать дальше.
  say('Файл ' + name + ' с ' + Object.keys(answers).length +
      ' ответами передан браузеру. Проверьте, что он появился в загрузках, ' +
      'и пришлите его специалисту, когда закончите.');
}

function load(file) {
  const reader = new FileReader();
  reader.onerror = function () {
    say('Файл не прочитался. Попробуйте выбрать его ещё раз.');
  };
  reader.onload = function () {
    // Чтение заканчивается отдельным оборотом цикла событий: бросок отсюда
    // не поймает никто, загрузка останется сделанной наполовину, а на
    // экране — прежняя подсказка, как будто ничего не случилось.
    try {
      accept(reader.result);
    } catch (e) {
      refresh();
      say('Загрузить файл не удалось: ' + ((e && e.message) || e) +
          '. Ответы могли встать не полностью — проверьте экран и ' +
          'выберите файл ещё раз.');
    }
  };
  try {
    reader.readAsText(file);
  } catch (e) {
    say('Файл не прочитался. Попробуйте выбрать его ещё раз.');
  }
}

function accept(text) {
  let data = null;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return say('Это не файл ответов: он не читается как JSON.');
  }
  const why = mismatch(data);
  if (why) {
    return say('Файл не подошёл: ' + why + '. Возьмите последний файл ' +
               'ответов этого опросника.');
  }
  const result = apply(data["ответы"]);
  refresh();
  // Ответы из файла в файле и лежат; несохранённым остаётся то, что
  // оставлено как на экране.
  snapshot(data["ответы"]);
  say(tale(result, 'Загружено ответов'), result.unknown ? 'warn' : 'hint');
}

form.addEventListener('change', save);
document.getElementById('download').addEventListener('click', download);
const picker = document.getElementById('picker');
document.getElementById('continue').addEventListener('click', function () {
  picker.click();
});
picker.addEventListener('change', function () {
  if (picker.files && picker.files[0]) load(picker.files[0]);
  // Сброс: иначе повторный выбор того же файла не вызовет события.
  picker.value = '';
});
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
        # Подгруппы перекрываются: у Candida есть «всего», перечисляющая все
        # вопросы блока. Без учёта уже показанных клиент проходил бы их дважды.
        # Сводные подгруппы идут последними независимо от порядка в спецификации:
        # иначе сводная, оказавшись первой, забрала бы себе весь блок и
        # настоящие заголовки частей исчезли бы.
        rendered: set[str] = set()
        whole = {q.id for q in block.questions}
        subscales = sorted(
            block.subscales, key=lambda sub: set(sub.question_ids) >= whole
        )
        for subscale in subscales:
            ids = set(subscale.question_ids)
            questions = [
                q for q in block.questions if q.id in ids and q.id not in rendered
            ]
            if not questions:
                continue
            rendered.update(q.id for q in questions)
            if multi:
                parts.append(f"<h3>{html.escape(subscale.title)}</h3>")
            parts.extend(_render_question(q, subscale.title) for q in questions)
        sections.append("\n".join(parts))

    shown = [block.id for block in blocks]
    script = (
        f"const CLIENT_CODE = {json.dumps(client_code, ensure_ascii=False)};\n"
        f"const SPEC_VERSION = {json.dumps(questionnaire.version)};\n"
        f"const PAYLOAD_VERSION = {json.dumps(PAYLOAD_VERSION)};\n"
        f"const SHOWN_BLOCKS = {json.dumps(shown, ensure_ascii=False)};\n"
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
        "Заполнять можно за несколько подходов: нажмите «Сохранить ответы» — "
        "телефон предложит отправить файл или положит его в загрузки. Когда "
        "вернётесь, откройте опросник снова и нажмите «Продолжить»: выберите "
        "этот файл, и заполненное встанет на место. Последний файл ответов "
        "пришлите специалисту.</p>"
        f'<form id="form">{"".join(sections)}</form>'
        "</main>"
        '<div class="bar"><p id="warning" hidden></p>'
        '<span id="progress"></span>'
        '<span class="actions">'
        '<input type="file" id="picker" hidden>'
        # Без accept: на телефоне фильтр чаще мешает, чем помогает.
        # Safari сохраняет скачанное то с расширением, то без, то
        # добавив своё, — и файл, который страница сама и выдала,
        # оказывался бы в выборщике недоступен. Содержимое всё равно
        # проверяется целиком: и что это JSON, и чей он, и от какой
        # версии опросника.
        '<button type="button" id="continue">Продолжить</button>'
        '<button type="button" id="download">Сохранить ответы</button>'
        "</span></div>"
        f"<script>\n{script}</script>"
        "</body></html>"
    )
