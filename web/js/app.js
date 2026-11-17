/* Plotline front-end: upload -> story. Vanilla JS, no framework (Vercel-static). */

const $ = (s) => document.querySelector(s);

const drop = $("#drop");
const fileInput = $("#file");
const statusEl = $("#drop-status");
const landing = $("#landing");
const storyEl = $("#story");

let busy = false;

async function handleFile(file) {
  if (busy) return;
  busy = true;
  statusEl.classList.remove("err");
  statusEl.textContent = `Reading ${file.name} (${Math.round(file.size / 1024)} KB)…`;
  try {
    const buf = await file.arrayBuffer();
    const res = await fetch("/api/story", {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: new Uint8Array(buf),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `Server said ${res.status}`);
    }
    if (data.too_small) {
      renderTooSmall(data);
    } else {
      renderStory(data);
    }
  } catch (e) {
    statusEl.classList.add("err");
    statusEl.textContent = e.message || "Something went wrong reading that file.";
  } finally {
    busy = false;
  }
}

function renderTooSmall(data) {
  landing.hidden = true;
  storyEl.hidden = false;
  storyEl.innerHTML = `
    <section class="wrap frame shown" style="min-height:60vh">
      <p class="frame-label">Not enough data</p>
      <h2 class="headline">${data.n_rows} ${data.n_rows === 1 ? "row" : "rows"} isn't enough to support claims.</h2>
      <p class="sub">${data.message}</p>
      <p class="sub" style="font-family:var(--mono);font-size:13px">This refusal is the point of the tool. Bring 20+ rows and it will have something to say.</p>
      <div class="retools"><button class="btn" onclick="location.reload()">Try another file</button></div>
    </section>`;
}

function renderStory(data) {
  landing.hidden = true;
  storyEl.hidden = false;
  document.title = `${data.title} — Plotline`;

  const framesHtml = data.frames.map((f, i) => frameHtml(f, i, data)).join("");
  storyEl.innerHTML = `
    <div class="ledger-strip on wrap" id="ledger-strip"></div>
    ${framesHtml}
    <div class="wrap retools"><button class="btn" onclick="location.reload()">Read another dataset</button></div>`;

  // reveal frames as they enter the viewport
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (en.isIntersecting) en.target.classList.add("shown");
    });
  }, { threshold: 0.25 });
  document.querySelectorAll(".frame").forEach((el) => io.observe(el));

  // receipts
  storyEl.addEventListener("click", (e) => {
    const c = e.target.closest(".claim[data-stat]");
    if (!c) return;
    toggleReceipt(c, data);
  });

  updateStrip(data);
}

function updateStrip(data) {
  const strip = $("#ledger-strip");
  if (!strip) return;
  const v = data.verification;
  strip.innerHTML = `LEDGER — ${v.claims_with_stats}/${v.claims_total} sentences carry a verified stat · ${v.unverified_dropped} unverified claims dropped at build time`;
}

function frameHtml(f, i, data) {
  const label = `Frame ${String(i + 1).padStart(2, "0")} · ${f.kind}`;
  let inner = "";

  if (f.kind === "hero") {
    inner = `
      <p class="kicker">${f.big.label}</p>
      <h1 class="headline">${f.big.value}</h1>
      ${claimsHtml(f, data)}`;
  } else if (f.kind === "table") {
    inner = `<h2 class="headline" style="font-size:34px">${f.title}</h2>${claimsHtml(f, data)}`;
  } else if (f.kind === "caveats") {
    const items = f.claims.map((c) => `<li>${c.text}</li>`).join("");
    inner = `<h2>${f.title}</h2><ul class="claims" style="margin-top:10px">${items}</ul>`;
  } else {
    inner = `<h2 class="headline" style="font-size:34px">${f.title}</h2>${claimsHtml(f, data)}`;
  }

  const chart = f.chart_data ? chartHtml(f) : "";
  return `<section class="frame ${f.id === "limits" ? "limits" : ""}" id="frame-${f.id}">
    <div class="wrap">
      <p class="frame-label">${label}</p>
      ${inner}
      ${chart}
    </div>
  </section>`;
}

function claimsHtml(f, data) {
  if (!f.claims || !f.claims.length) return "";
  return `<ul class="claims">${f.claims.map((c) => claimHtml(c)).join("")}</ul>`;
}

function claimHtml(c) {
  if (!c.stat) {
    return `<li><span class="claim caveat">${c.text}</span></li>`;
  }
  const chip = `<span class="stat-chip">${c.stat}</span>`;
  return `<li><button class="claim ${c.role === "lead" ? "" : ""}" data-stat="${c.stat}">${c.text}${chip}</button></li>`;
}

/* ---------- receipts ---------- */

function toggleReceipt(btn, data) {
  const existing = btn.parentElement.querySelector(".receipt-slot");
  if (existing) {
    existing.remove();
    return;
  }
  document.querySelectorAll(".receipt-slot").forEach((r) => r.remove());

  const s = data.stats[btn.dataset.stat];
  if (!s) return;
  const slot = document.createElement("div");
  slot.className = "receipt-slot";
  slot.innerHTML = receiptHtml(s);
  btn.closest("li").after(slot);
  requestAnimationFrame(() => {
    slot.style.height = slot.firstElementChild.scrollHeight + "px";
    slot.style.overflow = "hidden";
  });
}

function receiptHtml(s) {
  return `<div class="receipt">
    <div class="r-head">Claim receipt</div>
    <div class="r-row"><span class="r-label">stat id</span><span class="r-val">${s.id}</span></div>
    <div class="r-row"><span class="r-label">value</span><span class="r-val">${s.fmt}</span></div>
    <div class="r-row"><span class="r-label">computed</span><span class="r-val">pandas-lite engine</span></div>
    <div class="r-detail">${s.detail || "—"}</div>
    <div class="r-stamp">✓ VERIFIED — NOT LLM-GENERATED</div>
  </div>`;
}

/* ---------- charts: hand-rolled SVG ---------- */

function chartHtml(f) {
  if (f.kind === "bars") return barsSvg(f.chart_data);
  if (f.kind === "line") return lineSvg(f.chart_data);
  if (f.kind === "histogram") return histSvg(f.chart_data);
  return "";
}

const esc = (s) => String(s)
  .replace(/&/g, "&" + "amp;")
  .replace(/</g, "&" + "lt;")
  .replace(/>/g, "&" + "gt;")
  .replace(/"/g, "&" + "quot;");

function barsSvg(d) {
  const W = 720, H = 260, padB = 46, padL = 8, padT = 16;
  const max = Math.max(...d.y);
  const bw = (W - padL * 2) / d.x.length;
  const bars = d.x.map((x, i) => {
    const h = (d.y[i] / max) * (H - padB - padT);
    const bx = padL + i * bw + bw * 0.18;
    const bwid = bw * 0.64;
    return `<rect class="bar-anim" style="transition-delay:${i * 60}ms" x="${bx.toFixed(1)}" y="${(H - padB - h).toFixed(1)}" width="${bwid.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="#2746E0"></rect>
      <text class="axis" x="${(bx + bwid / 2).toFixed(1)}" y="${H - padB + 16}" text-anchor="middle" transform="rotate(18 ${(bx + bwid / 2).toFixed(1)} ${H - padB + 16})">${esc(x).slice(0, 18)}</text>
      <text class="axis" x="${(bx + bwid / 2).toFixed(1)}" y="${(H - padB - h - 6).toFixed(1)}" text-anchor="middle">${d.y[i]}</text>`;
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Group means">${bars}
    <line x1="${padL}" y1="${H - padB}" x2="${W - padL}" y2="${H - padB}" stroke="#E3DDCF"></line></svg></div>`;
}

function lineSvg(d) {
  const W = 720, H = 260, padB = 30, padL = 10, padT = 18;
  const xs = d.x.map((v) => new Date(v).getTime());
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...d.y), y1 = Math.max(...d.y);
  const px = (t) => padL + ((t - x0) / Math.max(1, x1 - x0)) * (W - padL * 2);
  const py = (v) => padT + (1 - (v - y0) / Math.max(1e-9, y1 - y0)) * (H - padB - padT);
  const path = d.y.map((v, i) => `${i ? "L" : "M"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  const len = d.y.length * 12;
  const area = path + ` L${px(xs[xs.length - 1]).toFixed(1)},${H - padB} L${px(xs[0]).toFixed(1)},${H - padB} Z`;
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Trend over time">
    <path d="${area}" fill="rgba(39,70,224,.07)"></path>
    <path class="line-draw" style="--len:${len}" d="${path}" fill="none" stroke="#2746E0" stroke-width="2.2" stroke-linecap="round"></path>
    <text class="axis" x="${padL}" y="${H - 6}">${esc(d.x[0])}</text>
    <text class="axis" x="${W - padL}" y="${H - 6}" text-anchor="end">${esc(d.x[d.x.length - 1])}</text>
    <line x1="${padL}" y1="${H - padB}" x2="${W - padL}" y2="${H - padB}" stroke="#E3DDCF"></line>
  </svg></div>`;
}

function histSvg(d) {
  const W = 720, H = 240, padB = 28, padL = 8, padT = 14;
  const max = Math.max(...d.counts);
  const bw = (W - padL * 2) / d.counts.length;
  const bars = d.counts.map((c, i) => {
    const h = (c / max) * (H - padB - padT);
    return `<rect class="hist-anim" style="transition-delay:${i * 28}ms" x="${(padL + i * bw + 1).toFixed(1)}" y="${(H - padB - h).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="#1C2230" opacity="0.82"></rect>`;
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribution">${bars}
    <text class="axis" x="${padL}" y="${H - 8}">${esc(d.edges[0])}</text>
    <text class="axis" x="${W - padL}" y="${H - 8}" text-anchor="end">${esc(d.edges[d.edges.length - 1])}</text>
  </svg></div>`;
}

/* ---------- wiring ---------- */

drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => fileInput.files[0] && handleFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", async () => {
    statusEl.textContent = `Fetching sample (${chip.dataset.sample})…`;
    try {
      const res = await fetch(`/samples/${chip.dataset.sample}.csv`);
      const buf = await res.arrayBuffer();
      handleFile(new File([buf], `${chip.dataset.sample}.csv`, { type: "text/csv" }));
    } catch {
      statusEl.classList.add("err");
      statusEl.textContent = "Could not load that sample.";
    }
  });
});
