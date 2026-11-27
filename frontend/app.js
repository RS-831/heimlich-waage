/* heimlich · Waage – Oberfläche. Reines JavaScript, spricht nur mit der eigenen API. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const fmt = (d) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
  const f1 = fmt(1), f2 = fmt(2);
  const dateFmt = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
  const dateLong = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const fmtDate = (iso) => dateFmt.format(new Date(iso + "T00:00:00Z"));
  const rowFmt = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", timeZone: "UTC" });
  const rowFmtY = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "UTC" });
  const fmtRowDate = (iso) => (iso.slice(0, 4) === localToday().slice(0, 4) ? rowFmt : rowFmtY)
    .format(new Date(iso + "T00:00:00Z")).replace(".,", "");
  const fmtDateLong = (iso) => dateLong.format(new Date(iso + "T00:00:00Z"));

  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* egal */ } },
  };

  const state = {
    summary: null,
    entries: new Map(),       // ISO-Datum -> Eintrag
    rangeDays: Number(store.get("range", "91")),
    method: store.get("method", "ewma"),
    listLimit: 30,
  };

  function localToday() {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }
  function parseNum(text) {
    const t = String(text || "").trim().replace(/\s/g, "").replace(",", ".");
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : NaN;
  }
  function signed(v, f = f1, unit = " kg") {
    if (v == null) return "–";
    const s = f.format(Math.abs(v));
    return (v > 0 ? "+" : v < 0 ? "−" : "±") + s + unit;
  }
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function msg(id, text, kind) {
    const node = $(id);
    node.textContent = text || "";
    node.className = "msg" + (kind ? " " + kind : "");
  }

  // Läuft die Anmeldung am Proxy (z. B. Authelia) ab, leitet er API-Aufrufe zur Login-Seite um.
  // Der Umleitung nicht folgen (gäbe einen CORS-Fehler), sondern die Seite neu laden:
  // Der Browser landet dann bei der Anmeldung und danach wieder hier.
  let reloading = false;
  function sessionExpired() {
    if (reloading) return;
    let last = 0;
    try { last = Number(sessionStorage.getItem("auth-reload") || 0); } catch { /* egal */ }
    if (Date.now() - last < 30000) {  // gerade erst neu geladen: keine Endlosschleife
      showBanner("Nicht angemeldet. Bitte die Seite neu laden oder neu anmelden.");
      return;
    }
    reloading = true;
    try { sessionStorage.setItem("auth-reload", String(Date.now())); } catch { /* egal */ }
    showBanner("Anmeldung abgelaufen, wird neu geladen …");
    setTimeout(() => location.reload(), 800);
  }
  function showBanner(text) {
    let b = document.getElementById("banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "banner"; b.className = "banner"; b.setAttribute("role", "alert");
      document.body.prepend(b);
    }
    b.textContent = text;
  }

  async function api(path, options = {}) {
    const res = await fetch("api/" + path, { redirect: "manual", ...options });
    if (res.type === "opaqueredirect" || res.status === 401) {
      sessionExpired();
      throw new Error("Anmeldung abgelaufen");
    }
    if (res.status === 403) {
      showBanner("Kein Zugriff auf die Waage.");
      throw new Error("Kein Zugriff");
    }
    if (res.status === 204) return null;
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      let detail = body && body.detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ");
      else if (detail && typeof detail === "object") detail = detail.message + (detail.errors && detail.errors.length ? ` (Zeile ${detail.errors[0].line}: ${detail.errors[0].message})` : "");
      throw new Error(detail || `Fehler ${res.status}`);
    }
    return body;
  }
  const json = (method, data) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  // --- Laden ------------------------------------------------------------------
  async function refresh() {
    try {
      const s = await api(`summary?method=${state.method}&today=${localToday()}`);
      state.summary = s;
      state.entries = new Map(s.series.map((p) => [p.date, p]));
      renderTiles(); renderChart(); renderList();
      if (!$("entry-msg").textContent) hintExisting();
    } catch (e) {
      msg("entry-msg", "Server nicht erreichbar: " + e.message, "error");
    }
  }

  // --- Dialoge ----------------------------------------------------------------
  function ask(text, okLabel = "OK", danger = false) {
    const dlg = $("confirm-dialog");
    $("confirm-text").textContent = text;
    $("confirm-ok").textContent = okLabel;
    $("confirm-ok").className = danger ? "primary danger-fill" : "primary";
    dlg.showModal();
    return new Promise((resolve) => {
      const done = (v) => { dlg.close(); $("confirm-ok").onclick = $("confirm-cancel").onclick = dlg.oncancel = null; resolve(v); };
      $("confirm-ok").onclick = () => done(true);
      $("confirm-cancel").onclick = () => done(false);
      dlg.oncancel = () => done(false);
    });
  }

  // --- Erfassung (Übersicht) ----------------------------------------------------
  function hintExisting() {
    const e = state.entries.get($("f-date").value);
    if (e) msg("entry-msg", `Für diesen Tag gibt es schon einen Eintrag (${f1.format(e.weight)} kg). Speichern ersetzt ihn.`);
    else if ($("entry-msg").className === "msg") msg("entry-msg", "");
  }
  $("f-date").addEventListener("change", hintExisting);

  $("entry-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const day = $("f-date").value;
    const weight = parseNum($("f-weight").value);
    const waist = parseNum($("f-waist").value);
    if (!day) return msg("entry-msg", "Bitte ein Datum wählen.", "error");
    if (weight == null || Number.isNaN(weight)) { $("f-weight").focus(); return msg("entry-msg", "Bitte ein Gewicht eingeben, z. B. 82,4.", "error"); }
    if (Number.isNaN(waist)) return msg("entry-msg", "Bauchumfang ist keine Zahl.", "error");
    const existing = state.entries.get(day);
    if (existing && !(await ask(`Am ${fmtDateLong(day)} ist schon ${f1.format(existing.weight)} kg eingetragen. Durch ${f1.format(weight)} kg ersetzen?`, "Ersetzen"))) return;
    $("btn-save").disabled = true;
    try {
      await api("entries/" + day, json("PUT", { weight_kg: weight, waist_cm: waist, note: $("f-note").value }));
      msg("entry-msg", `Gespeichert: ${f1.format(weight)} kg am ${fmtDateLong(day)}.`, "ok");
      $("f-weight").value = ""; $("f-waist").value = ""; $("f-note").value = "";
      $("f-date").value = localToday();
      await refresh();
    } catch (e) {
      msg("entry-msg", e.message, "error");
    } finally {
      $("btn-save").disabled = false;
    }
  });

  // --- Bearbeiten / Löschen (Einträge) -------------------------------------------
  let editing = null;
  function openEdit(day) {
    const e = state.entries.get(day);
    if (!e) return;
    editing = day;
    $("edit-title").textContent = "Eintrag vom " + fmtDate(day);
    $("e-weight").value = f1.format(e.weight);
    $("e-waist").value = e.waist != null ? f1.format(e.waist) : "";
    $("e-note").value = e.note || "";
    msg("edit-msg", "");
    $("edit-dialog").showModal();
    $("e-weight").select();
  }
  $("edit-cancel").addEventListener("click", () => $("edit-dialog").close());
  $("edit-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const weight = parseNum($("e-weight").value);
    const waist = parseNum($("e-waist").value);
    if (weight == null || Number.isNaN(weight)) return msg("edit-msg", "Bitte ein Gewicht eingeben, z. B. 82,4.", "error");
    if (Number.isNaN(waist)) return msg("edit-msg", "Bauchumfang ist keine Zahl.", "error");
    try {
      await api("entries/" + editing, json("PUT", { weight_kg: weight, waist_cm: waist, note: $("e-note").value }));
      $("edit-dialog").close();
      await refresh();
      flashRow(editing);
    } catch (e) { msg("edit-msg", e.message, "error"); }
  });

  async function deleteEntry(day) {
    const e = state.entries.get(day);
    if (!e || !(await ask(`Eintrag vom ${fmtDateLong(day)} (${f1.format(e.weight)} kg) löschen? Das lässt sich nicht rückgängig machen.`, "Löschen", true))) return;
    try {
      await api("entries/" + day, { method: "DELETE" });
      await refresh();
    } catch (err) { alert(err.message); }
  }
  function flashRow(day) {
    const tr = $("list").querySelector(`tr[data-date="${day}"]`);
    if (tr) { tr.classList.add("flash"); setTimeout(() => tr.classList.remove("flash"), 1200); }
  }

  // --- Kennzahlen -------------------------------------------------------------
  function tile(label, value, sub, extra = "") {
    return `<div class="tile ${extra}"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }
  const ICONS = {
    week: '<path d="M3 7h18M3 12h12M3 17h7"/><path d="M17 14l3 3-3 3"/>',
    month: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    speed: '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>',
    start: '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    body: '<circle cx="12" cy="5" r="2.5"/><path d="M7 21l2-9-3-3h12l-3 3 2 9"/>',
    streak: '<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z"/>',
    range: '<path d="M7 4v16M17 4v16M3 8l4-4 4 4M13 16l4 4 4-4"/>',
    waist: '<path d="M3 12h18"/><path d="M6 9v6M10 10v4M14 10v4M18 9v6"/>',
    flag: '<path d="M5 21V4h11l-2 4 2 4H5"/>',
  };
  const icon = (name, cls = "") => `<span class="ico ${cls}" aria-hidden="true"><svg viewBox="0 0 24 24">${ICONS[name]}</svg></span>`;
  function tile(ic, label, value, sub) {
    return `<div class="tile">${icon(ic)}<div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }

  function renderTiles() {
    const s = state.summary, st = s && s.stats;
    // Hero
    if (!st) {
      $("hero-trend").textContent = "–";
      $("hero-sub").textContent = "Trag unten dein erstes Gewicht ein.";
      $("hero-badge").hidden = true;
      $("goal-card").hidden = true;
      $("tiles").innerHTML = "";
      return;
    }
    const lastInfo = st.days_since_last === 0 ? "heute" : st.days_since_last === 1 ? "gestern" : `vor ${st.days_since_last} Tagen`;
    $("hero-trend").textContent = f1.format(st.trend_weight);
    $("hero-sub").textContent = `Letzte Messung ${f1.format(st.current_weight)} kg (${lastInfo})`;
    const ch = st.change_30d != null ? [st.change_30d, "30 Tagen"] : st.change_7d != null ? [st.change_7d, "7 Tagen"] : null;
    $("hero-badge").hidden = !ch;
    if (ch) $("hero-badge").textContent = `${signed(ch[0])} in ${ch[1]}`;

    // Ziel
    const g = s.goal;
    $("goal-card").hidden = !g;
    if (g) {
      let head;
      if (g.reached) head = "Ziel erreicht – gratuliere!";
      else if (g.projected_date) head = `Voraussichtlich ${fmtDateLong(g.projected_date)}`;
      else head = s.forecast ? "Trend zeigt gerade nicht Richtung Ziel" : "Prognose ab ca. 2 Wochen Daten";
      const details = [];
      if (g.target_date && !g.reached) {
        details.push(`Zieldatum ${fmtDateLong(g.target_date)}` + (g.on_track === true ? " – im Plan" : g.on_track === false ? " – nicht im Plan" : ""));
        if (g.required_rate_kg_per_week != null) details.push(`nötig ${signed(g.required_rate_kg_per_week, f2)}/Woche`);
      }
      const rest = g.reached ? "" : ` · noch ${f1.format(Math.abs(g.remaining_kg))} kg`;
      $("goal-card").innerHTML = `<div class="goal-head">${icon("flag", "hi")}
          <div class="text"><small>Ziel ${f1.format(g.target_weight_kg)} kg${rest}</small><b>${head}</b></div>
          <span class="goal-pct">${f1.format(g.progress_pct).replace(",0", "")} %</span></div>
        <div class="progress" role="progressbar" aria-label="Fortschritt zum Ziel" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${g.progress_pct}"><div style="width:${g.progress_pct}%"></div></div>
        ${details.length ? `<div class="details">${details.join(" · ")}</div>` : ""}`;
    }

    const parts = [];
    parts.push(tile("week", "7 Tage", signed(st.change_7d), "Trendveränderung"));
    parts.push(tile("month", "30 Tage", signed(st.change_30d), "Trendveränderung"));
    parts.push(tile("speed", "Tempo", st.rate_kg_per_week == null ? "–" : signed(st.rate_kg_per_week, f2, "") + " <small>kg/Wo</small>",
      st.rate_kg_per_week == null ? "ab ca. 2 Wochen Daten" : "letzte 4 Wochen"));
    parts.push(tile("start", "Seit Start", signed(st.change_total), `seit ${fmtDateLong(st.start_date)}`));
    if (st.bmi != null) parts.push(tile("body", "BMI", f1.format(st.bmi), st.bmi_category));
    parts.push(tile("streak", "Serie", `${st.streak} <small>${st.streak === 1 ? "Tag" : "Tage"}</small>`, `${st.count} ${st.count === 1 ? "Eintrag" : "Einträge"}`));
    parts.push(tile("range", "Min / Max", `${f1.format(st.min_weight)} / ${f1.format(st.max_weight)}`, "kg, Messwerte"));
    if (st.waist_current != null) parts.push(tile("waist", "Bauchumfang", `${f1.format(st.waist_current)} <small>cm</small>`,
      st.waist_change_total != null ? signed(st.waist_change_total, f1, " cm") + " seit erster Messung" : ""));
    $("tiles").innerHTML = parts.join("");
  }

  // --- Darstellung (hell/dunkel) ------------------------------------------------
  const darkMq = matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    const choice = store.get("theme", "auto");
    const theme = choice === "auto" ? (darkMq.matches ? "dark" : "light") : choice;
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = getComputedStyle(document.documentElement).getPropertyValue("--page").trim();
    for (const b of document.querySelectorAll("[data-theme-choice]")) b.setAttribute("aria-pressed", String(b.dataset.themeChoice === choice));
    $("menu-theme").textContent = { auto: "Automatisch (wie das Gerät)", light: "Hell", dark: "Dunkel" }[choice];
    if (state.summary) renderChart();
  }
  darkMq.addEventListener("change", applyTheme);
  $("theme-seg").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-theme-choice]"); if (!b) return;
    store.set("theme", b.dataset.themeChoice); applyTheme();
  });

  // --- Diagramme --------------------------------------------------------------
  // Zeiträume zählen ab heute rückwärts (nicht ab dem letzten Eintrag)
  const todayUtc = () => new Date(Date.parse(localToday() + "T00:00:00Z"));
  const RANGES = [30, 91, 182, 365];
  // Wie viele Tage reichen die Daten zurück (inkl. heute)?
  function dataSpanDays() {
    const s = state.summary;
    if (!s || !s.series.length) return 0;
    return Math.round((todayUtc() - Date.parse(s.series[0].date + "T00:00:00Z")) / 86400000) + 1;
  }
  // Zeiträume, die nichts Neues zeigen würden: länger als der kürzeste, der schon alles enthält
  function rangeAvailable(days) {
    if (!days) return true;
    const span = dataSpanDays();
    const covering = RANGES.find((r) => r >= span);
    return covering == null || days <= covering;
  }
  // Gewählter Zeitraum, notfalls auf den kürzesten passenden zurückgeführt (Wahl bleibt gespeichert)
  function effectiveRange() {
    if (rangeAvailable(state.rangeDays)) return state.rangeDays;
    return RANGES.find((r) => rangeAvailable(r) && r >= dataSpanDays()) || 0;
  }
  function rangeFrom() {
    const s = state.summary, days = effectiveRange();
    if (!days || !s || !s.series.length) return null;
    return new Date(todayUtc().getTime() - (days - 1) * 86400000);
  }
  function renderChart() {
    const s = state.summary;
    const series = s ? s.series : [];
    const eff = effectiveRange();
    for (const b of $("range").querySelectorAll("button")) {
      const d = Number(b.dataset.days), ok = rangeAvailable(d);
      b.disabled = !ok;
      b.title = ok ? "" : "Deine Einträge reichen noch nicht so weit zurück";
      b.setAttribute("aria-pressed", String(d === eff));
    }
    for (const b of $("method").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.method === state.method));
    const forecast = s && s.forecast ? s.forecast.line.map((p) => ({ date: p.date, value: p.weight })) : null;
    const goal = s && s.goal ? s.goal.target_weight_kg : null;
    $("lg-forecast").hidden = !forecast;
    $("lg-goal").hidden = goal == null;
    Chart.render($("chart"), {
      points: series.map((p) => ({ date: p.date, value: p.weight, trend: p.trend, src: p })),
      from: rangeFrom(), to: todayUtc(), forecast, goal, unit: "kg", label: "Gewichtsverlauf mit Trend",
      tooltip: (p) => `<b>${fmtDate(p.date)}</b>
        <div class="row"><span>Gewicht</span><span>${f1.format(p.value)} kg</span></div>
        <div class="row"><span>Trend</span><span>${f1.format(p.trend)} kg</span></div>
        ${p.src.waist != null ? `<div class="row"><span>Bauch</span><span>${f1.format(p.src.waist)} cm</span></div>` : ""}
        ${p.src.note ? `<div class="note">${esc(p.src.note)}</div>` : ""}`,
    });
    const waist = series.filter((p) => p.waist != null);
    $("waist-card").hidden = waist.length < 2;
    if (waist.length >= 2) {
      Chart.render($("waist-chart"), {
        points: waist.map((p) => ({ date: p.date, value: p.waist, trend: null })),
        from: rangeFrom(), to: todayUtc(), showTrend: false, unit: "cm", height: 180, label: "Bauchumfang",
        tooltip: (p) => `<b>${fmtDate(p.date)}</b><div class="row"><span>Bauch</span><span>${f1.format(p.value)} cm</span></div>`,
      });
    }
  }
  $("range").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.rangeDays = Number(b.dataset.days); store.set("range", String(state.rangeDays));
    renderChart();
  });
  $("method").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b || b.dataset.method === state.method) return;
    state.method = b.dataset.method; store.set("method", state.method);
    refresh();
  });
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderChart, 150); });

  // --- Liste ------------------------------------------------------------------
  function renderList() {
    const rows = state.summary ? state.summary.series.slice().reverse() : [];
    $("list-count").textContent = rows.length ? `(${rows.length})` : "";
    const goal = state.summary && state.summary.goal;
    const losing = goal ? goal.target_weight_kg < goal.start_weight_kg : null;
    const pen = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
    const bin = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>';
    $("list").innerHTML = rows.slice(0, state.listLimit).map((p) => {
      const d = p.weight - p.trend;
      const cls = losing == null || Math.abs(d) < 0.05 ? "" : (d < 0) === losing ? "delta-down" : "delta-up";
      const sub = [p.waist != null ? f1.format(p.waist) + " cm" : "", p.note].filter(Boolean).join(" · ");
      return `<tr data-date="${p.date}">
        <td class="day">${fmtRowDate(p.date)}${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</td>
        <td class="num">${f1.format(p.weight)}</td>
        <td class="num ${cls}">${signed(d, f1, "")}</td>
        <td class="act"><button class="ib" data-act="edit" title="Bearbeiten" aria-label="Eintrag vom ${fmtDateLong(p.date)} bearbeiten">${pen}</button><button class="ib del" data-act="delete" title="Löschen" aria-label="Eintrag vom ${fmtDateLong(p.date)} löschen">${bin}</button></td></tr>`;
    }).join("") || `<tr><td colspan="4" class="empty">Noch keine Einträge.</td></tr>`;
    $("btn-more").hidden = rows.length <= state.listLimit;
  }
  $("list").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-act]"); if (!btn) return;
    const day = btn.closest("tr").dataset.date;
    if (btn.dataset.act === "edit") openEdit(day); else deleteEntry(day);
  });
  $("btn-more").addEventListener("click", () => { state.listLimit += 60; renderList(); });

  // --- Navigation (Hash-Routing) ---------------------------------------------
  const ROUTES = {
    "": { view: "dashboard", nav: "dashboard", title: "Übersicht" },
    "eintraege": { view: "entries", nav: "entries", title: "Einträge" },
    "einstellungen": { view: "settings", nav: "settings", title: "Einstellungen" },
    "einstellungen/ziel": { view: "goal", nav: "settings", title: "Ziel" },
    "einstellungen/profil": { view: "profile", nav: "settings", title: "Profil" },
    "einstellungen/daten": { view: "data", nav: "settings", title: "Daten" },
    "einstellungen/darstellung": { view: "appearance", nav: "settings", title: "Darstellung" },
  };
  function route() {
    const key = location.hash.replace(/^#\/?/, "").replace(/\/$/, "");
    const r = ROUTES[key] || ROUTES[""];
    for (const v of document.querySelectorAll("[data-view]")) v.hidden = v.dataset.view !== r.view;
    for (const a of document.querySelectorAll("[data-nav]")) {
      if (a.dataset.nav === r.nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    $("page-title").textContent = r.title;
    document.title = r.title === "Übersicht" ? "heimlich · Waage" : `${r.title} – heimlich · Waage`;
    for (const id of ["goal-msg", "profile-msg", "import-msg"]) msg(id, "");
    if (r.nav === "settings") loadSettings();
    if (r.view === "dashboard") renderChart();  // Breite war im versteckten Zustand 0
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);

  async function loadSettings() {
    try {
      const [profile, goal] = await Promise.all([api("profile"), api("goal")]);
      $("menu-goal").textContent = goal
        ? `${f1.format(goal.target_weight_kg)} kg` + (goal.target_date ? ` bis ${fmtDateLong(goal.target_date)}` : "")
        : "Noch kein Ziel gesetzt";
      $("menu-profile").textContent = profile.height_cm != null
        ? `${profile.name} · ${f1.format(profile.height_cm).replace(",0", "")} cm`
        : `${profile.name} · Größe fehlt (für den BMI)`;
      $("p-name").value = profile.name;
      $("p-height").value = profile.height_cm != null ? f1.format(profile.height_cm).replace(",0", "") : "";
      $("g-weight").value = goal ? f1.format(goal.target_weight_kg) : "";
      $("g-date").value = goal && goal.target_date ? goal.target_date : "";
      $("btn-goal-delete").hidden = !goal;
      $("goal-info").textContent = goal
        ? `Gestartet am ${fmtDateLong(goal.start_date)} bei ${f1.format(goal.start_weight_kg)} kg (Trend). Speichern setzt den Startpunkt neu.`
        : "Startpunkt ist dein aktuelles Trendgewicht. Das Zieldatum ist optional.";
    } catch (e) { msg("goal-msg", e.message, "error"); }
  }

  $("goal-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const w = parseNum($("g-weight").value);
    if (w == null || Number.isNaN(w)) return msg("goal-msg", "Bitte ein Zielgewicht eingeben.", "error");
    try {
      await api("goal", json("PUT", { target_weight_kg: w, target_date: $("g-date").value || null }));
      msg("goal-msg", "Ziel gespeichert.", "ok");
      await Promise.all([refresh(), loadSettings()]);
    } catch (e) { msg("goal-msg", e.message, "error"); }
  });
  $("btn-goal-delete").addEventListener("click", async () => {
    if (!confirm("Ziel entfernen?")) return;
    try {
      await api("goal", { method: "DELETE" });
      msg("goal-msg", "Ziel entfernt.", "ok");
      await Promise.all([refresh(), loadSettings()]);
    } catch (e) { msg("goal-msg", e.message, "error"); }
  });

  $("profile-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const h = parseNum($("p-height").value);
    if (Number.isNaN(h)) return msg("profile-msg", "Größe ist keine Zahl.", "error");
    try {
      await api("profile", json("PUT", { name: $("p-name").value.trim() || "standard", height_cm: h }));
      msg("profile-msg", "Profil gespeichert.", "ok");
      await refresh();
    } catch (e) { msg("profile-msg", e.message, "error"); }
  });

  $("i-file").addEventListener("change", () => { $("btn-import").disabled = !$("i-file").files.length; msg("import-msg", ""); });
  $("btn-import").addEventListener("click", async () => {
    const file = $("i-file").files[0]; if (!file) return;
    const overwrite = $("i-overwrite").checked;
    try {
      const body = await file.arrayBuffer();
      const r = await api(`import?overwrite=${overwrite}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body });
      let text = `${r.created} neu, ${r.updated} aktualisiert, ${r.skipped} übersprungen.`;
      if (r.errors.length) text += ` ${r.errors.length} ${r.errors.length === 1 ? "Zeile" : "Zeilen"} fehlerhaft: ` + r.errors.slice(0, 3).map((e) => `Zeile ${e.line}: ${e.message}`).join("; ");
      msg("import-msg", text, r.errors.length ? "error" : "ok");
      $("i-file").value = ""; $("btn-import").disabled = true;
      await refresh();
    } catch (e) { msg("import-msg", e.message, "error"); }
  });

  // --- Angemeldeter Nutzer (nur im Proxy-Modus sichtbar) ---------------------------
  async function loadMe() {
    try {
      const me = await api("me");
      try { sessionStorage.removeItem("auth-reload"); } catch { /* egal */ }
      if (me.auth_mode !== "proxy") return;
      $("user-name").textContent = me.name;  // textContent: Header-Werte nie als HTML
      $("user-box").hidden = false;
      if (me.logout_url) {
        $("logout-link").href = me.logout_url;
        $("logout-link").hidden = false;
      }
    } catch { /* Meldung kommt aus api() */ }
  }

  // --- Start ------------------------------------------------------------------
  $("f-date").value = localToday();
  $("f-date").max = localToday();
  applyTheme();
  route();
  loadMe();
  refresh().then(() => {
    if (!state.entries.has(localToday()) && !location.hash.replace(/^#\/?/, "")) $("f-weight").focus();
  });
})();
