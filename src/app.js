(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const LINES = [];
  for (let i = 0; i < 5; i++) {
    LINES.push([0, 1, 2, 3, 4].map((j) => i * 5 + j));
    LINES.push([0, 1, 2, 3, 4].map((j) => j * 5 + i));
  }
  LINES.push([0, 6, 12, 18, 24], [4, 8, 12, 16, 20]);
  const FREE = 12;
  const LEGACY_KEY = "lunchbingo:v1";
  const KEY = "lunchbingo:v2";

  let areas = [];
  let data = null; // current area json
  const legacy = readStorage(LEGACY_KEY);
  let stamps = load();
  let progress = Object.create(null);
  let areaRequest = 0;
  let loading = false;
  let drawTimer, closeTimer;
  let current = null; // store index in sheet
  let lastLines = 0;

  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  function record(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function readStorage(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return record(value) ? value : {};
    } catch { return {}; }
  }
  function load() {
    const value = readStorage(KEY);
    return {
      area: typeof value.area === "string" ? value.area : (typeof legacy.area === "string" ? legacy.area : null),
      boards: record(value.boards) ? value.boards : {},
    };
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(stamps)); } catch {} }
  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(value + "T00:00:00Z");
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }
  function boardMonth(board) {
    const month = board.month ?? (typeof board.updated === "string" ? board.updated.slice(0, 7) : "");
    if (typeof month !== "string" || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error("Invalid board month");
    return month;
  }
  function useProgress(board) {
    // Board hashes may change during a correction. Month + area is the challenge.
    const month = boardMonth(board), key = JSON.stringify([month, board.id]);
    if (!own(stamps.boards, key)) {
      const migrated = Object.create(null);
      // v1 visits were global by URL; its saved area was only the last selection.
      // Preserve those visits wherever the URL occurs, then keep new visits area-scoped.
      if (record(legacy.s)) {
        // Retain absent URLs too: a later correction can restore a restaurant.
        // Only current board stores contribute to the rendered score.
        for (const [url, date] of Object.entries(legacy.s)) {
          if (validDate(date) && date.slice(0, 7) === month) migrated[url] = date;
        }
      }
      stamps.boards[key] = migrated; // Also marks an empty migration as completed.
    }
    const saved = stamps.boards[key];
    progress = Object.create(null);
    if (record(saved)) {
      for (const [url, date] of Object.entries(saved)) {
        if (validDate(date)) progress[url] = date;
      }
    }
    stamps.boards[key] = progress;
  }

  const cellToStore = (c) => (c < FREE ? c : c - 1);
  const storeToCell = (s) => (s < FREE ? s : s + 1);
  const isOn = (st) => !!progress[st.u];

  function pct(v) {
    if (v === null || v === undefined || v === "") return "–";
    const n = Number(v);
    if (!isFinite(n)) return "–";
    return "상위 " + (n < 1 ? String(Math.round(n * 100) / 100) : (Math.round(n * 10) / 10).toString()) + "%";
  }
  function num(v) {
    const n = Number(v);
    if (v === null || v === undefined || v === "" || !isFinite(n)) return "–";
    return n < 1 ? String(Math.round(n * 100) / 100) : String(Math.round(n * 10) / 10);
  }
  function rot(u) { // deterministic tilt per store
    let h = 0; for (const ch of u) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return (((h >>> 0) % 28) - 18) + "deg";
  }
  function sealSVG(date) {
    return `<svg class="seal" viewBox="0 0 100 100" aria-hidden="true">
      <circle cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="5"/>
      <circle cx="50" cy="50" r="37" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <text x="50" y="57" text-anchor="middle" font-size="25" font-weight="800" fill="currentColor" font-family="Pretendard Variable, sans-serif">먹음</text>
      <text x="50" y="76" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor" font-family="ui-monospace, monospace">${date}</text>
    </svg>`;
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2200);
  }

  function onCells() {
    const on = new Set([FREE]);
    data.stores.forEach((st, i) => { if (isOn(st)) on.add(storeToCell(i)); });
    return on;
  }
  function lines(on) { return LINES.filter((l) => l.every((c) => on.has(c))); }

  function renderAreaLists() {
    const html = areas.map((a) => `<li><button type="button" data-area="${a.id}" ${data && data.id === a.id ? 'aria-current="true"' : ""}><b>${esc(a.name)}</b><span>${esc(a.sub)}</span></button></li>`).join("");
    $("introAreas").innerHTML = html; $("sheetAreas").innerHTML = html;
  }

  function renderBoard(popIdx) {
    const on = onCells();
    const done = lines(on);
    const lineCells = new Set(done.flat());
    const g = $("grid");
    let html = "";
    for (let c = 0; c < 25; c++) {
      if (c === FREE) {
        html += `<li class="cell free${lineCells.has(c) ? " line" : ""}"><div class="free-in"><span class="t">12:00</span><span class="l">점심시간</span></div></li>`;
        continue;
      }
      const i = cellToStore(c), st = data.stores[i], s = progress[st.u];
      html += `<li class="cell${s ? " on" : ""}${lineCells.has(c) ? " line" : ""}${popIdx === i ? " pop" : ""}" style="--rot:${rot(st.u)}" data-i="${i}">
        <button type="button" aria-label="${esc(st.s)}, ${esc(st.c)}${s ? ", 도장 찍음" : ""}">
          <span class="nm${st.s.length > 10 ? " xlong" : st.s.length > 6 ? " long" : ""}">${esc(st.s)}</span>
          <span class="rk">${esc(num(st.r))}<small>%</small></span>
        </button>${s ? sealSVG(s.slice(5).replace("-", ".")) : ""}</li>`;
    }
    g.innerHTML = html;
    const n = data.stores.filter(isOn).length;
    $("stampCount").textContent = n;
    $("lineCount").textContent = done.length;
    if (done.length > lastLines && popIdx !== undefined) toast(done.length === 12 ? "판 완성. 이 동네 점심은 마스터!" : `빙고! ${done.length}줄`);
    lastLines = done.length;
  }

  function openStore(i) {
    if (loading || !data || !data.stores[i]) return;
    clearTimeout(closeTimer);
    current = i;
    const st = data.stores[i];
    $("sCat").textContent = st.c || "";
    $("sName").textContent = st.n;
    $("sAddr").textContent = st.a || "";
    $("sUpdated").textContent = `식당 정보 갱신: ${st.updated || data.updated}`;
    $("sAll").textContent = pct(st.r);
    $("sLoc").textContent = pct(st.g);
    $("sHours").textContent = st.h || "–";
    $("sBusy").textContent = [st.bd ? st.bd + "요일" : "", st.bt || ""].filter(Boolean).join(" ") || "–";
    const tags = [];
    if (st.lo) tags.push("동네 단골 많음");
    if (st.gr) tags.push("회식 결제 많음");
    if (st.fr) tags.push("외국인 손님 많음");
    $("sCust").innerHTML = (st.cu && st.cu.length ? `주로 오는 손님 <b>${st.cu.map(esc).join(" · ")}</b><br>` : "") + tags.map((t) => `<span class="tag">${t}</span>`).join("");
    // 받은 merUrl 그대로. 추적 파라미터·리다이렉트 없음 (공모전 집계 조건)
    $("sLink").href = st.u;
    syncStampBtn();
    $("storeSheet").showModal();
  }
  function syncStampBtn() {
    const b = $("sStamp"), on = isOn(data.stores[current]);
    b.textContent = on ? "도장 지우기" : "다녀왔어요, 도장 찍기";
    b.classList.toggle("done", on);
  }

  function today() {
    const d = new Date(Date.now() + 9 * 3600e3); // KST
    return d.toISOString().slice(0, 10);
  }

  function bitmask() {
    let n = 0;
    data.stores.forEach((st, i) => { if (isOn(st)) n |= 1 << i; });
    return (n >>> 0).toString(36);
  }

  function renderFriend(params) {
    const f = $("friend");
    const s = params.get("s"), b = params.get("b");
    if (!s || params.get("a") !== data.id) { f.hidden = true; return; }
    const n = parseInt(s, 36) >>> 0;
    const on = new Set([FREE]);
    for (let i = 0; i < 24; i++) if (n & (1 << i)) on.add(storeToCell(i));
    const cnt = on.size - 1, ln = lines(on).length;
    const same = b === data.board;
    let mini = "";
    for (let c = 0; c < 25; c++) mini += `<i class="${on.has(c) ? "on" : ""}"></i>`;
    f.innerHTML = `<div class="mini" aria-hidden="true">${mini}</div><div>동료의 ${esc(data.name)} 판 — 도장 <b>${cnt}개</b> · 빙고 <b>${ln}줄</b><br>${same ? "같은 판이에요. 내 도장을 모아 따라잡아 보세요." : "판이 그사이 새로 바뀌었어요. 이번 판으로 시작해 보세요."}</div>`;
    f.hidden = false;
  }

  async function openArea(id, params) {
    const request = ++areaRequest;
    loading = true;
    clearTimeout(drawTimer); clearTimeout(closeTimer);
    $("storeSheet").close(); current = null;
    let next;
    try {
      const res = await fetch(`data/${encodeURIComponent(id)}.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("Board unavailable");
      next = await res.json();
      if (request !== areaRequest) return;
      if (next.id !== id || !Array.isArray(next.stores) || next.stores.length !== 24) throw new Error("Invalid board");
      boardMonth(next);
    } catch {
      if (request !== areaRequest) return;
      loading = false;
      toast("이 동네 판을 불러오지 못했어요"); showIntro(); return;
    }
    loading = false;
    data = next;
    useProgress(data);
    stamps.area = id; save();
    $("areaName").textContent = data.name;
    $("cardNo").textContent = `No. ${boardMonth(data).replace("-", ".")} · ${data.board.toUpperCase()}`;
    $("cardTitle").textContent = `${data.name} 점심 빙고`;
    $("updated").textContent = `· ${data.updated} 갱신`;
    document.title = `${data.name} 점심 빙고 — 매출 상위 24곳 도장깨기`;
    lastLines = lines(onCells()).length;
    renderBoard();
    renderAreaLists();
    renderFriend(params || new URLSearchParams());
    $("intro").hidden = true; $("boardView").hidden = false;
    const u = new URL(location.href);
    if (!params || params.get("a") !== id) { u.search = "?a=" + id; history.replaceState(null, "", u); }
  }

  function showIntro() {
    data = null; current = null;
    $("boardView").hidden = true; $("intro").hidden = false; $("areaName").textContent = "동네 고르기";
  }

  function draw() {
    if (loading || !data) return;
    clearTimeout(drawTimer);
    const left = data.stores.map((st, i) => (isOn(st) ? -1 : i)).filter((i) => i >= 0);
    if (!left.length) { toast("이미 다 가봤어요. 다음 달 새 판을 기다려 주세요"); return; }
    const i = left[Math.floor(Math.random() * left.length)];
    document.querySelectorAll(".cell.hl").forEach((el) => el.classList.remove("hl"));
    const el = document.querySelector(`.cell[data-i="${i}"]`);
    if (el) { el.classList.add("hl"); el.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    const request = areaRequest;
    drawTimer = setTimeout(() => { if (request === areaRequest) openStore(i); }, 650);
  }

  async function share() {
    if (loading || !data) return;
    const url = `${location.origin}${location.pathname}?a=${data.id}&b=${data.board}&s=${bitmask()}`;
    const n = data.stores.filter(isOn).length, ln = lines(onCells()).length;
    const text = `${data.name} 점심 빙고, 나는 도장 ${n}개 · 빙고 ${ln}줄. 회사 앞 매출 상위 24곳 같이 깨요.`;
    if (navigator.share) {
      try { await navigator.share({ title: "점심 빙고", text, url }); return; } catch (e) { if (e && e.name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(`${text}\n${url}`); toast("링크를 복사했어요"); }
    catch { prompt("이 링크를 복사해 보내세요", url); }
  }

  // events
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-area]");
    if (a) { $("areaSheet").close(); openArea(a.dataset.area); return; }
    const cell = e.target.closest(".cell[data-i] button");
    if (cell) openStore(Number(cell.parentElement.dataset.i));
  });
  $("areaBtn").addEventListener("click", () => { renderAreaLists(); $("areaSheet").showModal(); });
  $("drawBtn").addEventListener("click", draw);
  $("shareBtn").addEventListener("click", share);
  $("sStamp").addEventListener("click", () => {
    if (loading || !data || current === null) return;
    const st = data.stores[current];
    if (isOn(st)) delete progress[st.u]; else progress[st.u] = today();
    save(); syncStampBtn();
    const stamped = isOn(st);
    renderBoard(stamped ? current : undefined);
    if (stamped) closeTimer = setTimeout(() => $("storeSheet").close(), 380);
  });
  for (const d of [$("storeSheet"), $("areaSheet")]) {
    d.addEventListener("click", (e) => { if (e.target === d) d.close(); }); // backdrop tap
  }

  // boot
  (async () => {
    try {
      const r = await fetch("data/areas.json", { cache: "no-cache" });
      const j = await r.json(); areas = j.areas;
    } catch { areas = []; }
    renderAreaLists();
    const params = new URLSearchParams(location.search);
    const want = params.get("a") || stamps.area;
    if (want && areas.some((a) => a.id === want)) openArea(want, params);
    else showIntro();
  })();
})();
