'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadUI(options = {}) {
  const elements = new Map(), timers = new Map(), audios = [];
  let timerId = 0;
  const escape = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  class Element {
    constructor() {
      this.children = []; this.dataset = {}; this.events = {}; this.cache = new Map();
      this.classList = { add() {}, remove() {}, toggle() {} }; this.style = {};
      this.className = ''; this.value = ''; this.scrollHeight = 24;
    }
    set textContent(value) { this.text = value; this.html = null; }
    get textContent() { return this.text || ''; }
    set innerHTML(value) { this.html = value; this.cache.clear(); }
    get innerHTML() { return this.html ?? escape(this.text || ''); }
    appendChild(child) { child.parent = this; this.children.push(child); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
    focus() { this.focused = true; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, callback) { this.events[name] = callback; }
    scrollIntoView() { this.scrolled = true; }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    querySelectorAll(selector) {
      if (selector === '.message:not(.welcome-message)') return this.children.filter(child => child.className.startsWith('message'));
      if (this.cache.has(selector)) return this.cache.get(selector);
      let items = [];
      const attribute = selector === '[data-citation]' ? 'citation' : selector === '[data-source-index]' ? 'source-index' : null;
      if (attribute) {
        items = [...this.innerHTML.matchAll(new RegExp(`data-${attribute}="([^"]+)"`, 'g'))].map(match => {
          const item = new Element();
          item.dataset[attribute === 'citation' ? 'citation' : 'sourceIndex'] = match[1];
          return item;
        });
      } else if (selector === '.copy-btn' && this.innerHTML.includes('class="copy-btn"')) {
        items = [new Element()];
      }
      this.cache.set(selector, items);
      return items;
    }
  }
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new Element());
      return elements.get(selector);
    },
    querySelectorAll() { return []; },
    createElement() { return new Element(); },
    getElementById(id) {
      for (const element of elements.values()) {
        const child = element.children.find(child => child.id === id);
        if (child) return child;
        if (element.innerHTML.includes(`id="${id}"`)) return new Element();
      }
      return null;
    },
    addEventListener() {},
  };
  const synthesis = {
    spoken: [], cancels: 0,
    voices: options.voices || [{ lang: 'vi-VN', name: 'Vietnamese' }],
    getVoices() { return this.voices; },
    cancel() { this.cancels++; },
    speak(utterance) { this.spoken.push(utterance); },
  };
  class Audio {
    constructor(src) {
      this.src = src; this.pauses = 0; this.loads = 0;
      this.playback = options.deferPlay
        ? new Promise((resolve, reject) => { this.resolve = resolve; this.reject = reject; })
        : Promise.resolve();
      audios.push(this);
    }
    play() { return this.playback; }
    pause() { this.pauses++; }
    removeAttribute(name) { if (name === 'src') this.src = ''; }
    load() { this.loads++; }
  }
  const sandbox = {
    document, localStorage: { getItem() { return null; }, setItem() {} },
    crypto: { randomUUID() { return 'test-session'; } }, navigator: {}, console,
    window: { speechSynthesis: synthesis }, speechSynthesis: synthesis,
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } }, Audio,
    setTimeout(callback, delay) { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    fetch: options.fetch,
    HocVuAPI: require('../../ui/api-errors.js'),
  };
  const filename = path.join(__dirname, '..', '..', 'ui', 'main.js');
  const source = fs.readFileSync(filename, 'utf8');
  assert.match(source, /\}\)\(\);\s*$/);
  const instrumented = source.replace(/\}\)\(\);\s*$/, `
    globalThis.testUI = {
      renderAnswerCard, appendAnswer, restoreHistory, state, dom, appendTyping,
      speak, stopSpeech, stopLive, send, bind, startNewConversation,
      setSpeechHook(callback) { speak = callback; }
    };
  })();`);
  vm.runInNewContext(instrumented, sandbox, { filename });
  const ui = sandbox.testUI;
  Object.assign(ui, { speech: [], synthesis, audios, timers });
  ui.runTimers = () => {
    const pending = [...timers.entries()];
    for (const [id, timer] of pending) { timers.delete(id); timer.callback(); }
  };
  if (!options.realSpeech) ui.setSpeechHook((...args) => ui.speech.push(args));
  return ui;
}

module.exports = { loadUI };
