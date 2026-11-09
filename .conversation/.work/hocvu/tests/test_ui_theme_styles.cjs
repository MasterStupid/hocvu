'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');
const read = name => fs.readFileSync(path.join(__dirname, '..', 'ui', name), 'utf8');
const css = read('styles.css');

function theme(saved, blocked = false) {
  const document = { documentElement: { dataset: {} } };
  vm.runInNewContext(read('theme.js'), {
    document,
    localStorage: { getItem(key) {
      assert.equal(key, 'hv_theme');
      if (blocked) throw new Error('Storage unavailable');
      return saved;
    } },
  });
  return document.documentElement.dataset.theme;
}

test('both pages apply the persisted theme before their stylesheet', () => {
  for (const name of ['index.html', 'documents.html']) {
    const html = read(name), script = html.indexOf('src="theme.js'), stylesheet = html.indexOf('rel="stylesheet"');
    assert.ok(script > 0 && script < stylesheet, name);
  }
  assert.equal(theme('dark'), 'dark');
  assert.equal(theme('light'), 'light');
});

test('missing, invalid and inaccessible theme storage default safely to light', () => {
  assert.equal(theme(null), 'light');
  assert.equal(theme('invalid'), 'light');
  assert.equal(theme(null, true), 'light');
});

test('all custom properties used by the stylesheet have definitions', () => {
  const definitions = new Set([...css.matchAll(/(--[\w-]+)\s*:/g)].map(match => match[1]));
  for (const match of css.matchAll(/var\((--[\w-]+)/g)) assert.ok(definitions.has(match[1]), match[1]);
});

test('document text aliases and backgrounds follow the active color theme', () => {
  const properties = block => Object.fromEntries(
    [...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]),
  );
  const light = properties(css.match(/:root\s*\{([^]*?)\}/)[1]);
  const dark = { ...light, ...properties(css.match(/\[data-theme="dark"\]\s*\{([^]*?)\}/)[1]) };
  const resolve = (name, values) => values[name].replace(/var\((--[\w-]+)\)/g, (_, key) => resolve(key, values));
  for (const values of [light, dark]) {
    assert.equal(resolve('--ink', values), values['--text-primary']);
    assert.equal(resolve('--muted', values), values['--text-secondary']);
    assert.ok(values['--line']);
  }
  assert.notEqual(resolve('--ink', light), resolve('--ink', dark));
  for (const selector of ['.queue-fields input', '.document-date-dialog input']) {
    const rule = css.slice(css.indexOf(selector)).split('}')[0];
    assert.match(rule, /background:\s*var\(--bg-secondary\)/);
    assert.doesNotMatch(rule, /background:\s*#fff/);
  }
});

test('the typing DOM contains three dots that match visible styled elements', () => {
  const ui = loadUI();
  ui.appendTyping();
  const html = ui.dom.thread.children.at(-1).innerHTML;
  assert.equal([...html.matchAll(/class="typing-dot"/g)].length, 3);
  assert.match(html, /role="status"/);
  const rule = css.match(/\.typing-dot\s*\{([^]*?)\}/)[1];
  assert.match(rule, /width:\s*8px/);
  assert.match(rule, /height:\s*8px/);
  assert.match(rule, /background-color:\s*var\(--text-secondary\)/);
  assert.match(rule, /animation:\s*bounce/);
});

test('reduced-motion preference leaves static visible typing dots', () => {
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*\.typing-dot\s*\{[^}]*animation:\s*none;[^}]*transform:\s*none;/);
});
