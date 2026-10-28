// Заглушка браузера для скрипта опросника.
//
// Скрипт страницы — единственное место, где живёт логика сохранения и
// загрузки ответов, и проверять её поиском подстрок в HTML бессмысленно:
// так не отличить работающую проверку чужого файла от вычеркнутой. Здесь
// скрипт исполняется по-настоящему, на разметке, которую сам генератор и
// выдал: заглушка собирает дерево из неё, а не из выдуманного образца.

const fs = require('fs');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = fs.readFileSync(process.argv[3], 'utf8');
const plan = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

// --- разбор разметки ----------------------------------------------------

const inputs = [];
const inputRe = /<input type="radio" name="([^"]+)" value="([^"]+)"/g;
let m;
while ((m = inputRe.exec(html)) !== null) {
  inputs.push({ name: m[1], value: m[2], checked: false, type: 'radio' });
}
if (!inputs.length) throw new Error('в разметке не нашлось ни одного ответа');

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

// --- заглушка дерева ----------------------------------------------------

const elements = {
  warning: { textContent: '', hidden: true, className: '' },
  progress: { textContent: '' },
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

function match(selector) {
  const byName = selector.match(/^input\[name="(.+?)"\]\[value="(.+?)"\]$/);
  if (byName) {
    return inputs.filter(
      (i) => i.name === byName[1] && String(i.value) === byName[2]
    );
  }
  const checkedByName = selector.match(/^input\[name="(.+?)"\]:checked$/);
  if (checkedByName) {
    return inputs.filter((i) => i.name === checkedByName[1] && i.checked);
  }
  if (selector === 'input[type=radio]:checked') {
    return inputs.filter((i) => i.checked);
  }
  if (selector === 'input[type=radio]') return inputs;
  if (selector === '.q') return questions;
  throw new Error('заглушка не знает селектора: ' + selector);
}

elements.form = {
  querySelectorAll: match,
  querySelector: (s) => match(s)[0] || null,
  addEventListener: (event, fn) => {
    handlers['form:' + event] = fn;
  },
};

const downloads = [];
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
global.URL = {
  createObjectURL: (blob) => {
    global.__lastBlob = blob;
    return 'blob:ответы';
  },
  revokeObjectURL: () => {
    revoked += 1;
  },
};
global.setTimeout = (fn) => fn && 0;

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
    this.result = file.text;
    if (file.broken) {
      if (this.onerror) this.onerror();
      return;
    }
    this.onload();
  };
};

// --- исполнение ---------------------------------------------------------

eval(script);

function answer(name, value) {
  for (const input of inputs) {
    if (input.name === name) input.checked = String(input.value) === String(value);
  }
  handlers['form:change']();
}

for (const step of plan.steps) {
  if (step.answer) answer(step.answer[0], step.answer[1]);
  if (step.download) elements.download.click();
  if (step.load) {
    elements.picker.files = [{ text: step.load, broken: !!step.broken }];
    handlers['picker:change']();
  }
}

console.log(
  JSON.stringify({
    warning: elements.warning.textContent,
    warningKind: elements.warning.className,
    warningHidden: elements.warning.hidden,
    progress: elements.progress.textContent,
    checked: inputs.filter((i) => i.checked).map((i) => i.name + '=' + i.value),
    done: questions.filter((q) => q.classes.has('done')).length,
    downloads: downloads.map((d) => ({ name: d.name, inDom: d.inDom })),
    saved: global.__lastBlob ? global.__lastBlob.text : null,
    stored: store,
    revoked: revoked,
    pickerReset: elements.picker.value === '',
  })
);
