/* NOOB AI's 3D gem: a colourful faceted crystal that rotates in 3D (drawn on a canvas, no libraries).

   How it is made: an icosahedron (20 triangles), each face split into 4 and pushed out onto a sphere (80), then
   every one of those split into 3 triangles meeting at a point pulled slightly outwards (240 facets). Each facet is filled with a bold colour, outlined in white, and has a
   smaller triangle of another colour inside it. Every frame the shape is rotated, the facets facing away are
   skipped, the rest are drawn back-to-front with simple lighting, so it looks solid and 3D.

   Use: <div class="gem" style="--s:200px"><div class="gem-halo"></div><canvas></canvas></div>
   Inside the Talk orb it reacts to NOOB: faster while thinking, pulsing while listening. class="gem sleep" = asleep. */
(() => {
  "use strict";
  const PALETTE = ["#e6007e", "#00aeef", "#ffd200", "#6a2c91", "#2bb673", "#ef3b24", "#f7941d", "#23206b", "#ff5fa2", "#00c9b7"];
  const LIGHT = norm([-0.45, 0.6, 0.9]);

  function norm(a) { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; }
  function add(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function mul(a, k) { return [a[0] * k, a[1] * k, a[2] * k]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function rgb(hex) { const n = parseInt(hex.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }

  function makeFacets() {
    const t = (1 + Math.sqrt(5)) / 2;
    const v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
               [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]].map(norm);
    const ico = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2],
                 [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5],
                 [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
    const faces = [];                                        // each face split into 4, on the sphere
    for (const [i, j, k] of ico) {
      const a = v[i], b = v[j], c = v[k];
      const ab = norm(add(a, b)), bc = norm(add(b, c)), ca = norm(add(c, a));
      faces.push([a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]);
    }
    let seed = 20260927;                                     // same colours every time
    const pick = () => (seed = (seed * 16807) % 2147483647) % PALETTE.length;
    const facets = [];
    for (const [a, b, c] of faces) {
      const tip = mul(norm(add(add(a, b), c)), 1.045);                 // the face's centre, pulled outwards
      for (const [p, q] of [[a, b], [b, c], [c, a]]) {
        let n = norm(cross(sub(q, p), sub(tip, p)));
        const centre = mul(add(add(p, q), tip), 1 / 3);
        if (dot(n, centre) < 0) n = mul(n, -1);                          // always pointing outwards
        const outer = pick();
        let inner = pick();
        if (inner === outer) inner = (inner + 3) % PALETTE.length;
        facets.push({ pts: [p, q, tip], n, outer: rgb(PALETTE[outer]), inner: rgb(PALETTE[inner]) });
      }
    }
    return facets;
  }
  const FACETS = makeFacets();

  function start(el) {
    const canvas = el.querySelector("canvas");
    if (!canvas || el.dataset.started) return;
    el.dataset.started = "1";
    const ctx = canvas.getContext("2d");
    const orb = el.closest(".orb");
    let angleY = 0.6, last = performance.now(), size = 0, dpr = 1;

    function resize() {
      size = el.clientWidth || 200;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(size * dpr);
      canvas.height = Math.round(size * dpr);
    }

    function shade(color, light) {
      const k = 0.7 + 0.3 * light;
      return `rgb(${Math.round(color[0] * k)},${Math.round(color[1] * k)},${Math.round(color[2] * k)})`;
    }

    function frame(now) {
      if (!el.isConnected) return;
      requestAnimationFrame(frame);
      if (document.hidden) { last = now; return; }
      if (el.clientWidth !== size) resize();
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const mood = orb ? orb.className : "";
      const sleeping = el.classList.contains("sleep");
      const speed = sleeping ? 0.08 : mood.includes("thinking") ? 2.6 : mood.includes("listening") ? 0.9
        : mood.includes("speaking") ? 1.1 : 0.45;
      angleY += speed * dt;
      const t = now / 1000;
      const angleX = 0.38 * Math.sin(t * 0.37) + 0.25;
      const pulse = mood.includes("listening") ? 1 + 0.035 * Math.sin(t * 7) : 1 + 0.015 * Math.sin(t * 1.6);

      const cy = Math.cos(angleY), sy = Math.sin(angleY), cx = Math.cos(angleX), sx = Math.sin(angleX);
      const rot = (p) => {                                   // turn around the vertical axis, then tilt
        const x = p[0] * cy + p[2] * sy, z = -p[0] * sy + p[2] * cy;
        return [x, p[1] * cx - z * sx, p[1] * sx + z * cx];
      };
      const R = size * dpr * 0.42 * pulse, mid = size * dpr / 2, eye = 4.5;
      const project = (p) => { const k = eye / (eye - p[2]); return [mid + p[0] * R * k, mid - p[1] * R * k]; };

      const visible = [];
      for (const f of FACETS) {
        const n = rot(f.n);
        if (n[2] <= 0.02) continue;                          // facing away: hidden behind the gem
        const pts = f.pts.map(rot);
        visible.push({ f, n, pts, depth: (pts[0][2] + pts[1][2] + pts[2][2]) / 3 });
      }
      visible.sort((a, b) => a.depth - b.depth);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineJoin = "round";
      const line = Math.max(1, size * dpr / 150);
      for (const { f, n, pts } of visible) {
        const light = Math.max(0, dot(n, LIGHT));
        const [a, b, c] = pts.map(project);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(c[0], c[1]); ctx.closePath();
        ctx.fillStyle = shade(f.outer, light);
        ctx.fill();
        ctx.lineWidth = line;
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.stroke();
        const g = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3];   // the smaller triangle inside
        const inset = (p) => [g[0] + (p[0] - g[0]) * 0.52, g[1] + (p[1] - g[1]) * 0.52];
        const [ia, ib, ic] = [inset(a), inset(b), inset(c)];
        ctx.beginPath(); ctx.moveTo(ia[0], ia[1]); ctx.lineTo(ib[0], ib[1]); ctx.lineTo(ic[0], ic[1]); ctx.closePath();
        ctx.fillStyle = shade(f.inner, light);
        ctx.fill();
        ctx.lineWidth = line * 0.7;
        ctx.stroke();
      }
    }
    resize();
    requestAnimationFrame(frame);
  }

  function startAll() { document.querySelectorAll(".gem").forEach(start); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startAll);
  else startAll();
  window.NoobGem = { startAll };
})();
