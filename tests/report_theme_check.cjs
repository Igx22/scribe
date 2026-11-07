// Execute the actual inline script without a browser, network, or extra libraries.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(0, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const key = 'scribe-report-theme';

function open({storage = new Map(), systemDark = false, protocol = 'file:', cookie = '',
               blockRead = false, blockWrite = false, blockCookie = false} = {}) {
  let ready, focused;
  const cookieWrites = [];
  function element(tag) {
    const attrs = Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
    return {id: attrs.id, attrs, hidden: /\shidden\b/.test(tag), tabIndex: Number(attrs.tabindex), listeners: {},
      setAttribute(k, value) { this.attrs[k] = value; }, getAttribute(k) { return this.attrs[k]; },
      addEventListener(type, handler) { this.listeners[type] = handler; }, focus() { focused = this; }};
  }
  const toggle = element(html.match(/<button[^>]*id="theme-toggle"[^>]*>/)[0]);
  const state = {textContent: 'Off'};
  const root = {dataset: {}};
  const tabs = [...html.matchAll(/<button[^>]*role="tab"[^>]*>/g)].map(m => element(m[0]));
  const panels = [...html.matchAll(/<section[^>]*role="tabpanel"[^>]*>/g)].map(m => element(m[0]));
  const document = {
    documentElement: root,
    getElementById(id) { return id === 'theme-toggle' ? toggle : state; },
    addEventListener(type, handler) { assert.equal(type, 'DOMContentLoaded'); ready = handler; },
    querySelectorAll(selector) { return selector === '[role="tab"]' ? tabs : panels; },
    get cookie() { if (blockCookie) throw Error('Cookie access denied'); return cookie; },
    set cookie(value) {
      if (blockCookie) throw Error('Cookie access denied');
      cookieWrites.push(value); cookie = value.split(';')[0];
    }
  };
  const context = {document, location: {protocol}, window: {matchMedia: () => ({matches: systemDark})}};
  Object.defineProperty(context, 'localStorage', {get() {
    if (blockRead) throw Error('SecurityError');
    return {getItem: name => storage.get(name) ?? null, setItem(name, value) {
      if (blockWrite) throw Error('QuotaExceededError');
      storage.set(name, value);
    }};
  }});
  assert.equal(toggle.attrs.role, 'switch');
  assert.equal(toggle.attrs['aria-label'], 'Dark Mode');
  assert.equal(toggle.hidden, true);
  vm.runInNewContext(script, context);
  // Theme initialization runs in the head, before content is displayed.
  const beforeReady = root.dataset.theme;
  ready();
  assert.equal(toggle.hidden, false);
  function theme(expected) {
    assert.equal(beforeReady === 'light' || beforeReady === 'dark', true);
    assert.equal(root.dataset.theme, expected);
    assert.equal(toggle.attrs['aria-checked'], String(expected === 'dark'));
    assert.equal(state.textContent, expected === 'dark' ? 'On' : 'Off');
  }
  function active(index) {
    tabs.forEach((tab, i) => {
      assert.equal(tab.attrs['aria-selected'], String(i === index));
      assert.equal(tab.tabIndex, i === index ? 0 : -1);
    });
    panels.forEach(panel => assert.equal(panel.hidden, panel.id !== tabs[index].attrs['aria-controls']));
  }
  function checkNavigation() {
    active(0);
    tabs.forEach((tab, i) => { tab.listeners.click(); active(i); });
    for (const [start, key, expected] of [[0, 'End', tabs.length - 1], [tabs.length - 1, 'ArrowRight', 0],
                                         [0, 'ArrowLeft', tabs.length - 1], [tabs.length - 1, 'Home', 0]]) {
      let prevented = false;
      tabs[start].listeners.keydown({key, preventDefault() { prevented = true; }});
      assert.ok(prevented); active(expected); assert.equal(focused, tabs[expected]);
    }
  }
  return {theme, beforeReady, toggle, storage, cookieWrites, checkNavigation};
}

const local = open();
local.theme('light');
local.toggle.listeners.click(); local.theme('dark');
assert.equal(local.storage.get(key), 'dark');
assert.deepEqual(local.cookieWrites, []);
const reopened = open({storage: local.storage});
assert.equal(reopened.beforeReady, 'dark'); reopened.theme('dark');
reopened.toggle.listeners.click(); reopened.theme('light');
open({storage: local.storage, systemDark: true}).theme('light');
open({systemDark: true}).theme('dark');
open({storage: new Map([[key, '<untrusted>']]), systemDark: true}).theme('dark');

for (const blocked of [{blockRead: true}, {blockWrite: true}, {blockRead: true, blockCookie: true}]) {
  const report = open({...blocked, protocol: 'https:'});
  report.theme('light'); report.toggle.listeners.click(); report.theme('dark');
  report.checkNavigation();
}

const web = open({protocol: 'https:'});
web.toggle.listeners.click();
assert.equal(web.cookieWrites[0], key + '=dark; Max-Age=31536000; Path=/; SameSite=Lax; Secure');
// Cookie fallback covers other reports on the same website when localStorage fails.
open({protocol: 'https:', blockRead: true, cookie: 'other=1; ' + web.cookieWrites[0]}).theme('dark');
open({protocol: 'https:', blockRead: true, cookie: key + '=invalid', systemDark: true}).theme('dark');
local.checkNavigation();
