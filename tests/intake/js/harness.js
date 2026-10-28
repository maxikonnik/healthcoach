// Заглушка браузера для скрипта опросника.
//
// Скрипт страницы — единственное место, где живёт логика сохранения и
// загрузки ответов, и проверять её поиском подстрок в HTML бессмысленно:
// так не отличить работающую проверку чужого файла от вычеркнутой. Здесь
// скрипт исполняется по-настоящему, на разметке, которую сам генератор и
// выдал: заглушка собирает дерево из неё, а не из выдуманного образца.
//
// Заглушка обязана уметь краснеть. Поэтому здесь воспроизведено то, чем
// браузер отличается от удобного объекта: клик по «Продолжить» доходит до
// выборщика файла и возвращает выбранный файл с именем, радиокнопки одной
// группы снимают друг друга, чтение файла заканчивается отдельным оборотом
// цикла событий (а значит, бросок внутри onload уже никем не ловится), и
// setTimeout не теряет обратный вызов, а откладывает его до команды теста.

const fs = require('fs');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = fs.readFileSync(process.argv[3], 'utf8');
const plan = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

// --- разбор разметки ----------------------------------------------------

const inputs = [];
const inputRe = /<input type="radio" name="([^"]+)" value="([^"]+)"/g;
let m;
while ((m = inputRe.exec(html)) !== null) {
  inputs.push({ name: m[1], value: m[2], type: 'radio' });
}
if (!inputs.length) throw new Error('в разметке не нашлось ни одного ответа');

// Взаимное исключение в группе — не украшение: в браузере отметка варианта
// снимает прежнюю отметку того же вопроса. Без этого «слияние» ответов
// выглядит безобидным, хотя старый черновик затирает свежий ответ.
const checked = new Set();
for (const input of inputs) {
  Object.defineProperty(input, 'checked', {
    get: () => checked.has(input),
    set: (on) => {
      if (!on) return void checked.delete(input);
      for (const other of inputs) {
        if (other.name === input.name) checked.delete(other);
      }
      checked.add(input);
    },
  });
}

const questions = [...html.matchAll(/data-q="([^"]+)"/g)].map((hit) => ({
  dataset: { q: hit[1] },
  classes: new Set(),
  classList: null,
}));
for (const q of questions) {
  q.classList = {
    toggle: (name, on) => (on ? q.classes.add(name) : q.classes.delete(name)),
  };
}

// --- отложенные вызовы --------------------------------------------------

const timers = [];
const reads = [];
let crashed = null;

function safely(fn) {
  // Бросок в обратном вызове браузер не передаёт никому: он пишет в консоль,
  // а страница остаётся в середине недоделанной работы. Здесь он не валит
  // заглушку молча, а запоминается — тест читает его как «страница сломалась
  // и клиенту об этом не сказали».
  try {
    fn();
  } catch (e) {
    crashed = String((e && e.message) || e);
  }
}

function runTimers() {
  for (const t of timers.splice(0)) safely(t.fn);
}

function settle() {
  // Чтение файла и лист отправки заканчиваются вне вызова, который их завёл.
  for (const read of reads.splice(0)) safely(read);
  return new Promise((done) => setImmediate(done));
}

// --- заглушка дерева ----------------------------------------------------

const elements = {
  warning: { textContent: '', hidden: true, className: '' },
  progress: {
    writes: 0,
    text: '',
    // Сбой при работе с деревом — обычное дело в браузере телефона, и
    // страница обязана о нём сказать, а не остаться с полуприменённой
    // загрузкой. Ломается по команде теста, на заданном по счёту обращении:
    // первое приходится на запуск страницы.
    set textContent(value) {
      this.writes += 1;
      if (plan.breakTreeAt === this.writes) throw new Error('дерево недоступно');
      this.text = value;
    },
    get textContent() {
      return this.text;
    },
  },
};
const handlers = {};

function stubNode(id) {
  return {
    addEventListener: (event, fn) => {
      handlers[id + ':' + event] = fn;
    },
    click: () => {
      const fn = handlers[id + ':click'];
      if (fn) fn();
    },
    files: null,
    value: '',
  };
}
elements.download = stubNode('download');
elements.continue = stubNode('continue');
elements.picker = stubNode('picker');

let chosenFile = null;
let pickerOpened = 0;
elements.picker.click = () => {
  // Клик по невидимому выборщику открывает диалог. Если клиент файл выбрал,
  // браузер кладёт его в files, подставляет имя в value и посылает change.
  pickerOpened += 1;
  if (!chosenFile) return;
  const file = chosenFile;
  chosenFile = null;
  elements.picker.files = [file];
  elements.picker.value = file.name;
  const fn = handlers['picker:change'];
  if (fn) fn();
};

function match(selector) {
  if (selector === 'input[type=radio]') return inputs;
  if (selector === 'input[type=radio]:checked') {
    return inputs.filter((i) => i.checked);
  }
  if (selector === '.q') return questions;
  // Браузер разбирает селектор по грамматике, а не по шаблону: лишняя
  // кавычка внутри — SyntaxError, а не «ничего не нашлось». Заглушка обязана
  // падать там же, иначе селектор, собранный из чужого значения, выглядит
  // безобидным.
  const parts = selector.match(
    /^input\[name="([^"\\]*)"\](?:\[value="([^"\\]*)"\])?(:checked)?$/
  );
  if (!parts) throw new Error('заглушка не знает селектора: ' + selector);
  return inputs.filter(
    (i) =>
      i.name === parts[1] &&
      (parts[2] === undefined || String(i.value) === parts[2]) &&
      (!parts[3] || i.checked)
  );
}

elements.form = {
  querySelectorAll: match,
  querySelector: (s) => match(s)[0] || null,
  addEventListener: (event, fn) => {
    handlers['form:' + event] = fn;
  },
};

const downloads = [];
const shared = [];
let revoked = 0;

global.document = {
  getElementById: (id) => elements[id],
  createElement: () => ({
    href: '',
    download: '',
    click() {
      downloads.push({ href: this.href, name: this.download, inDom: this.inDom });
    },
    remove() {
      this.inDom = false;
    },
  }),
  body: {
    appendChild: (node) => {
      node.inDom = true;
    },
  },
};
global.location = { protocol: plan.protocol || 'file:' };
global.CSS = { escape: (s) => s.replace(/["\\]/g, '\\$&') };
global.Blob = function (parts) {
  this.text = parts.join('');
};
global.File = function (parts, name) {
  this.text = parts.join('');
  this.name = name;
};
global.URL = {
  createObjectURL: (blob) => {
    global.__lastBlob = blob;
    return 'blob:ответы';
  },
  revokeObjectURL: () => {
    revoked += 1;
  },
};
global.setTimeout = (fn, ms) => {
  timers.push({ fn: fn, ms: ms });
  return timers.length;
};

// Лист отправки есть не везде: в встроенном браузере мессенджера он часто
// единственный способ отдать файл, а на обычном рабочем столе его нет вовсе.
global.navigator = {};
if (plan.canShare) {
  global.navigator.canShare = (what) => !!(what && what.files && what.files[0]);
  global.navigator.share = (what) => {
    shared.push({
      name: what.files && what.files[0] && what.files[0].name,
      text: what.files && what.files[0] && what.files[0].text,
    });
    if (plan.shareFails) {
      // Клиент закрыл лист отправки, не отправив: браузер отвечает
      // AbortError — это отказ человека, а не поломка.
      const no = new Error('отправка отменена');
      no.name = 'AbortError';
      return Promise.reject(no);
    }
    if (plan.shareBroken) {
      // Лист отправки есть, но не работает: встроенный браузер объявил
      // поддержку и не справился. Клиент тут ни при чём.
      return Promise.reject(new Error('отправка невозможна'));
    }
    return Promise.resolve();
  };
}

const store = Object.assign({}, plan.storage || {});
global.localStorage = {
  getItem: (k) => {
    if (plan.storageThrows) throw new Error('хранилище недоступно');
    return k in store ? store[k] : null;
  },
  setItem: (k, v) => {
    if (plan.storageThrows) throw new Error('хранилище недоступно');
    store[k] = v;
  },
};

global.FileReader = function () {
  this.readAsText = (file) => {
    // Чтение заканчивается отдельным оборотом цикла событий. Это не
    // придирка: именно поэтому бросок внутри onload не ловится тем кодом,
    // который вызвал readAsText, и загрузка остаётся сделанной наполовину.
    reads.push(() => {
      if (file.broken) {
        if (this.onerror) this.onerror();
        return;
      }
      this.result = file.text;
      this.onload();
    });
  };
};

// --- исполнение ---------------------------------------------------------

eval(script);

function answer(name, value) {
  for (const input of inputs) {
    if (input.name === name && String(input.value) === String(value)) {
      input.checked = true;
    }
  }
  handlers['form:change']();
}

async function main() {
  await settle();
  for (const step of plan.steps) {
    if (step.answer) answer(step.answer[0], step.answer[1]);
    if (step.download) elements.download.click();
    // Единственный вход в восстановление — кнопка «Продолжить»: она и
    // открывает выборщик. Дёргать picker:change напрямую значит проверять
    // проводку, минуя её.
    if (step.load || step.continue) {
      chosenFile = {
        text: step.load || step.continue,
        broken: !!step.broken,
        name: 'ответы.json',
      };
      elements.continue.click();
    }
    if (step.cancel) elements.continue.click();
    if (step.timers) runTimers();
    await settle();
  }
  await settle();

  console.log(
    JSON.stringify({
      warning: elements.warning.textContent,
      warningKind: elements.warning.className,
      warningHidden: elements.warning.hidden,
      progress: elements.progress.textContent,
      checked: inputs.filter((i) => i.checked).map((i) => i.name + '=' + i.value),
      done: questions.filter((q) => q.classes.has('done')).length,
      downloads: downloads.map((d) => ({ name: d.name, inDom: d.inDom })),
      shared: shared,
      saved: global.__lastBlob ? global.__lastBlob.text : null,
      stored: store,
      revoked: revoked,
      timerDelays: timers.map((t) => t.ms),
      pickerOpened: pickerOpened,
      pickerValue: elements.picker.value,
      pickerReset: elements.picker.value === '',
      crashed: crashed,
    })
  );
}

main();
