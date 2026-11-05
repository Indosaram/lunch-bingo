'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/app.js'), 'utf8');
const V1 = 'lunchbingo:v1', V2 = 'lunchbingo:v2';
const scope = (month, area) => JSON.stringify([month, area]);
function board(id = 'a', month = '2026-11') {
  return { id, month, updated: `${month}-02`, name: id, board: 'abc123',
    stores: Array.from({length: 24}, (_, i) => ({u: `https://eat.pl/${i}`, s: `Store ${i}`, n: `Store ${i}`, c: 'Food'})) };
}
function harness(seed = {}, fetcher = async () => { throw new Error('No fetch configured'); }) {
  const storage = new Map(Object.entries(seed));
  const nodes = new Map(), timers = new Map();
  let timerId = 0;
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {
      innerHTML: '', textContent: '', hidden: false, open: false, events: {},
      classList: {add() {}, remove() {}, toggle() {}},
      addEventListener(event, fn) { this.events[event] = fn; },
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element, addEventListener() {}, querySelectorAll: () => [], querySelector: () => null},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, val) => storage.set(key, val)},
    fetch: fetcher, URL, URLSearchParams, location: {href: 'https://example.com/', search: '', origin: 'https://example.com', pathname: '/'},
    history: {replaceState() {}}, navigator: {},
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id),
  });
  // Keep production event handlers; expose the closure instead of initiating boot I/O.
  vm.runInContext(source.replace('  // boot', `  globalThis.app = {
    use(board) { data = board; useProgress(board); },
    isOn, bitmask, onCells, lines, openArea, openStore, draw, renderBoard, boardMonth,
    getData: () => data, save
  }; return;\n  // boot`), context);
  return {app: context.app, storage, element, timers, context,
    stamp(i = 0) { context.app.openStore(i); element('sStamp').events.click(); },
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); },
  };
}
const response = value => ({ok: true, json: async () => value});

test('month and area are independent, but same-month corrections retain URL stamps', () => {
  const h = harness(), november = board();
  h.app.use(november); h.stamp();
  assert.equal(h.app.bitmask(), '1');
  h.app.use(board('a', '2026-12'));
  assert.equal(h.app.bitmask(), '0');
  h.app.use(board('b'));
  assert.equal(h.app.bitmask(), '0');
  const corrected = board(); corrected.board = 'newhash'; corrected.stores.reverse();
  h.app.use(corrected);
  assert.equal(h.app.isOn(corrected.stores[23]), true);
  assert.equal(h.app.isOn(corrected.stores[0]), false);
  h.app.renderBoard();
  assert.equal(h.element('stampCount').textContent, 1);
  assert.match(h.element('grid').innerHTML, /class="cell on/);
  h.app.use(november);
  assert.equal(h.app.bitmask(), '1');
});

test('v1 migration preserves valid global URL visits and leaves original bytes untouched', () => {
  const b = board();
  const legacy = JSON.stringify({area: 'a', s: {
    [b.stores[0].u]: '2026-11-01', [b.stores[1].u]: '2026-10-31',
    [b.stores[2].u]: '2026-11-31', [b.stores[3].u]: true,
    [b.stores[4].u]: '2026-11-01<script>', 'https://eat.pl/missing': '2026-11-01',
  }});
  const h = harness({[V1]: legacy}); h.app.use(b); h.app.save();
  assert.equal(h.app.bitmask(), '1');
  assert.equal(h.storage.get(V1), legacy);
  assert.deepEqual(Object.keys(JSON.parse(h.storage.get(V2)).boards[scope('2026-11', 'a')]), [b.stores[0].u, 'https://eat.pl/missing']);
  h.app.use(board('b')); assert.equal(h.app.bitmask(), '1');
  h.app.use(board('a', '2026-12')); assert.equal(h.app.bitmask(), '0');
});

test('removing a migrated stamp stays removed after navigation and reload', () => {
  const b = board(), old = JSON.stringify({area: 'a', s: {[b.stores[0].u]: '2026-11-01'}});
  const h = harness({[V1]: old}); h.app.use(b); h.stamp();
  h.app.use(board('b')); h.app.use(b); assert.equal(h.app.bitmask(), '0');
  const reopened = harness(Object.fromEntries(h.storage)); reopened.app.use(b);
  assert.equal(reopened.app.bitmask(), '0');
  assert.equal(reopened.storage.get(V1), old);
});

test('corrupt and wrong-shaped storage never crashes or creates false stamps', () => {
  for (const raw of ['{', 'null', '[]', '1', 'true', '"oops"', '{"boards":[]}', '{"boards":null}', '{"s":true}']) {
    const h = harness({[V1]: raw, [V2]: raw});
    h.app.use(board()); h.app.renderBoard(); assert.equal(h.app.bitmask(), '0');
    h.stamp(); assert.equal(h.app.bitmask(), '1');
    assert.equal(h.storage.get(V1), raw);
  }
  const b = board(), bad = {[b.stores[0].u]: {}, [b.stores[1].u]: '2026-02-30', [b.stores[2].u]: '2026-11-03'};
  const h = harness({[V2]: JSON.stringify({boards: {[scope(b.month, b.id)]: bad}})});
  h.app.use(b); h.app.renderBoard(); assert.equal(h.app.bitmask(), '4');
});

test('unavailable localStorage still permits session progress', () => {
  const h = harness();
  h.context.localStorage.setItem = () => { throw new Error('Quota exceeded'); };
  h.app.use(board()); h.stamp(); assert.equal(h.app.bitmask(), '1');
});

test('explicit board month wins over update date; old JSON falls back to updated', () => {
  const h = harness(), b = board(); b.updated = '2026-12-01';
  assert.equal(h.app.boardMonth(b), '2026-11');
  delete b.month; assert.equal(h.app.boardMonth(b), '2026-12');
  for (const month of ['2026-13', '2026-00', '2026-1', {}, '']) {
    b.month = month; assert.throws(() => h.app.boardMonth(b));
  }
});

test('counts and completed lines reset on the next month, persisted progress survives reload', () => {
  const h = harness(), b = board(); h.app.use(b);
  for (let i = 0; i < 5; i++) h.stamp(i);
  assert.equal(h.app.lines(h.app.onCells()).length, 1);
  const reopened = harness(Object.fromEntries(h.storage)); reopened.app.use(b);
  assert.equal(reopened.app.bitmask(), (31).toString(36));
  reopened.app.use(board('a', '2026-12')); reopened.app.renderBoard();
  assert.equal(reopened.element('stampCount').textContent, 0);
  assert.equal(reopened.element('lineCount').textContent, 0);
});

test('latest area selection wins out-of-order fetches', async () => {
  const pending = new Map();
  const h = harness({}, url => new Promise(resolve => pending.set(url, resolve)));
  const first = h.app.openArea('a'), second = h.app.openArea('b');
  pending.get('data/b.json')(response(board('b'))); await second;
  pending.get('data/a.json')(response(board('a'))); await first;
  assert.equal(h.app.getData().id, 'b');
  assert.equal(JSON.parse(h.storage.get(V2)).area, 'b');
});

test('navigation cancels delayed draw and blocks stamps on the old board during load', async () => {
  let resolve;
  const h = harness({}, () => new Promise(r => { resolve = r; }));
  h.app.use(board()); h.app.openStore(0); h.app.draw();
  const loading = h.app.openArea('b');
  h.element('sStamp').events.click(); h.flushTimers();
  assert.equal(h.element('storeSheet').open, false);
  assert.equal(h.app.bitmask(), '0');
  resolve(response(board('b'))); await loading;
  assert.equal(h.element('storeSheet').open, false);
});

test('fetch errors and malformed board month show intro instead of rejecting', async () => {
  for (const fetcher of [async () => { throw new Error('offline'); }, async () => ({ok: false}), async () => response({...board(), month: 'bad'})]) {
    const h = harness({}, fetcher); await h.app.openArea('a');
    assert.equal(h.element('intro').hidden, false);
    assert.equal(h.app.getData(), null);
  }
});

test('stale failed request cannot hide a newer successful board', async () => {
  const pending = new Map();
  const h = harness({}, url => new Promise((resolve, reject) => pending.set(url, {resolve, reject})));
  const first = h.app.openArea('a'), second = h.app.openArea('b');
  pending.get('data/b.json').resolve(response(board('b'))); await second;
  pending.get('data/a.json').reject(new Error('offline')); await first;
  assert.equal(h.app.getData().id, 'b');
  assert.equal(h.element('boardView').hidden, false);
});

test('removed stores do not count and their saved visits are retained for corrections', () => {
  const h = harness(), original = board(); h.app.use(original); h.stamp();
  const corrected = board(); corrected.stores[0] = {...corrected.stores[0], u: 'https://eat.pl/new'};
  h.app.use(corrected); h.app.renderBoard(); h.app.save();
  assert.equal(h.element('stampCount').textContent, 0);
  const reopened = harness(Object.fromEntries(h.storage)); reopened.app.use(original);
  assert.equal(reopened.app.bitmask(), '1');
});

test('temporarily absent legacy store returns on correction but an explicit erasure never remigrates', () => {
  const initial = board(); initial.stores[0].u = 'https://eat.pl/temporary';
  const h = harness({[V1]: JSON.stringify({area: 'a', s: {'https://eat.pl/0': '2026-11-01'}})});
  h.app.use(initial); h.app.save(); assert.equal(h.app.bitmask(), '0');
  const reopened = harness(Object.fromEntries(h.storage)); reopened.app.use(board());
  assert.equal(reopened.app.bitmask(), '1');
  reopened.stamp(); // Explicitly erase the restored legacy visit.
  reopened.app.use(initial); reopened.app.use(board());
  assert.equal(reopened.app.bitmask(), '0');
  const afterErase = harness(Object.fromEntries(reopened.storage)); afterErase.app.use(board());
  assert.equal(afterErase.app.bitmask(), '0');
});

test('restaurant modal exposes its actual refresh date with old-JSON fallback', () => {
  const h = harness(), b = board(); b.stores[0].updated = '2026-11-01';
  h.app.use(b); h.app.openStore(0);
  assert.equal(h.element('sUpdated').textContent, '식당 정보 갱신: 2026-11-01');
  h.app.openStore(1);
  assert.equal(h.element('sUpdated').textContent, '식당 정보 갱신: 2026-11-02');
});


test('legacy last-selected area is not evidence of where visits happened', () => {
  const b = board('a');
  const old = JSON.stringify({area: 'b', s: {[b.stores[0].u]: '2026-11-01'}});
  const h = harness({[V1]: old});
  h.app.use(b); assert.equal(h.app.bitmask(), '1');
  h.stamp(); // Remove only A's migrated visit.
  h.app.use(board('b')); assert.equal(h.app.bitmask(), '1');
  h.stamp(1); // New visits are scoped to B, even for a shared restaurant URL.
  h.app.use(b); assert.equal(h.app.bitmask(), '0');
  h.app.save();
  const reopened = harness(Object.fromEntries(h.storage)); reopened.app.use(b);
  assert.equal(reopened.app.bitmask(), '0');
  reopened.app.use(board('b')); assert.equal(reopened.app.bitmask(), '3');
  assert.equal(reopened.storage.get(V1), old);
});
