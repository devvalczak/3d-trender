"use strict";
// Asystent: jeden lejek trendy -> modele -> stół -> zysk. Korzysta z pomocników z app.js.

const FLOW_STAGES = ["Trendy", "Modele", "Stół", "Zysk"];
const FLOW_FIELDS = [
  ["top_n", "Ile fraz w lejku", "int"], ["models_per_item", "Modeli na frazę", "int"],
  ["commercial_only", "Tylko licencje do sprzedaży", "bool"], ["max_license_cost_pln", "Max koszt licencji [zł]", "num?"],
  ["printer_id", "Drukarka", "printer"], ["spacing_mm", "Odstęp między obiektami [mm]", "num"], ["margin_mm", "Margines stołu [mm]", "num"],
  ["attended_hours", "Godziny obsługi dziennie", "num"], ["allow_night", "Płyta na noc", "bool"], ["swap_min", "Zmiana płyty [min]", "num"],
  ["paint_min_per_color", "Malowanie: min / kolor / szt.", "num"], ["market_share", "Udział w rynku (0.15 = 15%)", "num"],
  ["plan_days", "Plan na ile dni", "int"], ["download_files", "Pobieraj pliki modeli", "bool"], ["refresh", "Pomiń cache API", "bool"],
];
const LIVE_PARAMS = ["printer_id", "spacing_mm", "margin_mm", "attended_hours", "allow_night", "swap_min", "paint_min_per_color", "market_share", "plan_days"];

let FLOW = null, FLOW_DEFAULTS = null, FLOW_TIMER = null;
const OPEN = new Set();

async function flowInit() {
  FLOW_DEFAULTS = await api("/api/flow/defaults");
  renderParams(FLOW_DEFAULTS.params);
  await loadRuns();
  const last = $("#flow-runs").options[1];
  if (last) { $("#flow-runs").value = last.value; await loadRun(last.value); }
  else renderFlow();
}

function renderParams(p) {
  $("#flow-params").innerHTML = FLOW_FIELDS.map(([k, label, t]) => {
    if (t === "bool") return `<label>${label}<select data-p="${k}"><option value="true" ${p[k] ? "selected" : ""}>tak</option><option value="false" ${!p[k] ? "selected" : ""}>nie</option></select></label>`;
    if (t === "printer") return `<label>${label}<select data-p="${k}">${FLOW_DEFAULTS.printers.map((x) => `<option value="${esc(x.id)}" ${x.id === p[k] ? "selected" : ""}>${esc(x.name)} (${x.bed.join("×")})</option>`).join("")}</select></label>`;
    return `<label>${label}<input data-p="${k}" type="number" step="any" min="0" value="${p[k] ?? ""}"></label>`;
  }).join("");
  const pr = FLOW_DEFAULTS.printers.find((x) => x.id === p.printer_id);
  $("#flow-params-sum").textContent = `· top ${p.top_n} · ${pr ? pr.name : ""} · odstęp ${p.spacing_mm} mm · ${p.attended_hours} h obsługi${p.allow_night ? " + noc" : ""}`;
}
function readParams() {
  const out = {};
  $$("#flow-params [data-p]").forEach((el) => {
    const t = FLOW_FIELDS.find((f) => f[0] === el.dataset.p)[2];
    if (t === "bool") out[el.dataset.p] = el.value === "true";
    else if (t === "printer") out[el.dataset.p] = el.value;
    else if (el.value === "") out[el.dataset.p] = null;
    else out[el.dataset.p] = t === "int" ? parseInt(el.value, 10) : Number(el.value);
  });
  return out;
}

async function loadRuns() {
  const runs = await api("/api/flow/runs");
  const cur = $("#flow-runs").value;
  $("#flow-runs").innerHTML = '<option value="">nowy</option>' + runs.map((r) =>
    `<option value="${esc(r.id)}">${new Date(r.created_at * 1000).toLocaleString("pl-PL")} · top ${r.params.top_n}</option>`).join("");
  if (cur) $("#flow-runs").value = cur;
}
async function loadRun(id) {
  FLOW = await api("/api/flow/" + encodeURIComponent(id));
  renderParams({ ...FLOW_DEFAULTS.params, ...FLOW.params });
  renderFlow();
  if (FLOW.status === "running") poll();
}
$("#flow-runs").addEventListener("change", (e) => { if (e.target.value) loadRun(e.target.value); else { FLOW = null; renderFlow(); } });

$("#flow-start").addEventListener("click", async () => {
  FLOW = await api("/api/flow", { method: "POST", body: JSON.stringify(readParams()) });
  OPEN.clear();
  renderFlow();
  poll();
});
$("#flow-params").addEventListener("change", () => $("#flow-apply").classList.toggle("hidden", !FLOW || FLOW.status !== "done"));
$("#flow-apply").addEventListener("click", async () => {
  const p = readParams();
  const live = Object.fromEntries(LIVE_PARAMS.map((k) => [k, p[k]]));
  await patchFlow({ params: live });
  $("#flow-apply").classList.add("hidden");
});

function poll() {
  clearInterval(FLOW_TIMER);
  FLOW_TIMER = setInterval(async () => {
    FLOW = await api("/api/flow/" + FLOW.id);
    renderFlow();
    if (FLOW.status !== "running") { clearInterval(FLOW_TIMER); await loadRuns(); $("#flow-runs").value = FLOW.id; }
  }, 1000);
}

async function patchFlow(body) {
  try { FLOW = await api("/api/flow/" + FLOW.id, { method: "PATCH", body: JSON.stringify(body) }); renderFlow(); }
  catch (err) { toast(err.message); }
}

// ------------------------------------------------------------------ render
function renderFlow() {
  const st = FLOW;
  $("#flow-steps").innerHTML = FLOW_STAGES.map((name, i) => {
    const cls = !st ? "" : st.status === "done" || i < st.stage ? "done" : i === st.stage && st.status === "running" ? "active" : "";
    const detail = !st ? "" : cls === "active" ? esc(st.progress || "...") : cls === "done" ? stageDetail(i, st) : "";
    return `<li class="${cls}"><b>${i + 1}. ${name}</b>${detail}</li>`;
  }).join("");
  $("#flow-error").textContent = st && st.error ? "Błąd: " + st.error : "";
  if (!st) {
    $("#flow-summary").innerHTML = '<div class="empty">Kliknij <b>Uruchom analizę</b>. Asystent przeanalizuje obserwowane frazy, znajdzie modele do sprzedaży, ułoży je na stole i policzy zysk na dzień.</div>';
    $("#flow-items").innerHTML = $("#flow-others").innerHTML = "";
    return;
  }
  if (st.status !== "done") { $("#flow-summary").innerHTML = ""; $("#flow-items").innerHTML = ""; return; }
  renderSummary(st);
  $("#flow-items").innerHTML = st.items.map((it, i) => renderItem(it, i)).join("");
  $("#flow-others").innerHTML = st.others && st.others.length ? `<div class="panel"><h2>Pozostałe frazy (poza lejkiem)</h2><div class="strip">${st.others.map((o) =>
    `<span class="chip">${esc(o.keyword)} · ${num(o.score)}${o.ip === "high" ? ' <span class="badge ip-high">IP !</span>' : ""} <button class="small" data-add-item="${o.keyword_id}">+ do lejka</button></span>`).join("")}</div></div>` : "";
}

function stageDetail(i, st) {
  const items = st.items || [];
  if (i === 0) return `<span>${items.length} w lejku z ${items.length + (st.others || []).length} fraz</span>`;
  if (i === 1) return `<span>${items.reduce((a, x) => a + x.models.total, 0)} modeli, ${items.reduce((a, x) => a + x.models.commercial, 0)} do sprzedaży</span>`;
  if (i === 2) return `<span>średnio ${num(items.reduce((a, x) => a + (x.plate?.units || 0), 0) / (items.length || 1), 1)} szt./płyta</span>`;
  return `<span>plan: ${zl(st.plan?.profit)} / ${st.plan?.days} dni</span>`;
}

function renderSummary(st) {
  const p = st.plan;
  const best = st.items.find((x) => !x.excluded);
  const fil = Object.entries(p.filament_kg || {}).map(([k, v]) => `${num(v, 2)} kg ${esc(k)}`).join(", ") || "–";
  const cmp = st.compare ? `<span class="muted">Porównanie z przebiegiem z ${new Date(st.compare.created_at * 1000).toLocaleString("pl-PL")}</span>` : "";
  $("#flow-summary").innerHTML = `<div class="summary-cards">
      <div class="stat"><small>Najlepszy produkt</small><b>${esc(best ? best.keyword : "–")}</b><small>${best ? zl(best.profit_day) + " / dzień" : ""}</small></div>
      <div class="stat"><small>Zysk z planu (${p.days} dni)</small><b>${zl(p.profit)}</b><small>${num(p.units)} szt.${p.idle_days ? ` · ${p.idle_days} dni wolnych` : ""}</small></div>
      <div class="stat"><small>Filament na plan</small><b>${fil}</b></div>
    </div>
    <details class="panel" open><summary><b>Plan produkcji</b> ${cmp}</summary>
      <div class="table-wrap"><table class="data"><tr><th>Produkt</th><th>Wariant</th><th class="num">Dni</th><th>Harmonogram dnia</th><th class="num">Sztuk</th><th class="num">Filament</th><th class="num">Zysk</th></tr>
      ${p.rows.map((r) => `<tr><td><b>${esc(r.keyword)}</b></td><td>${esc(r.variant)}</td><td class="num">${num(r.days, 1)}</td><td class="muted">${esc(r.schedule)}</td>
        <td class="num">${num(r.units)}${r.limited ? ' <span class="muted" title="Ograniczone szacowanym zbytem">(zbyt)</span>' : ""}</td><td class="num">${num(r.filament_g)} g ${esc(r.filament)}</td><td class="num pos">${zl(r.profit)}</td></tr>`).join("")}</table></div>
      <p class="muted">Dni przydzielane od najwyższego zysku/dzień, z limitem zbytu (${Math.round(st.params.market_share * 100)}% sprzedaży konkurencji), żeby nie drukować więcej, niż realnie sprzedasz.</p>
    </details>`;
}

function deltaBadge(d) {
  if (!d) return "";
  if (d.new) return '<span class="delta badge tier-better">nowe</span>';
  if (!d.profit_day) return "";
  return `<span class="delta ${signCls(d.profit_day)}">${d.profit_day > 0 ? "▲" : "▼"} ${zl(Math.abs(d.profit_day))}</span>`;
}

function renderItem(it, i) {
  const open = OPEN.has(it.keyword_id);
  const v = (it.variants || []).find((x) => x.id === it.best_variant);
  const o = it.opportunity;
  return `<div class="item ${it.excluded ? "excluded" : ""}" data-kid="${it.keyword_id}">
    <div class="item-head" data-toggle="${it.keyword_id}">
      <b>${i + 1}</b>
      <input type="checkbox" title="Uwzględnij w planie" data-include="${it.keyword_id}" ${it.excluded ? "" : "checked"}>
      <div>${tierBadge(it.tier)}${scoreBar(it.final_score)}</div>
      <div><b>${esc(it.keyword)}</b>${ipBadge(o.ip)}${demoBadge(o.demo)} ${deltaBadge(it.delta)}<br>
        <span class="muted">${esc(it.category || "")} · trend <span class="${signCls(o.trend.momentum)}">${pct(o.trend.momentum)}</span>${o.season.event ? " · " + esc(o.season.event) : ""}</span></div>
      <div class="kpi opt"><small>modele</small>${it.models.commercial}/${it.models.total}</div>
      <div class="kpi opt"><small>na płycie</small>${it.plate ? it.plate.units : "–"} szt.</div>
      <div class="kpi opt"><small>zysk/szt.</small><span class="${signCls(v?.at_price.profit)}">${zl(v?.at_price.profit)}</span></div>
      <div class="kpi opt"><small>${esc(v ? v.label : "")}</small>${v ? num(v.schedule.units_per_day) + " szt./d" : "–"}</div>
      <div class="kpi" title="Zysk przy pełnym wykorzystaniu drukarki; w nawiasie część, którą realnie sprzedasz"><small>zysk/dzień</small><b class="${signCls(it.profit_day)}">${zl(it.profit_day)}</b>${it.sellable_profit_day < it.profit_day ? `<small>sprzedasz: ${zl(it.sellable_profit_day)}</small>` : ""}</div>
      <span>${it.warnings.length ? `<span title="${esc(it.warnings.join("\n"))}" class="warn">⚠</span>` : ""}</span>
    </div>
    ${open ? renderItemBody(it) : ""}
  </div>`;
}

function renderItemBody(it) {
  const o = it.opportunity, s = it.spec, m = it.models;
  const cands = m.candidates.map((c, idx) => {
    const url = safeUrl(c.url);
    const f = c.file ? `<br><span class="pos">plik: ${esc(c.file.name)} (${c.file.exact ? "dane ze slicera" : "z siatki"})</span>` : c.file_error ? `<br><span class="neg" title="${esc(c.file_error)}">nie udało się pobrać pliku</span>` : "";
    return `<label class="cand ${s.candidate === idx ? "sel" : ""}"><input type="radio" name="cand-${it.keyword_id}" data-cand="${idx}" ${s.candidate === idx ? "checked" : ""}>
      <span>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(c.title)}</a>` : esc(c.title)}<br>
      <span class="muted">${esc(c.source)} · ♥ ${num(c.likes)}</span> ${licBadge(c.license)}${c.license_total_pln ? ` <span class="muted">${zl(c.license_total_pln)}</span>` : ""}${f}</span></label>`;
  }).join("");
  const none = `<label class="cand ${s.candidate === null ? "sel" : ""}"><input type="radio" name="cand-${it.keyword_id}" data-cand="-1" ${s.candidate === null ? "checked" : ""}><span>Bez modelu: własny projekt / parametry z frazy</span></label>`;
  const srcErr = (m.sources || []).filter((x) => x.error).map((x) => `${esc(x.label)}: błąd`).join(", ");
  const fil = PROFILE.filaments.map((f) => `<option value="${esc(f.id)}" ${f.id === s.filament ? "selected" : ""}>${esc(f.name)}</option>`).join("");
  const variants = it.variants.map((v) => !v.fits ? `<tr><td>${esc(v.label)}</td><td colspan="6" class="neg">nie mieści się</td></tr>` :
    `<tr class="${v.id === it.best_variant ? "best" : ""}"><td><b>${esc(v.label)}</b>${v.color_changes ? `<br><span class="muted">${v.color_changes} zmian/płytę</span>` : ""}${v.post_min ? `<br><span class="muted">obróbka ${num(v.post_min)} min</span>` : ""}</td>
      <td class="num">${zl(v.cost.total)}</td><td class="num ${signCls(v.at_price.profit)}">${zl(v.at_price.profit)}</td>
      <td class="num">${num(v.plate_h, 1)} h<br><span class="muted">${zl(v.profit_plate)}</span></td>
      <td>${esc(v.schedule ? v.schedule.label : "–")}<br><span class="muted">prosto: ${esc(v.simple ? v.simple.label + " → " + zl(v.simple.profit_per_day) : "–")}</span></td>
      <td class="num"><b>${zl(v.schedule?.profit_per_day)}</b></td></tr>`).join("");
  const L = it.listing;
  return `<div class="item-body">
    <div><h3>1 · Trend i rynek</h3>
      <p>Ocena rynku <b>${num(o.score, 1)}</b> · ${tierBadge(o.tier)}</p>${spark(o.trend.spark, 200, 36)}
      <ul>${o.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      <p class="muted">Cena odniesienia: <b>${zl(o.market.reference_price)}</b> (${esc(o.market.reference || "brak")})</p>
      <button class="small" data-goto-market="${esc(it.keyword)}" data-en="${esc(it.keyword_en || "")}">Szczegóły konkurencji</button></div>
    <div><h3>2 · Modele (${m.commercial} do sprzedaży z ${m.total})</h3>${cands}${none}
      ${srcErr ? `<p class="muted">${srcErr}</p>` : ""}
      <label class="muted" style="font-size:12px">Wgraj własny plik (.3mf z Bambu Studio / .stl / .gcode)<input type="file" data-upload="${it.keyword_id}" accept=".3mf,.stl,.gcode,.gco"></label>
      ${it.uploaded_file ? `<p class="pos" style="font-size:12px">Wgrano: ${esc(it.uploaded_file.name)}${it.uploaded_file.objects > 1 ? ` (${it.uploaded_file.objects} obiektów w projekcie, liczę na sztukę)` : ""}</p>` : ""}</div>
    <div><h3>3 · Stół: ${it.plate.units} szt.</h3>${plateSvg(it.plate)}
      <p class="muted" style="font-size:12px">Obiekt ${s.size.map((x) => num(x)).join(" × ")} mm (${esc(s.size_source || "")}) · odstęp ${num(it.plate.spacing)} mm</p></div>
    <div><h3>Parametry sztuki</h3>
      <form class="mini-form" data-spec="${it.keyword_id}">
        <label>X mm<input name="size_x" type="number" step="any" value="${s.size[0]}"></label>
        <label>Y mm<input name="size_y" type="number" step="any" value="${s.size[1]}"></label>
        <label>Z mm<input name="size_z" type="number" step="any" value="${s.size[2]}"></label>
        <label>Waga g<input name="unit_weight_g" type="number" step="any" value="${s.unit_weight_g}"></label>
        <label>Czas h<input name="unit_time_h" type="number" step="any" value="${s.unit_time_h}"></label>
        <label>Filament<select name="filament">${fil}</select></label>
        <label>Kolory<input name="colors" type="number" min="1" value="${s.colors}"></label>
        <label>Zmiany/płytę<input name="color_changes" type="number" min="0" value="${s.color_changes}"></label>
        <label>Cena zł<input name="sale_price_pln" type="number" step="any" value="${s.price ?? ""}"></label>
        <label>Obróbka min<input name="post_min" type="number" step="any" value="${s.post_min}"></label>
        <button class="small primary" style="grid-column: span 2">Przelicz</button>
        <button class="small" type="button" data-reset="${it.keyword_id}">Resetuj</button>
      </form>
      <p class="muted" style="font-size:12px">Waga/czas: ${esc(s.weight_source || "")} · cena: ${esc(s.price_source || "")}</p></div>
    <div class="wide"><h3>4 · Zysk: warianty i optymalny dzień (${num(FLOW.params.attended_hours)} h obsługi${FLOW.params.allow_night ? " + płyta na noc" : ""})</h3>
      <div class="table-wrap"><table class="data variants"><tr><th>Wariant</th><th class="num">Koszt/szt.</th><th class="num">Zysk/szt.</th><th class="num">Pełny stół</th><th>Optymalny harmonogram doby</th><th class="num">Zysk/dzień</th></tr>${variants}</table></div>
      ${it.cap_day != null ? `<p class="muted">Szacowany realny zbyt: ok. ${num(it.cap_day, 1)} szt./dzień</p>` : ""}
      ${it.warnings.map((w) => `<p class="warn">⚠ ${esc(w)}</p>`).join("")}</div>
    <div class="wide listing"><h3>Szkic aukcji</h3>
      <div class="grid2"><div><label class="muted">Tytuł (${L.title.length}/75)</label><input style="width:100%" value="${esc(L.title)}" readonly>
        <p>Proponowana cena: <b>${zl(L.price)}</b></p>${L.notes.map((n) => `<p class="warn">${esc(n)}</p>`).join("")}</div>
      <div><textarea readonly>${esc(L.description)}</textarea><button class="small" data-copy="${it.keyword_id}">Kopiuj tytuł i opis</button></div></div></div>
  </div>`;
}

function plateSvg(pl) {
  const W = 240, k = W / Math.max(pl.bed[0], pl.bed[1]), H = pl.bed[1] * k;
  const y = (yy, h) => H - (yy + h) * k;
  const ex = (pl.exclude || []).map((r) => `<rect x="${r[0] * k}" y="${y(r[1], r[3] - r[1])}" width="${(r[2] - r[0]) * k}" height="${(r[3] - r[1]) * k}" fill="var(--bad)" opacity=".35"/>`).join("");
  const pos = pl.positions.map((p) => `<rect x="${p[0] * k}" y="${y(p[1], p[3])}" width="${p[2] * k}" height="${p[3] * k}" rx="1.5" fill="var(--accent)" opacity=".75"/>`).join("");
  return `<svg class="plate-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Układ ${pl.units} sztuk na stole">
    <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="var(--row-hover)" stroke="var(--border)"/>${ex}${pos}</svg>`;
}

// ------------------------------------------------------------------ interakcje
$("#flow-items").addEventListener("click", async (e) => {
  const t = e.target;
  if (t.matches("[data-include]")) {
    e.stopPropagation();
    return patchFlow({ overrides: { [t.dataset.include]: { excluded: !t.checked } } });
  }
  if (t.dataset.reset) {
    try { FLOW = await api(`/api/flow/${FLOW.id}/items/${t.dataset.reset}/reset`, { method: "POST" }); renderFlow(); } catch (err) { toast(err.message); }
    return;
  }
  if (t.dataset.gotoMarket) return gotoMarket(t.dataset.gotoMarket, t.dataset.en);
  if (t.dataset.copy) {
    const it = FLOW.items.find((x) => String(x.keyword_id) === t.dataset.copy);
    try { await navigator.clipboard.writeText(`${it.listing.title}\n\n${it.listing.description}`); t.textContent = "Skopiowano"; } catch (_) { toast("Nie udało się skopiować"); }
    return;
  }
  const head = t.closest("[data-toggle]");
  if (head && !t.closest("input,button,a")) {
    const id = Number(head.dataset.toggle);
    OPEN.has(id) ? OPEN.delete(id) : OPEN.add(id);
    renderFlow();
  }
});
$("#flow-items").addEventListener("change", async (e) => {
  const t = e.target;
  if (t.dataset.cand !== undefined) {
    const kid = t.closest("[data-kid]").dataset.kid;
    return patchFlow({ overrides: { [kid]: { selected: Number(t.dataset.cand) } } });
  }
  if (t.dataset.upload) {
    const file = t.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try { FLOW = await api(`/api/flow/${FLOW.id}/items/${t.dataset.upload}/file`, { method: "POST", body: fd }); renderFlow(); }
    catch (err) { toast(err.message); }
  }
});
$("#flow-items").addEventListener("submit", (e) => {
  const f = e.target.closest("[data-spec]");
  if (!f) return;
  e.preventDefault();
  const ov = {};
  new FormData(f).forEach((v, k) => { if (v !== "") ov[k] = k === "filament" ? v : Number(v); });
  patchFlow({ overrides: { [f.dataset.spec]: ov } });
});
$("#flow-others").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-add-item]");
  if (!b) return;
  b.disabled = true; b.textContent = "Analizuję...";
  try { FLOW = await api(`/api/flow/${FLOW.id}/items/${b.dataset.addItem}`, { method: "POST" }); renderFlow(); } catch (err) { toast(err.message); }
});

flowInit();
