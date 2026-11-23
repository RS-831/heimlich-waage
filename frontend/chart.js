/* Schlankes SVG-Zeitreihendiagramm ohne Abhängigkeiten.
 *
 * Chart.render(container, {
 *   points: [{date: "2026-11-01", value: 82.1, trend: 82.4, extra: {...}}],
 *   from: Date|null, forecast: [{date, value}, {date, value}] | null,
 *   goal: number|null, unit: "kg", showTrend: true, tooltip: fn(point) -> html
 * })
 */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const nf = (d) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }
  const toTime = (iso) => Date.parse(iso + "T00:00:00Z");

  function niceStep(span, target) {
    const raw = span / target;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 5, 10]) if (m * mag >= raw) return m * mag;
    return 10 * mag;
  }

  function dateTicks(t0, t1, maxTicks) {
    const spanDays = (t1 - t0) / DAY;
    const fmtDay = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "numeric", timeZone: "UTC" });
    const fmtMon = new Intl.DateTimeFormat("de-DE", { month: "short", timeZone: "UTC" });
    const fmtMonY = new Intl.DateTimeFormat("de-DE", { month: "short", year: "2-digit", timeZone: "UTC" });
    const ticks = [];
    if (spanDays <= 70) {
      const step = [1, 2, 3, 7, 14].find((s) => spanDays / s <= maxTicks) || 14;
      let t = t0 - (t0 % DAY);
      if (step === 7 || step === 14) {               // auf Montage ausrichten
        const wd = (new Date(t).getUTCDay() + 6) % 7;
        t += ((7 - wd) % 7) * DAY;
      }
      for (; t <= t1; t += step * DAY) if (t >= t0) ticks.push([t, fmtDay.format(t)]);
    } else {
      const months = [1, 2, 3, 6, 12].find((m) => spanDays / 30.4 / m <= maxTicks) || 12;
      const d = new Date(t0);
      let y = d.getUTCFullYear(), m = d.getUTCMonth() + 1;
      const multiYear = spanDays > 330;
      for (;;) {
        if (m > 11) { y += Math.floor(m / 12); m %= 12; }
        const t = Date.UTC(y, m, 1);
        if (t > t1) break;
        if (m % months === 0) ticks.push([t, (multiYear && m === 0 ? fmtMonY : fmtMon).format(t)]);
        m += 1;
      }
    }
    return ticks;
  }

  function render(container, opts) {
    container.innerHTML = "";
    const all = opts.points || [];
    const from = opts.from ? opts.from.getTime() : null;
    const pts = from ? all.filter((p) => toTime(p.date) >= from) : all.slice();
    if (!pts.length) {
      const msg = document.createElement("div");
      msg.className = "empty";
      msg.textContent = all.length ? "Keine Einträge in diesem Zeitraum." : "Noch keine Einträge – trag oben dein erstes Gewicht ein.";
      container.appendChild(msg);
      return;
    }
    const unit = opts.unit || "";
    const decimals = opts.decimals ?? 1;
    const width = Math.max(280, container.clientWidth || 600);
    const height = opts.height || (width < 500 ? 230 : 280);
    const m = { top: 12, right: 12, bottom: 24, left: 40 };
    const iw = width - m.left - m.right, ih = height - m.top - m.bottom;

    // x-Bereich: gewählter Zeitraum bis heute, aber nie vor dem ersten Messwert überhaupt.
    // Rechts etwas Platz für die Prognose; mindestens eine Woche breit.
    const lastT = Math.max(toTime(all[all.length - 1].date), opts.to ? opts.to.getTime() : 0);
    const firstT = toTime(all[0].date) - DAY;
    let t0 = from != null ? Math.max(from, firstT) : firstT;
    if (lastT - t0 < 6 * DAY) t0 = lastT - 6 * DAY;
    const span = lastT - t0;
    const t1 = lastT + (opts.forecast ? Math.max(3 * DAY, span * 0.2) : DAY);

    // y-Bereich: sichtbare Werte, Trend, Ziel, sichtbare Prognose
    const ys = [];
    for (const p of pts) { ys.push(p.value); if (opts.showTrend !== false && p.trend != null) ys.push(p.trend); }
    let fc = null;
    if (opts.forecast && opts.forecast.length === 2) {
      const [a, b] = opts.forecast;
      const ta = toTime(a.date), tb = toTime(b.date);
      const tEnd = Math.min(tb, t1);
      const vEnd = a.value + (b.value - a.value) * (tEnd - ta) / Math.max(1, tb - ta);
      fc = [[ta, a.value], [tEnd, vEnd]];
      ys.push(vEnd);
    }
    // Ziel nur in die Skala nehmen, wenn es nah an den Werten liegt – sonst würden die
    // Messwerte zu einer flachen Linie zusammengedrückt. Weit entfernt: Hinweis am Rand.
    let goalOff = 0; // -1 = Ziel liegt darunter, +1 = darüber
    if (opts.goal != null) {
      const lo = Math.min(...ys), hi = Math.max(...ys);
      const reach = Math.max(3, (hi - lo) * 1.5);
      if (opts.goal >= lo - reach && opts.goal <= hi + reach) ys.push(opts.goal);
      else goalOff = opts.goal < lo ? -1 : 1;
    }
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = Math.max(0.5, (y1 - y0) * 0.08);
    y0 -= pad; y1 += pad;
    const step = niceStep(y1 - y0, height < 250 ? 4 : 5);
    y0 = Math.floor(y0 / step) * step; y1 = Math.ceil(y1 / step) * step;

    const x = (t) => m.left + (t - t0) / (t1 - t0) * iw;
    const y = (v) => m.top + (1 - (v - y0) / (y1 - y0)) * ih;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img",
      "aria-label": opts.label || "Verlaufsdiagramm" }, container);
    const clipId = "clip" + Math.random().toString(36).slice(2, 8);
    el("rect", { x: m.left, y: m.top - 6, width: iw, height: ih + 12 },
      el("clipPath", { id: clipId }, el("defs", {}, svg)));

    // Gitter und Achsen
    const stepDec = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
    for (let v = y0; v <= y1 + step / 2; v += step) {
      el("line", { class: "grid", x1: m.left, x2: m.left + iw, y1: y(v), y2: y(v) }, svg);
      const t = el("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end" }, svg);
      t.textContent = nf(stepDec).format(v);
    }
    el("line", { class: "baseline", x1: m.left, x2: m.left + iw, y1: m.top + ih, y2: m.top + ih }, svg);
    const ticks = dateTicks(t0, t1, Math.max(3, Math.floor(iw / 70)));
    for (const [t, label] of ticks) {
      const tx = el("text", { x: x(t), y: height - 6, "text-anchor": "middle" }, svg);
      tx.textContent = label;
    }

    const plot = el("g", { "clip-path": `url(#${clipId})` }, svg);

    // Ziel
    if (goalOff) {
      const below = goalOff < 0;
      const lbl = el("text", { class: "goal-label", x: m.left + iw - 4, "text-anchor": "end",
        y: below ? m.top + ih - 6 : m.top + 12 }, svg);
      lbl.textContent = `Ziel ${nf(1).format(opts.goal)} ${unit} ${below ? "↓" : "↑"}`;
    } else if (opts.goal != null) {
      el("line", { class: "goal", x1: m.left, x2: m.left + iw, y1: y(opts.goal), y2: y(opts.goal) }, plot);
      const lbl = el("text", { class: "goal-label", x: m.left + 4, y: y(opts.goal) - 5 }, svg);
      lbl.textContent = "Ziel " + nf(1).format(opts.goal) + " " + unit;
    }
    // Messwerte (Punkte), bei sehr vielen Punkten kleiner
    const r = pts.length > 200 ? 2.5 : pts.length > 90 ? 3 : 4;
    const rawG = el("g", {}, plot);
    for (const p of pts) el("circle", { class: "raw", cx: x(toTime(p.date)), cy: y(p.value), r }, rawG);
    // Trend: auch der Punkt direkt vor dem Zeitraum, damit die Linie am Rand beginnt
    if (opts.showTrend !== false) {
      const firstIdx = all.indexOf(pts[0]);
      const tr = (firstIdx > 0 ? [all[firstIdx - 1]] : []).concat(pts).filter((p) => p.trend != null);
      if (tr.length > 1) {
        const line = "M" + tr.map((p) => x(toTime(p.date)).toFixed(1) + "," + y(p.trend).toFixed(1)).join("L");
        // Fläche unter dem Trend (Verlauf in Akzentfarbe), hinter den Punkten
        const gid = "fill" + clipId;
        const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, svg.querySelector("defs"));
        el("stop", { offset: 0, style: "stop-color: var(--trend); stop-opacity: 0.22" }, grad);
        el("stop", { offset: 1, style: "stop-color: var(--trend); stop-opacity: 0" }, grad);
        const bottom = (m.top + ih).toFixed(1);
        const area = el("path", { class: "area", fill: `url(#${gid})`,
          d: `${line}L${x(toTime(tr[tr.length - 1].date)).toFixed(1)},${bottom}L${x(toTime(tr[0].date)).toFixed(1)},${bottom}Z` }, plot);
        plot.insertBefore(area, rawG);
        el("path", { class: "trend", d: line }, plot);
      }
    }
    if (fc) {
      el("path", { class: "forecast", d: `M${x(fc[0][0])},${y(fc[0][1])}L${x(fc[1][0])},${y(fc[1][1])}` }, plot);
    }

    // Hover-Ebene: Fadenkreuz + Tooltip am nächsten Eintrag
    const cross = el("line", { class: "cross", y1: m.top, y2: m.top + ih, visibility: "hidden" }, svg);
    const dot = el("circle", { class: "hover-dot", r: 5, visibility: "hidden" }, svg);
    const tip = document.createElement("div");
    tip.className = "tooltip"; tip.hidden = true;
    container.appendChild(tip);
    const xs = pts.map((p) => x(toTime(p.date)));
    const overlay = el("rect", { x: m.left, y: m.top, width: iw, height: ih, fill: "transparent" }, svg);

    let current = -1;
    function show(evt) {
      const rect = svg.getBoundingClientRect();
      const px = (evt.clientX - rect.left) * (width / rect.width);
      let best = 0;
      for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - px) < Math.abs(xs[best] - px)) best = i;
      current = best;
      const p = pts[best];
      const cy = y(opts.showTrend !== false && p.trend != null ? p.trend : p.value);
      cross.setAttribute("x1", xs[best]); cross.setAttribute("x2", xs[best]);
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", xs[best]); dot.setAttribute("cy", cy);
      dot.setAttribute("visibility", "visible");
      tip.innerHTML = opts.tooltip ? opts.tooltip(p) : nf(decimals).format(p.value);
      tip.hidden = false;
      const scale = rect.width / width;
      const left = xs[best] * scale, cw = container.clientWidth, tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(0, left + 12 + tw > cw ? left - tw - 12 : left + 12), cw - tw) + "px";
      tip.style.top = Math.max(0, cy * scale - tip.offsetHeight - 10) + "px";
    }
    function hide() {
      current = -1;
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }
    overlay.addEventListener("pointermove", show);
    overlay.addEventListener("pointerdown", show);
    overlay.addEventListener("pointerleave", hide);
    if (opts.onSelect) overlay.addEventListener("click", (evt) => {
      show(evt);
      if (current >= 0) opts.onSelect(pts[current]);
    });
  }

  window.Chart = { render };
})();
