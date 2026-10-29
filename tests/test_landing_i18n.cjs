'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../static/landing.js');

const html = fs.readFileSync(path.join(__dirname, '../templates/landing.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../static/landing.css'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../static/landing.js'), 'utf8');

function element(key, attribute = 'data-i18n') {
  return {
    value: '', textContent: '', attributes: { [attribute]: key }, listeners: {},
    getAttribute(name) { return this.attributes[name]; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(type, listener) { this.listeners[type] = listener; }
  };
}

function harness({ stored = null, browser = 'it-CH' } = {}) {
  const textNodes = [...html.matchAll(/data-i18n="([^"]+)"/g)].map(match => element(match[1]));
  const ariaNodes = [...html.matchAll(/data-i18n-aria="([^"]+)"/g)].map(match => element(match[1], 'data-i18n-aria'));
  const select = element('');
  const meta = element('');
  const saved = new Map(stored ? [[ui.storageKey, stored]] : []);
  const document = {
    title: '', documentElement: { lang: 'it' },
    getElementById: id => id === 'site-language' ? select : null,
    querySelector: selector => selector === 'meta[name="description"]' ? meta : null,
    querySelectorAll: selector => selector === '[data-i18n]' ? textNodes : selector === '[data-i18n-aria]' ? ariaNodes : []
  };
  const window = {
    navigator: { language: browser },
    localStorage: {
      getItem: key => saved.get(key) || null,
      setItem: (key, value) => saved.set(key, value)
    },
    fetch() { throw new Error('The landing locale controller must not use the network'); }
  };
  return { controller: ui.createController(document, window), document, select, meta, saved, textNodes, ariaNodes };
}

test('Every landing text and accessible label has complete IT DE FR EN parity', () => {
  assert.deepEqual([...ui.locales].sort(), ['de', 'en', 'fr', 'it']);
  const keys = Object.keys(ui.dictionaries.it).sort();
  for (const locale of ui.locales) {
    assert.deepEqual(Object.keys(ui.dictionaries[locale]).sort(), keys);
    for (const key of keys) assert.ok(ui.dictionaries[locale][key].trim(), `${locale}:${key}`);
  }
  for (const match of html.matchAll(/data-i18n(?:-aria)?="([^"]+)"/g)) {
    assert.ok(keys.includes(match[1]), `Missing translation key: ${match[1]}`);
  }
});

test('Browser language applies immediately to content, metadata and accessible names', () => {
  const h = harness({ browser: 'fr-CH' });
  h.controller.start();
  assert.equal(h.controller.getLanguage(), 'fr');
  assert.equal(h.document.documentElement.lang, 'fr');
  assert.equal(h.document.title, ui.dictionaries.fr.pageTitle);
  assert.equal(h.meta.attributes.content, ui.dictionaries.fr.description);
  assert.equal(h.select.value, 'fr');
  assert.equal(h.textNodes.find(node => node.attributes['data-i18n'] === 'openApp').textContent, ui.dictionaries.fr.openApp);
  assert.equal(h.ariaNodes.find(node => node.attributes['data-i18n-aria'] === 'navLabel').attributes['aria-label'], ui.dictionaries.fr.navLabel);
});

test('An explicit choice survives refresh and persists only the canonical locale', () => {
  assert.equal(ui.storageKey, 'slps.locale');
  const h = harness({ stored: 'de', browser: 'en-US' });
  h.controller.start();
  assert.equal(h.controller.getLanguage(), 'de');
  h.controller.change('en');
  assert.equal(h.document.documentElement.lang, 'en');
  assert.equal(h.document.title, ui.dictionaries.en.pageTitle);
  assert.deepEqual([...h.saved.entries()], [[ui.storageKey, 'en']]);
  h.controller.change('unsupported');
  assert.deepEqual([...h.saved.entries()], [[ui.storageKey, 'en']]);
});

test('Landing localization is same-origin and contains no network operation', () => {
  assert.doesNotMatch(script, /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon/);
  const h = harness({ browser: 'de-CH' });
  assert.doesNotThrow(() => h.controller.start());
  h.select.listeners.change({ target: { value: 'fr' } });
  assert.equal(h.controller.getLanguage(), 'fr');
});

test('Capability and access limits stay explicit in every locale', () => {
  for (const locale of ui.locales) {
    const copy = ui.dictionaries[locale];
    assert.match(copy.mediaNote.toLowerCase(), /vid[eé]o/);
    assert.match(copy.outcome4Copy.toLowerCase(), /(export|esportazione)/);
    assert.ok(copy.accountAccess.trim());
    assert.ok(copy.createAccount.trim());
    assert.ok(copy.signInAccount.trim());
  }
  assert.doesNotMatch(script + html, /Stampa il rapporto|formato strutturato JSON|Gold|Silver|Premium/);
});

test('Language control, no-script fallback, mobile and motion accessibility remain present', () => {
  assert.match(html, /<select id="site-language"[^>]+data-i18n-aria="language"/);
  for (const locale of ui.locales) assert.match(html, new RegExp(`<option value="${locale}" lang="${locale}">${locale.toUpperCase()}<\\/option>`));
  assert.match(html, /<noscript>[\s\S]*lang="it"[\s\S]*lang="de"[\s\S]*lang="fr"[\s\S]*lang="en"[\s\S]*<\/noscript>/);
  assert.doesNotMatch(html, /(?:🇨🇭|🇮🇹|🇩🇪|🇫🇷|🇬🇧)/);
  assert.doesNotMatch(html, /onclick=|style=/);
  assert.match(css, /\.sr-only\{/);
  assert.match(css, /@media\(max-width:600px\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(css, /\.language-control select\{[^}]*height:44px/);
  assert.match(css, /\.button>span:last-child/);
  assert.match(css, /\.text-link>span:last-child/);
});
