"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
const zl = (x) => (x === null || x === undefined ? "–" : Number(x).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " zł");
const num = (x, d = 0) => (x === null || x === undefined ? "–" : Number(x).toLocaleString("pl-PL", { maximumFractionDigits: d }));
const pct = (x) => (x === null || x === undefined ? "–" : (x >= 0 ? "+" : "") + Math.round(x * 100) + "%");
const signCls = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

const SEASONS = {
  all_year: "cały rok", valentines: "Walentynki", womens_day: "Dzień Kobiet", easter: "Wielkanoc",
  mothers_day: "Dzień Matki", childrens_day: "Dzień Dziecka", fathers_day: "Dzień Ojca", summer: "Lato",
  back_to_school: "Szkoła", halloween: "Halloween", black_friday: "Black Friday", christmas: "Święta BN", new_year: "Sylwester",
};

let PROFILE = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) { /* brak JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg) { alert(msg); }

// ------------------------------------------------------------------ zakładki
$$("#tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
  const loaders = { keywords: loadKeywords, settings: loadSettings, discover: loadSeasons };
  loaders[b.dataset.tab]?.();
}));

// ------------------------------------------------------------------ elementy wspólne
function spark(values, w = 90, h = 24) {
  if (!values || values.length < 2) return '<span class="muted">–</span>';
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / (max - min || 1)) * (h - 2) - 1}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="var(--accent)" stroke-width="1.5" points="${pts}"/></svg>`;
}
const tierBadge = (t) => `<span class="badge tier-${esc(t.id)}">${esc(t.label)}</span>`;
const scoreBar = (s) => `<div class="scorebar"><div class="bar"><i style="width:${Math.max(0, Math.min(100, s))}%"></i></div><b>${num(s)}</b></div>`;
const ipBadge = (ip) => (ip && ip.level !== "none" ? ` <span class="badge ip-${esc(ip.level)}" title="${esc(ip.note)}">IP ${ip.level === "high" ? "!" : "?"}</span>` : "");
const demoBadge = (d) => (d ? ' <span class="badge demo">DEMO</span>' : "");
function licBadge(l) {
  if (!l) return "";
  const cls = { allowed: "lic-ok", attribution: "lic-attr", no_derivatives: "lic-attr", paid: "lic-paid", non_commercial: "lic-no", unknown: "lic-unknown" }[l.status];
  return `<span class="badge ${cls}" title="${esc(l.note)}">${esc(l.label)}</span>`;
}
function links(el, obj) {
  el.innerHTML = "Szukaj też w: " + Object.entries(obj || {}).map(([k, u]) => `<a href="${esc(safeUrl(u) || "#")}" target="_blank" rel="noopener">${esc(k)}</a>`).join(" · ");
}
function fillSelects() {
  if (!PROFILE) return;
  $$(".fil-select").forEach((s) => {
    const keep = s.querySelector('option[value=""]');
    s.innerHTML = (keep ? keep.outerHTML : "") + PROFILE.filaments.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join("");
    if (!keep) s.value = PROFILE.default_filament;
  });
  $$(".prn-select").forEach((s) => { s.innerHTML = PROFILE.printers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join(""); s.value = PROFILE.default_printer; });
  $$(".fee-select").forEach((s) => { s.innerHTML = PROFILE.fees.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join(""); s.value = PROFILE.default_channel; });
}

// ------------------------------------------------------------------ status
async function loadStatus() {
  const st = await api("/api/status");
  const demo = [...st.markets, ...st.trends, ...st.models].filter((p) => p.demo).map((p) => p.label);
  const banner = $("#demo-banner");
  if (demo.length) {
    banner.textContent = `Tryb DEMO dla: ${demo.join(", ")}. To przykładowe dane, nie prawdziwy rynek. Dodaj klucze API w pliku .env, żeby włączyć prawdziwe źródła.`;
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
  renderScan(st.scan);
  return st;
}

// ------------------------------------------------------------------ okazje
let scanTimer = null;
function renderScan(s) {
  const el = $("#scan-status");
  if (!s) return;
  if (s.running) el.textContent = `Skanowanie... ${s.done}/${s.total}`;
  else if (s.finished_at) el.textContent = `Ostatni skan: ${new Date(s.finished_at * 1000).toLocaleString("pl-PL")}` + (s.errors.length ? ` · błędy: ${s.errors.length}` : "");
  else el.textContent = "";
}
async function startScan(refresh) {
  await api("/api/scan", { method: "POST", body: JSON.stringify({ refresh }) });
  clearInterval(scanTimer);
  scanTimer = setInterval(async () => {
    const st = await api("/api/status");
    renderScan(st.scan);
    await loadOpps();
    if (!st.scan.running) clearInterval(scanTimer);
  }, 1500);
}
$("#scan-btn").addEventListener("click", () => startScan(false));
$("#scan-refresh-btn").addEventListener("click", () => startScan(true));
$("#opp-sort").addEventListener("change", loadOpps);
$("#opp-cat").addEventListener("change", loadOpps);

let OPPS = [];
async function loadOpps() {
  const params = new URLSearchParams({ sort: $("#opp-sort").value });
  if ($("#opp-cat").value) params.set("category", $("#opp-cat").value);
  OPPS = await api("/api/opportunities?" + params);
  const cats = [...new Set((await api("/api/keywords")).map((k) => k.category).filter(Boolean))].sort();
  const cur = $("#opp-cat").value;
  $("#opp-cat").innerHTML = '<option value="">wszystkie</option>' + cats.map((c) => `<option ${c === cur ? "selected" : ""}>${esc(c)}</option>`).join("");
  $("#opp-empty").classList.toggle("hidden", OPPS.length > 0);
  $("#opp-table tbody").innerHTML = OPPS.map((o, i) => {
    const m = o.at_market || {};
    return `<tr class="clickable" data-i="${i}">
      <td>${i + 1}</td>
      <td>${tierBadge(o.tier)}<br>${scoreBar(o.score)}</td>
      <td><b>${esc(o.keyword)}</b>${ipBadge(o.ip)}${demoBadge(o.demo)}<br><span class="muted">${esc(o.category || "")}</span></td>
      <td>${spark(o.trend.spark)} <span class="${signCls(o.trend.momentum)}">${pct(o.trend.momentum)}</span></td>
      <td class="num">${num(o.market.total_listings)}</td>
      <td class="num">${zl(o.market.reference_price)}</td>
      <td class="num">${zl(o.cost.total)}</td>
      <td class="num ${signCls(m.profit)}">${zl(m.profit)}</td>
      <td class="num ${signCls(m.profit_per_hour)}">${zl(m.profit_per_hour)}</td>
      <td>${o.season.event ? esc(o.season.event) : '<span class="muted">–</span>'}</td>
      <td><button class="small" data-models="${esc(o.keyword)}">Modele</button></td></tr>`;
  }).join("");
}
$("#opp-table").addEventListener("click", (e) => {
  const mb = e.target.closest("[data-models]");
  if (mb) { e.stopPropagation(); gotoModels(mb.dataset.models); return; }
  const tr = e.target.closest("tr[data-i]");
  if (tr) showOpp(OPPS[+tr.dataset.i]);
});

function costTable(c) {
  const rows = [["Filament (" + num(c.filament_g, 1) + " g, " + esc(c.filament) + ")", c.material], ["Prąd", c.energy], ["Amortyzacja drukarki", c.depreciation],
    ["Serwis / części", c.maintenance], ["Nieudane wydruki", c.failure_allowance], ["Praca ręczna", c.labor], ["Opakowanie", c.packaging], ["Licencja / plik (na szt.)", c.license]];
  return `<table class="data">${rows.map(([k, v]) => `<tr><td>${k}</td><td class="num">${zl(v)}</td></tr>`).join("")}
    <tr><td><b>Razem</b></td><td class="num"><b>${zl(c.total)}</b></td></tr></table>
    <p class="muted">Czas maszyny na sztukę: ${num(c.machine_time_h, 2)} h · ${esc(c.printer)}</p>`;
}
function priceBlock(title, p) {
  if (!p) return "";
  return `<h3>${esc(title)}</h3><div class="kv"><span>Cena</span><span>${zl(p.price)}</span><span>Prowizja ${esc(p.channel)}</span><span>${zl(p.fees)}</span>
    ${p.vat ? `<span>VAT</span><span>${zl(p.vat)}</span>` : ""}<span>Zysk / szt.</span><span class="${signCls(p.profit)}"><b>${zl(p.profit)}</b></span>
    <span>Marża</span><span>${num(p.margin * 100, 1)}%</span><span>Zysk / h drukarki</span><span class="${signCls(p.profit_per_hour)}">${zl(p.profit_per_hour)}</span></div>`;
}
function openDrawer(html) { $("#drawer-body").innerHTML = html; $("#drawer").classList.remove("hidden"); }
$("#drawer-close").addEventListener("click", () => $("#drawer").classList.add("hidden"));

async function showOpp(o) {
  const src = o.market.sources.map((s) => `<li>${esc(s.label)}: ${s.error ? `<span class="neg">${esc(s.error)}</span>` : `${num(s.total)} ofert (pobrano ${s.count})`}</li>`).join("");
  const st = o.market.stats || {};
  openDrawer(`<h2>${esc(o.keyword)} ${tierBadge(o.tier)}</h2>
    <p>Wynik <b>${num(o.score, 1)}</b>/100 · popyt ${o.subscores.demand} · konkurencja ${o.subscores.competition} · marża ${o.subscores.margin} · sezon ${o.subscores.season}</p>
    <ul>${o.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    ${o.ip.level !== "none" ? `<p class="neg">${esc(o.ip.note)}</p>` : ""}
    <h3>Ceny konkurencji</h3><div class="kv"><span>Min</span><span>${zl(st.min)}</span><span>25%</span><span>${zl(st.p25)}</span><span>Mediana</span><span>${zl(st.median)}</span>
      <span>75%</span><span>${zl(st.p75)}</span><span>Max</span><span>${zl(st.max)}</span><span>Cena odniesienia (${esc(o.market.reference)})</span><span>${zl(o.market.reference_price)}</span></div>
    <ul>${src}</ul>
    ${o.trend.error ? `<p class="muted">Trend: ${esc(o.trend.error)}</p>` : ""}
    <h3>Koszt produkcji</h3>${costTable(o.cost)}
    ${priceBlock("Przy cenie rynkowej", o.at_market)}${priceBlock("Cena minimalna (docelowa marża)", o.suggested)}
    <h3>Historia</h3><div id="hist"></div>
    <p><button class="primary" data-models2="${esc(o.keyword)}">Szukaj modeli</button> <button data-market2="${esc(o.keyword)}" data-en="${esc(o.keyword_en || "")}">Pokaż konkurencję</button></p>`);
  $("#drawer [data-models2]").onclick = () => gotoModels(o.keyword);
  $("#drawer [data-market2]").onclick = () => gotoMarket(o.keyword, o.keyword_en);
  const h = await api("/api/history?q=" + encodeURIComponent(o.keyword));
  $("#hist").innerHTML = h.length < 2 ? '<p class="muted">Historia buduje się z każdym dziennym skanem.</p>'
    : `<table class="data"><tr><th>Dzień</th><th class="num">Oferty</th><th class="num">Mediana</th><th class="num">Sprzedaż</th><th class="num">Trend</th></tr>
      ${h.slice(-30).reverse().map((r) => `<tr><td>${esc(r.day)}</td><td class="num">${num(r.total_listings)}</td><td class="num">${zl(r.median_price)}</td><td class="num">${num(r.sold_sum)}</td><td class="num">${num(r.trend_level)}</td></tr>`).join("")}</table>`;
}

function gotoTab(name) { $(`#tabs button[data-tab="${name}"]`).click(); $("#drawer").classList.add("hidden"); }
function gotoModels(q) { gotoTab("models"); $("#models-q").value = q; $("#models-form").requestSubmit(); }
function gotoMarket(q, qen) { gotoTab("market"); $("#market-q").value = q; $("#market-qen").value = qen || ""; $("#market-form").requestSubmit(); }

// ------------------------------------------------------------------ modele
let MODELS = [];
$("#models-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const p = new URLSearchParams({ q: $("#models-q").value, sort: $("#models-sort").value, commercial_only: $("#models-commercial").checked });
  if ($("#models-maxcost").value) p.set("max_license_cost", $("#models-maxcost").value);
  if ($("#models-w").value) p.set("weight_g", $("#models-w").value);
  if ($("#models-t").value) p.set("time_h", $("#models-t").value);
  if ($("#models-fil").value) p.set("filament", $("#models-fil").value);
  $("#models-meta").textContent = "Szukam...";
  $("#models-results").innerHTML = "";
  try {
    const r = await api("/api/models?" + p);
    MODELS = r.hits;
    const srcs = r.sources.map((s) => `${esc(s.label)}: ${s.error ? `<span class="neg" title="${esc(s.error)}">błąd</span>` : s.count}`).join(" · ");
    $("#models-meta").innerHTML = `${r.hits.length} modeli · ${srcs} · cena odniesienia: <b>${zl(r.reference_price)}</b> (${esc(r.reference || "brak")})` +
      (r.matched_keyword ? ` · parametry z frazy „${esc(r.matched_keyword)}”` : "");
    $("#models-results").innerHTML = r.hits.map((h, i) => {
      const m = h.at_market || {};
      const img = safeUrl(h.image) ? `<img loading="lazy" src="${esc(h.image)}" alt="">` : "";
      const url = safeUrl(h.url);
      return `<div class="card">${img}<div class="body">
        <div class="title">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(h.title)}</a>` : esc(h.title)}${ipBadge(h.ip)}${demoBadge(h.demo)}</div>
        <div class="muted">${esc(h.source)} · ${esc(h.author || "")} · ♥ ${num(h.likes)} · ⬇ ${num(h.downloads)}</div>
        <div>${licBadge(h.license)} ${h.license_total_pln ? `<span class="muted">koszt: ${zl(h.license_total_pln)}</span>` : ""}</div>
        ${h.license.note ? `<div class="muted" style="font-size:12px">${esc(h.license.note)}</div>` : ""}
        <div class="kv"><span>Waga / czas (${esc(h.weight_source)})</span><span>${num(h.weight_g, 1)} g · ${num(h.time_h, 2)} h</span>
          <span>Koszt / szt.</span><span>${zl(h.cost.total)}</span>
          <span>Zysk / szt.</span><span class="${signCls(m.profit)}">${zl(m.profit)}</span>
          <span>Zysk / h</span><span class="${signCls(m.profit_per_hour)}">${zl(m.profit_per_hour)}</span>
          <span>Cena min. (marża)</span><span>${zl(h.suggested.price)}</span></div>
        <div class="scorebar"><div class="bar"><i style="width:${h.score}%"></i></div><b>${num(h.score)}</b><span class="muted">opłacalność</span>
          <span class="spacer"></span><button class="small" data-calc="${i}">Kalkulator</button></div>
      </div></div>`;
    }).join("") || '<div class="empty">Brak wyników dla tych filtrów.</div>';
    links($("#models-links"), r.links);
  } catch (err) { $("#models-meta").textContent = "Błąd: " + err.message; }
});
$("#models-results").addEventListener("click", (e) => {
  const b = e.target.closest("[data-calc]");
  if (!b) return;
  const h = MODELS[+b.dataset.calc];
  gotoTab("calc");
  const f = $("#calc-form");
  f.weight_g.value = h.weight_g; f.print_time_h.value = h.time_h; f.license_cost_pln.value = h.license_total_pln || 0;
  if (h.at_market) f.sale_price_pln.value = h.at_market.price;
  f.requestSubmit();
});

// ------------------------------------------------------------------ konkurencja
$("#market-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const p = new URLSearchParams({ q: $("#market-q").value, refresh: $("#market-refresh").checked });
  if ($("#market-qen").value) p.set("q_en", $("#market-qen").value);
  $("#market-summary").innerHTML = '<p class="muted">Pobieram oferty...</p>';
  try {
    const r = await api("/api/market?" + p);
    const s = r.stats;
    const per = r.sources.map((x) => `<div class="stat"><small>${esc(x.label)}${demoBadge(x.demo)}</small>${x.error ? `<span class="neg" title="${esc(x.error)}">błąd: ${esc(x.error.slice(0, 80))}</span>` :
      `<b>${zl(x.stats.median)}</b><small>${num(x.total)} ofert · ${zl(x.stats.min)}–${zl(x.stats.max)}${x.stats.sold_sum != null ? " · sprzedano " + num(x.stats.sold_sum) : ""}</small>`}</div>`).join("");
    $("#market-summary").innerHTML = `${r.ip.level !== "none" ? `<p class="neg">${esc(r.ip.note)} (${esc(r.ip.hits.join(", "))})</p>` : ""}
      <div class="stats"><div class="stat"><small>Wszystkie oferty</small><b>${num(r.total_listings)}</b></div>
      <div class="stat"><small>Mediana (PLN)</small><b>${zl(s.median)}</b></div><div class="stat"><small>Przedział 25–75%</small><b>${zl(s.p25)} – ${zl(s.p75)}</b></div>
      <div class="stat"><small>Min / max</small><b>${zl(s.min)} / ${zl(s.max)}</b></div></div><div class="stats">${per}</div>`;
    $("#market-table tbody").innerHTML = r.listings.map((l) => {
      const u = safeUrl(l.url);
      return `<tr><td>${esc(l.source)}</td><td>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(l.title)}</a>` : esc(l.title)}</td>
      <td class="num">${num(l.price, 2)} ${esc(l.currency)}</td><td class="num">${zl(l.price_pln)}</td><td class="num">${num(l.sold ?? l.favorites)}</td><td>${esc(l.seller || "")}</td></tr>`;
    }).join("");
    links($("#market-links"), r.links);
  } catch (err) { $("#market-summary").textContent = "Błąd: " + err.message; }
});

// ------------------------------------------------------------------ kalkulator
function formJson(form) {
  const o = {};
  new FormData(form).forEach((v, k) => { if (v !== "") o[k] = isNaN(v) || ["printer_id", "filament_id", "channel"].includes(k) ? v : Number(v); });
  return o;
}
function renderCalc(r, extra = "") {
  $("#calc-result").innerHTML = `<h2>Wynik</h2>${extra}${costTable(r.cost)}${priceBlock("Cena minimalna (docelowa marża)", r.suggested)}${priceBlock("Przy Twojej cenie", r.at_price)}`;
}
$("#calc-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { renderCalc(await api("/api/cost", { method: "POST", body: JSON.stringify(formJson(e.target)) })); } catch (err) { toast(err.message); }
});
const dz = $("#dropzone");
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.add("over")));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("over")));
$("#file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const f = $("#calc-form");
  const fd = new FormData();
  fd.append("file", file); fd.append("filament_id", f.filament_id.value); fd.append("printer_id", f.printer_id.value);
  $("#file-info").textContent = "Analizuję " + file.name + "...";
  try {
    const r = await api("/api/analyze-file", { method: "POST", body: fd });
    const a = r.analysis;
    $("#file-info").innerHTML = `<b>${esc(file.name)}</b>: ${a.exact ? "dane ze slicera" : "szacunek z siatki"} · ${num(a.weight_g, 1)} g · ${num(a.print_time_h, 2)} h` +
      (a.plates ? ` · płyt: ${a.plates}` : "") + (a.bbox_mm ? ` · ${a.bbox_mm.join(" × ")} mm` : "") + (a.filament_type ? ` · ${esc(a.filament_type)}` : "") +
      (a.note ? `<br><span class="muted">${esc(a.note)}</span>` : "");
    if (a.weight_g) f.weight_g.value = a.weight_g;
    if (a.print_time_h) f.print_time_h.value = a.print_time_h;
    if (a.color_changes) f.color_changes.value = a.color_changes;
    f.requestSubmit();
  } catch (err) { $("#file-info").textContent = "Błąd: " + err.message; }
  e.target.value = "";
});

// ------------------------------------------------------------------ trendy i sezony
async function loadSeasons() {
  const ev = await api("/api/seasons?days=150");
  const html = ev.map((e) => `<div class="chip ${e.in_window ? "hot" : ""}"><b>${esc(e.name)}</b> · ${esc(e.date)} · za ${e.days_to_event} dni<br>
    <span class="muted">${e.in_window ? "Okno sprzedaży trwa (do " + esc(e.window_end) + ")" : "Okno od " + esc(e.window_start)}</span></div>`).join("");
  $("#seasons-list").innerHTML = `<div class="strip">${html || '<span class="muted">Brak wydarzeń</span>'}</div>`;
  $("#season-strip").innerHTML = ev.slice(0, 4).map((e) => `<div class="chip ${e.in_window ? "hot" : ""}">${esc(e.name)}: za ${e.days_to_event} dni${e.in_window ? " · sprzedawaj teraz" : ""}</div>`).join("");
}
$("#discover-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#discover-list").innerHTML = '<p class="muted">Szukam...</p>';
  try {
    const rows = await api("/api/discover?seeds=" + encodeURIComponent($("#discover-seeds").value));
    $("#discover-list").innerHTML = rows.length ? `<table class="data"><tr><th>Fraza</th><th>Wzrost</th><th>Źródło</th><th></th></tr>${rows.map((r) =>
      `<tr><td>${esc(r.query)}${ipBadge(r.ip)}</td><td>${esc(typeof r.growth === "number" ? "+" + r.growth + "%" : r.growth)}</td><td class="muted">${esc(r.seed)}</td>
      <td><button class="small" data-add="${esc(r.query)}">Obserwuj</button></td></tr>`).join("")}</table>` : '<p class="muted">Brak nowych fraz (lub źródło trendów niedostępne).</p>';
  } catch (err) { $("#discover-list").textContent = "Błąd: " + err.message; }
});
$("#discover-list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-add]");
  if (!b) return;
  try { await api("/api/keywords", { method: "POST", body: JSON.stringify({ keyword: b.dataset.add, category: "Odkryte" }) }); b.textContent = "Dodano"; b.disabled = true; }
  catch (err) { toast(err.message); }
});
$("#trend-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const t = await api("/api/trend?q=" + encodeURIComponent($("#trend-q").value));
  const vals = t.points.map((p) => p.value);
  $("#trend-chart").innerHTML = t.error && !vals.length ? `<p class="neg">${esc(t.error)}</p>` :
    `<p>${demoBadge(t.demo)} Momentum: <b class="${signCls(t.momentum)}">${pct(t.momentum)}</b> · poziom ${num(t.level)} / 100 · ${t.points.length} tygodni</p>${spark(vals, 700, 120)}
     <p class="muted">${esc(t.points[0]?.date || "")} → ${esc(t.points.at(-1)?.date || "")}</p>`;
});

// ------------------------------------------------------------------ frazy
async function loadKeywords() {
  const kws = await api("/api/keywords");
  const fil = (v) => PROFILE.filaments.map((f) => `<option value="${esc(f.id)}" ${f.id === v ? "selected" : ""}>${esc(f.name)}</option>`).join("");
  $("#kw-table tbody").innerHTML = kws.map((k) => `<tr data-id="${k.id}">
    <td><input type="checkbox" data-f="active" ${k.active ? "checked" : ""}></td><td><b>${esc(k.keyword)}</b></td>
    <td><input data-f="keyword_en" value="${esc(k.keyword_en || "")}"></td><td><input data-f="category" value="${esc(k.category || "")}" class="num"></td>
    <td><input data-f="weight_g" type="number" step="0.1" value="${k.weight_g}" class="num"></td><td><input data-f="time_h" type="number" step="0.05" value="${k.time_h}" class="num"></td>
    <td><select data-f="filament">${fil(k.filament)}</select></td><td><input data-f="post_min" type="number" value="${k.post_min}" class="num"></td>
    <td class="muted">${k.seasons.map((s) => esc(SEASONS[s] || s)).join(", ")}</td>
    <td><button class="small" data-del="${k.id}">Usuń</button></td></tr>`).join("");
  $("#kw-seasons").innerHTML = Object.entries(SEASONS).map(([k, v]) => `<option value="${k}" ${k === "all_year" ? "selected" : ""}>${v}</option>`).join("");
  $("#kw-seasons").size = 4;
}
$("#kw-table").addEventListener("change", async (e) => {
  const el = e.target.closest("[data-f]");
  if (!el) return;
  const id = el.closest("tr").dataset.id;
  const v = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
  try { await api(`/api/keywords/${id}`, { method: "PATCH", body: JSON.stringify({ [el.dataset.f]: v }) }); } catch (err) { toast(err.message); }
});
$("#kw-table").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]");
  if (!b || !confirm("Usunąć frazę?")) return;
  await api(`/api/keywords/${b.dataset.del}`, { method: "DELETE" });
  loadKeywords();
});
$("#kw-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { keyword: f.keyword.value, keyword_en: f.keyword_en.value || null, category: f.category.value || "Inne",
    weight_g: Number(f.weight_g.value), time_h: Number(f.time_h.value), filament: f.filament.value,
    seasons: [...$("#kw-seasons").selectedOptions].map((o) => o.value) };
  try { await api("/api/keywords", { method: "POST", body: JSON.stringify(body) }); f.reset(); loadKeywords(); } catch (err) { toast(err.message); }
});

// ------------------------------------------------------------------ ustawienia
const GENERAL = [
  ["energy_price_kwh_pln", "Cena prądu [zł/kWh]"], ["labor_rate_h_pln", "Stawka pracy [zł/h]"], ["packaging_pln", "Opakowanie [zł/szt.]"],
  ["failure_rate", "Nieudane wydruki (0.05 = 5%)"], ["waste_pct", "Odpad filamentu (0.05 = 5%)"], ["target_margin", "Docelowa marża (0.35 = 35%)"],
  ["target_profit_per_hour_pln", "Zysk/h uznawany za świetny [zł]"], ["expected_units_per_model", "Sztuk na jeden zakupiony model"],
  ["vat_rate", "Stawka VAT"], ["vat_payer", "Płatnik VAT"], ["default_printer", "Domyślna drukarka"], ["default_filament", "Domyślny filament"], ["default_channel", "Główny kanał sprzedaży"],
];
function editTable(el, rows, cols) {
  el.innerHTML = `<div class="table-wrap"><table class="data edit-table"><tr>${cols.map((c) => `<th>${esc(c[1])}</th>`).join("")}<th></th></tr>
    ${rows.map((r, i) => `<tr data-i="${i}">${cols.map(([k, , t]) => `<td><input data-k="${k}" ${t === "n" ? 'type="number" step="any"' : ""} value="${esc(r[k])}"></td>`).join("")}
    <td><button class="small" data-rm="${i}">×</button></td></tr>`).join("")}</table></div><button class="small" data-addrow>+ dodaj</button>`;
  el.oninput = (e) => { const inp = e.target.closest("[data-k]"); if (!inp) return; const r = rows[+inp.closest("tr").dataset.i]; r[inp.dataset.k] = inp.type === "number" ? Number(inp.value) : inp.value; };
  el.onclick = (e) => {
    if (e.target.dataset.rm !== undefined) { rows.splice(+e.target.dataset.rm, 1); editTable(el, rows, cols); }
    if (e.target.dataset.addrow !== undefined) { rows.push(Object.fromEntries(cols.map(([k, , t]) => [k, t === "n" ? 0 : k === "id" ? "nowy" + rows.length : ""]))); editTable(el, rows, cols); }
  };
}
async function loadSettings() {
  PROFILE = await api("/api/profile");
  const st = await loadStatus();
  const grp = (t, list) => `<p><b>${t}</b><br>${list.map((p) => `${esc(p.label)}${p.demo ? ' <span class="badge demo">DEMO</span>' : ' <span class="badge lic-ok">aktywne</span>'}`).join("<br>") || '<span class="muted">brak</span>'}</p>`;
  $("#sources-status").innerHTML = grp("Rynki", st.markets) + grp("Trendy", st.trends) + grp("Modele", st.models) + `<p class="muted">Kursy walut: ${st.fx_live ? "NBP (na żywo)" : "awaryjne (NBP niedostępne)"}</p>`;
  const opt = (list, v) => list.map((x) => `<option value="${esc(x.id)}" ${x.id === v ? "selected" : ""}>${esc(x.name)}</option>`).join("");
  $("#general-form").innerHTML = GENERAL.map(([k, l]) => {
    if (k === "vat_payer") return `<label>${l}<select data-g="${k}"><option value="false">nie</option><option value="true" ${PROFILE.vat_payer ? "selected" : ""}>tak</option></select></label>`;
    if (k === "default_printer") return `<label>${l}<select data-g="${k}">${opt(PROFILE.printers, PROFILE[k])}</select></label>`;
    if (k === "default_filament") return `<label>${l}<select data-g="${k}">${opt(PROFILE.filaments, PROFILE[k])}</select></label>`;
    if (k === "default_channel") return `<label>${l}<select data-g="${k}">${opt(PROFILE.fees, PROFILE[k])}</select></label>`;
    return `<label>${l}<input data-g="${k}" type="number" step="any" value="${PROFILE[k]}"></label>`;
  }).join("") + ["margin", "demand", "competition", "season"].map((w) => `<label>Waga scoringu: ${w}<input data-w="${w}" type="number" step="0.05" value="${PROFILE.weights[w]}"></label>`).join("");
  editTable($("#printers-edit"), PROFILE.printers, [["id", "ID"], ["name", "Nazwa"], ["price_pln", "Cena zł", "n"], ["lifetime_hours", "Żywotność h", "n"], ["avg_power_w", "Moc W", "n"],
    ["maintenance_per_hour_pln", "Serwis zł/h", "n"], ["throughput_g_per_h", "Wydajność g/h", "n"], ["plate_overhead_min", "Narzut stołu min", "n"], ["purge_g_per_color_change", "Purge AMS g", "n"]]);
  editTable($("#filaments-edit"), PROFILE.filaments, [["id", "ID"], ["name", "Nazwa"], ["price_per_kg_pln", "Cena zł/kg", "n"], ["density_g_cm3", "Gęstość g/cm³", "n"]]);
  editTable($("#fees-edit"), PROFILE.fees, [["id", "ID"], ["name", "Nazwa"], ["percent", "Prowizja (0.11 = 11%)", "n"], ["fixed_pln", "Opłata stała zł", "n"], ["note", "Uwagi"]]);
}
$("#profile-save").addEventListener("click", async () => {
  $$("#general-form [data-g]").forEach((el) => { PROFILE[el.dataset.g] = el.dataset.g === "vat_payer" ? el.value === "true" : el.tagName === "SELECT" ? el.value : Number(el.value); });
  $$("#general-form [data-w]").forEach((el) => { PROFILE.weights[el.dataset.w] = Number(el.value); });
  try {
    PROFILE = await api("/api/profile", { method: "PUT", body: JSON.stringify(PROFILE) });
    fillSelects();
    $("#profile-msg").textContent = "Zapisano. Kliknij „Skanuj” w zakładce Okazje, żeby przeliczyć wyniki.";
  } catch (err) { toast(err.message); }
});
$("#profile-reset").addEventListener("click", async () => {
  if (!confirm("Przywrócić domyślne ustawienia?")) return;
  await api("/api/profile/reset", { method: "POST" });
  loadSettings();
});

// ------------------------------------------------------------------ start
(async function init() {
  PROFILE = await api("/api/profile");
  fillSelects();
  await loadStatus();
  await loadSeasons();
  await loadOpps();
  const st = await api("/api/status");
  if (st.scan.running) startScan(false);
})();
