// Execute the actual inline script without a browser, network, or extra libraries.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(0, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const key = 'scribe-report-theme';

function open({storage = new Map(), systemDark = false, protocol = 'file:', cookie = '',
               blockRead = false, blockWrite = false, blockCookie = false, now = Date.now()} = {}) {
  let ready, focused;
  let currentTime = now;
  const cookieWrites = [];
  const intervals = [];
  function element(tag) {
    const attrs = Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
    return {id: attrs.id, attrs, hidden: /\shidden\b/.test(tag), tabIndex: Number(attrs.tabindex), listeners: {},
      setAttribute(k, value) { this.attrs[k] = value; }, getAttribute(k) { return this.attrs[k]; },
      addEventListener(type, handler) { this.listeners[type] = handler; }, focus() { focused = this; }};
  }
  const toggle = element(html.match(/<button[^>]*id="theme-toggle"[^>]*>/)[0]);
  const state = {textContent: 'Off'};
  const stampTag = html.match(/<time[^>]*id="generated-at"[^>]*>/);
  const stamp = stampTag ? element(stampTag[0]) : null;
  const root = {dataset: {}};
  const tabs = [...html.matchAll(/<button[^>]*role="tab"[^>]*>/g)].map(m => element(m[0]));
  const panels = [...html.matchAll(/<section[^>]*role="tabpanel"[^>]*>/g)].map(m => element(m[0]));
  const extra = new Map(['detail', 'transcript'].flatMap(name =>
    ['picker', 'toggle', 'options', 'choice-title', 'choice-description'].map(suffix => {
      const id = name + '-' + suffix;
      const tag = html.match(new RegExp('<[^>]+id="' + id + '"[^>]*>'));
      return [id, tag ? element(tag[0]) : null];
    })));
  const groupFixtures = ['detail', 'transcript'].map(name => ({name,
    picker: extra.get(name + '-picker'), choice: extra.get(name + '-toggle'),
    options: extra.get(name + '-options'),
    tabs: tabs.filter(tab => name === 'detail' ? /^tab-\d+$/.test(tab.id) :
      tab.id === 'tab-transcript' || tab.id.startsWith('tab-source-'))
  })).filter(group => group.choice);
  groupFixtures.forEach(group => {
    group.picker.contains = item => item === group.choice || group.tabs.includes(item);
    group.options.contains = item => group.tabs.includes(item);
  });
  const documentListeners = {};
  const document = {
    documentElement: root,
    getElementById(id) { return id === 'theme-toggle' ? toggle : id === 'theme-state' ? state : id === 'generated-at' ? stamp : extra.get(id) ?? null; },
    addEventListener(type, handler) { if (type === 'DOMContentLoaded') ready = handler; else documentListeners[type] = handler; },
    get activeElement() { return focused; },
    querySelectorAll(selector) { return selector === '[role="tab"]' ? tabs : panels; },
    get cookie() { if (blockCookie) throw Error('Cookie access denied'); return cookie; },
    set cookie(value) {
      if (blockCookie) throw Error('Cookie access denied');
      cookieWrites.push(value); cookie = value.split(';')[0];
    }
  };
  class ReportDate extends Date {
    constructor(...args) { super(...(args.length ? args : [currentTime])); }
  }
  const context = {document, Date: ReportDate, location: {protocol}, window: {
    matchMedia: () => ({matches: systemDark}),
    setInterval(callback, delay) { intervals.push({callback, delay}); },
    clearTimeout() {}, setTimeout() { return 1; }
  }};
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
      const group = groupFixtures.find(item => item.tabs.includes(tab));
      assert.equal(tab.tabIndex, i === index && !group.options.hidden ? 0 : -1);
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
    for (const group of groupFixtures) {
      const {name, picker, choice, options, tabs: groupTabs} = group;
      const ids = groupTabs.map(tab => tab.id);
      choice.listeners.click();
      assert.equal(options.hidden, false);
      assert.equal(choice.attrs['aria-expanded'], 'true');
      const last = groupTabs[groupTabs.length - 1];
      last.listeners.click();
      assert.equal(options.hidden, true);
      assert.equal(focused, choice);
      assert.equal(extra.get(name + '-choice-title').textContent, last.attrs['data-title']);
      choice.listeners.click();
      assert.deepEqual(groupTabs.map(tab => tab.id), ids, 'Menu items must stay in place');
      assert.equal(last.attrs['data-current'], 'true');
      picker.listeners.keydown({key: 'Escape', preventDefault() {}});
      assert.equal(options.hidden, true);
      picker.listeners.keydown({key: 'ArrowDown', target: choice, preventDefault() {}});
      assert.equal(options.hidden, false); assert.equal(focused, last);
      last.listeners.keydown({key: 'ArrowDown', preventDefault() {}});
      assert.equal(focused, groupTabs[0]);
      groupTabs[0].listeners.click();
      assert.equal(extra.get(name + '-choice-title').textContent, groupTabs[0].attrs['data-title']);
      choice.listeners.click();
      documentListeners.pointerdown({target: toggle});
      assert.equal(options.hidden, true);
      choice.listeners.click();
      picker.listeners.focusout({relatedTarget: toggle});
      assert.equal(options.hidden, true);
    }
    if (groupFixtures.length === 2) {
      const [detail, transcript] = groupFixtures;
      const title = extra.get('detail-choice-title').textContent;
      detail.choice.listeners.click();
      assert.equal(detail.options.hidden, false);
      transcript.choice.listeners.click();
      assert.equal(detail.options.hidden, true);
      assert.equal(transcript.options.hidden, false);
      assert.equal(extra.get('detail-choice-title').textContent, title);
      documentListeners.pointerdown({target: toggle});
      assert.ok(groupFixtures.every(group => group.options.hidden));
    }
  }
  return {theme, beforeReady, toggle, storage, cookieWrites, checkNavigation, stamp, intervals,
    advance(value) { currentTime = value; intervals.forEach(timer => timer.callback()); }};
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

// Optional fixed-clock scenarios exercise the actual report formatter in the
// process's configured timezone, including midnight without reopening the file.
if (process.argv[2]) {
  for (const scenario of JSON.parse(process.argv[2])) {
    const report = open({now: scenario.now});
    assert.ok(report.stamp, 'Generated timestamp must be embedded in the HTML');
    assert.equal(report.stamp.textContent, scenario.expected);
    assert.equal(report.intervals.length, 1);
    assert.equal(report.intervals[0].delay, 60000);
    if (scenario.titleIncludes) assert.ok(report.stamp.attrs.title.includes(scenario.titleIncludes));
    if (scenario.advance) {
      report.advance(scenario.advance);
      assert.equal(report.stamp.textContent, scenario.afterAdvance);
    }
    // Formatting must never change the embedded generation instant.
    assert.equal(report.stamp.attrs.datetime, html.match(/<time[^>]*datetime="([^"]+)"/)[1]);
    report.checkNavigation();
  }
}
local.checkNavigation();
