/**
 * The "orb": a soft, organic visualiser that reacts to whoever is talking.
 * idle -> gentle breathing; listening -> green, follows the mic; speaking -> Snapdeal red,
 * follows Disha's voice; thinking -> amber with an orbiting arc while tools run.
 */
const PALETTES = {
  idle: { glow: "rgba(228, 0, 70, 0.10)", inner: ["#ffe3ec", "#fff1f5", "#ffffff"], outer: ["#f2a9bf", "#f7c6d5", "#fde4ec"] },
  connecting: { glow: "rgba(228, 0, 70, 0.14)", inner: ["#ffe3ec", "#fff1f5", "#ffffff"], outer: ["#ef8fad", "#f5b8cb", "#fde4ec"] },
  listening: { glow: "rgba(16, 150, 110, 0.16)", inner: ["#dff7ee", "#ecfbf5", "#ffffff"], outer: ["#3fb98f", "#86d6b7", "#c9eedf"] },
  speaking: { glow: "rgba(228, 0, 70, 0.22)", inner: ["#ffd1df", "#ffe6ee", "#ffffff"], outer: ["#e40046", "#f0507f", "#f8a9c0"] },
  thinking: { glow: "rgba(214, 120, 0, 0.18)", inner: ["#fff0d6", "#fff6e6", "#ffffff"], outer: ["#e08a00", "#f0b44d", "#f8d9a0"] },
};

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = "idle";
    this.level = 0;
    this.getLevel = () => 0;
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.t0 = performance.now();
    this.frame = this.frame.bind(this);
    requestAnimationFrame(this.frame);
  }

  setState(state) {
    this.state = PALETTES[state] ? state : "idle";
  }

  frame(now) {
    const { ctx, canvas } = this;
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const t = (now - this.t0) / 1000;
    const palette = PALETTES[this.state];

    const target = this.state === "idle" ? 0 : Math.min(1, this.getLevel() * 5);
    this.level += (target - this.level) * (target > this.level ? 0.35 : 0.08);
    const amp = this.level;
    const base = w * 0.25;
    const breathe = this.reduced ? 0 : Math.sin(t * 1.5) * 0.018;

    ctx.clearRect(0, 0, w, h);

    // Soft halo.
    const haloR = base * (1.65 + amp * 0.4);
    const halo = ctx.createRadialGradient(cx, cy, base * 0.5, cx, cy, haloR);
    halo.addColorStop(0, palette.glow);
    halo.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, haloR, 0, Math.PI * 2);
    ctx.fill();

    // Three layered, gently wobbling blobs.
    for (let k = 0; k < 3; k++) {
      ctx.beginPath();
      const points = 72;
      for (let i = 0; i <= points; i++) {
        const a = (i / points) * Math.PI * 2;
        const wobble = this.reduced
          ? 0
          : (Math.sin(a * (3 + k) + t * (1.1 + k * 0.45)) * 0.035 +
              Math.sin(a * (5 + k) - t * (0.7 + k * 0.3)) * 0.022) *
            (0.45 + amp * 1.8);
        const r = base * (1 + breathe + amp * 0.2 + wobble) * (1 - k * 0.14);
        const x = cx + Math.cos(a) * r;
        const y = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      const fill = ctx.createRadialGradient(cx - base * 0.35, cy - base * 0.4, base * 0.08, cx, cy, base * 1.25);
      fill.addColorStop(0, palette.inner[k]);
      fill.addColorStop(1, palette.outer[k]);
      ctx.globalAlpha = k === 0 ? 1 : 0.6;
      ctx.fillStyle = fill;
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Orbiting arc while connecting / running tools.
    if (this.state === "thinking" || this.state === "connecting") {
      const r = base * 1.32;
      const start = this.reduced ? 0 : t * 3.2;
      ctx.lineWidth = w * 0.012;
      ctx.lineCap = "round";
      ctx.strokeStyle = palette.outer[0];
      ctx.beginPath();
      ctx.arc(cx, cy, r, start, start + Math.PI * 0.55);
      ctx.stroke();
    }

    requestAnimationFrame(this.frame);
  }
}
