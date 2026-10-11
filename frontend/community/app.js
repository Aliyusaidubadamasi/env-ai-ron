"use strict";
const $ = (s) => document.querySelector(s);
const API = "/api/v1/community";
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { leafy: "Leafy and healthy", sparse: "Sparse leaves", bare_or_stressed: "Bare or stressed" };
let aid = null, bp = null, map, here = null, current = null;

function say(m, err = false) { const e = $("#msg"); e.textContent = m; e.classList.toggle("err", err); }
async function getJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(r.status); return r.json(); }

function locate() {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition(
      (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy }),
      () => res(null), { enableHighAccuracy: true, timeout: 10000, maximumAge: 15000 });
  });
}
function dist(a, b, c, d) { // metres, equirectangular is accurate enough at this scale
  const k = Math.PI / 180, x = (d - b) * k * Math.cos(((a + c) / 2) * k), y = (c - a) * k;
  return 6371000 * Math.hypot(x, y);
}

async function start() {
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
    $("#tab-map").hidden = b.dataset.tab !== "map"; $("#tab-near").hidden = b.dataset.tab !== "near";
    if (b.dataset.tab === "map") setTimeout(() => map.invalidateSize(), 30); else renderNear();
  }));
  $("#sh-close").addEventListener("click", () => ($("#sheet").hidden = true));
  $("#obsform").addEventListener("submit", send);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  map = L.map("map", { zoomControl: true }).setView([6.499, 3.359], 16);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  try {
    const list = (await getJSON(`${API}/published`)).analyses;
    if (!list.length) { say("No plan has been shared for your area yet. Ask your local planning office to share one."); return; }
    aid = list.sort((a, b) => b.created - a.created)[0].id;
    bp = await getJSON(`${API}/${aid}/blueprint`);
  } catch (e) { say("Could not load the plan. Check your connection and reopen the app.", true); return; }
  const m = bp.meta;
  $("#region").textContent = m.region;
  $("#summary").textContent = `${m.trees.toLocaleString()} native trees are planned. Together they should cool nearby streets by about ${m.cooling20.toFixed(1)} °C and store ${Math.round(m.tco2_20)} tonnes of CO₂ over 20 years.` + (m.synthetic ? " This is a demonstration plan built on synthetic data." : "");
  const w = m.bbox; map.fitBounds([[w[1], w[0]], [w[3], w[2]]]);
  draw();
  here = await locate();
  if (here) L.circleMarker([here.lat, here.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#2a3977", fillOpacity: 1 }).addTo(map).bindTooltip("You are here");
}

function draw() {
  bp.features.forEach((f) => {
    const [lon, lat] = f.geometry.coordinates, p = f.properties;
    L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 1.5, fillColor: p.obs ? "#2f7d46" : "#8a9a52", fillOpacity: 0.95 })
      .addTo(map).on("click", () => openSite(f));
  });
}
function renderNear() {
  const ul = $("#nearlist"); ul.innerHTML = "";
  if (!here) { ul.innerHTML = `<li class="hint">Allow location access to list the trees closest to you.</li>`; return; }
  bp.features.map((f) => ({ f, d: dist(here.lat, here.lon, f.geometry.coordinates[1], f.geometry.coordinates[0]) }))
    .sort((a, b) => a.d - b.d).slice(0, 12).forEach(({ f, d }) => {
      const li = document.createElement("li");
      li.innerHTML = `<button><strong>${esc(f.properties.cn)}</strong><span>${f.properties.n} trees, ${d < 1000 ? Math.round(d) + " m" : (d / 1000).toFixed(1) + " km"} away${f.properties.obs ? ", " + f.properties.obs + " photos" : ""}</span></button>`;
      li.querySelector("button").addEventListener("click", () => openSite(f)); ul.appendChild(li);
    });
}

async function openSite(f) {
  current = f; const p = f.properties;
  $("#sh-title").textContent = `${p.cn}: ${p.n} trees`; $("#sh-sci").textContent = p.sp; $("#sh-why").textContent = p.why;
  $("#sheet").hidden = false; $("#obsform").reset();
  const ul = $("#sh-obs"); ul.innerHTML = `<li class="hint">Loading...</li>`;
  try {
    const o = (await getJSON(`${API}/${aid}/sites/${p.id}/observations`)).observations.slice(-5).reverse();
    ul.innerHTML = o.length ? o.map((x) => `<li><img loading="lazy" alt="" src="${esc(x.photo)}"><span>${esc(STATUS[x.status] || x.status)}<br><span class="hint">${new Date(x.ts * 1000).toLocaleDateString()}${x.note ? ": " + esc(x.note) : ""}</span></span></li>`).join("")
      : `<li class="hint">No photos yet. Be the first to check on this tree.</li>`;
  } catch (e) { ul.innerHTML = `<li class="hint">Photos are unavailable offline.</li>`; }
}

/* Shrink photos on the phone first: a 4 MB camera photo becomes roughly 40-70 KB. */
function shrink(file, max = 640, quality = 0.6) {
  return new Promise((res, rej) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const s = Math.min(1, max / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      c.toBlob((b) => (b ? res(b) : rej(new Error("encode"))), "image/jpeg", quality);
    };
    img.onerror = () => rej(new Error("decode")); img.src = url;
  });
}

async function send(e) {
  e.preventDefault();
  const file = $("#photo").files[0]; if (!file || !current) return;
  const btn = $("#send"); btn.disabled = true; say("Finding your location...");
  try {
    const pos = await locate();
    if (!pos) { say("Location is needed to match the photo to this tree. Turn on location for this site and try again.", true); return; }
    say("Shrinking and sending your photo...");
    const blob = await shrink(file);
    const fd = new FormData();
    fd.append("photo", blob, "tree.jpg"); fd.append("lat", pos.lat); fd.append("lon", pos.lon);
    fd.append("accuracy_m", Math.round(pos.acc || 30)); fd.append("note", $("#note").value);
    const r = await fetch(`${API}/${aid}/sites/${current.properties.id}/observations`, { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { say(typeof j.detail === "string" ? j.detail : "Could not send the photo. Try again.", true); return; }
    say(`Sent (${Math.round(j.bytes / 1024)} KB). ${STATUS[j.status]}. Thank you for tending this tree.`);
    here = pos; openSite(current);
  } catch (err) { say("Could not send the photo. Check your connection and try again.", true); }
  finally { btn.disabled = false; }
}

start();
