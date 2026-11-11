import { useEffect, useRef } from "react";

/**
 * Animated backdrop: aurora colour blobs, a slowly panning grid and a canvas "constellation"
 * whose particles drift, link up when close, connect to the pointer, scatter on click, and are
 * crossed now and then by shooting stars. Theme-aware; static for reduced motion; pauses when
 * the tab is hidden.
 */
interface Particle { x: number; y: number; vx: number; vy: number; r: number; hue: number; tw: number }
interface Meteor { x: number; y: number; vx: number; vy: number; life: number }

const LINK = 130; // px between particles that get a line
const POINTER_LINK = 190;

function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function rgb(hex: string): [number, number, number] {
  const m = hex.replace("#", "").match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [124, 147, 255];
}

export function BackgroundFX() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const touch = window.matchMedia?.("(pointer: coarse)").matches ?? false;

    let w = 0, h = 0, dpr = 1, raf = 0, frame = 0;
    let particles: Particle[] = [];
    const meteors: Meteor[] = [];
    const pointer = { x: -9999, y: -9999, active: false };
    let accent: [number, number, number] = [124, 147, 255];
    let accent2: [number, number, number] = [176, 140, 255];
    let dark = true;

    const readTheme = () => {
      accent = rgb(cssColor("--accent", "#7c93ff"));
      accent2 = rgb(cssColor("--accent-2", "#b08cff"));
      dark = getComputedStyle(document.documentElement).colorScheme.includes("dark");
    };

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const target = Math.min(touch ? 45 : 110, Math.round((w * h) / 13000));
      while (particles.length < target) {
        particles.push({
          x: Math.random() * w, y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.35, vy: (Math.random() - 0.5) * 0.35,
          r: Math.random() * 1.8 + 0.9, hue: Math.random(), tw: Math.random() * Math.PI * 2,
        });
      }
      particles = particles.slice(0, target);
    };

    const color = (p: Particle, a: number) => {
      const [r1, g1, b1] = accent, [r2, g2, b2] = accent2;
      const t = p.hue;
      return `rgba(${Math.round(r1 + (r2 - r1) * t)}, ${Math.round(g1 + (g2 - g1) * t)}, ${Math.round(b1 + (b2 - b1) * t)}, ${a})`;
    };

    const draw = () => {
      frame++;
      if (frame % 90 === 1) readTheme();
      ctx.clearRect(0, 0, w, h);
      const baseA = dark ? 1 : 0.75;

      for (const p of particles) {
        if (!reduced) {
          // gentle pull towards the pointer, with a soft personal-space push close in
          if (pointer.active) {
            const dx = pointer.x - p.x, dy = pointer.y - p.y;
            const d2 = dx * dx + dy * dy;
            if (d2 < POINTER_LINK * POINTER_LINK && d2 > 1) {
              const d = Math.sqrt(d2);
              const f = d < 60 ? -0.03 : 0.006;
              p.vx += (dx / d) * f;
              p.vy += (dy / d) * f;
            }
          }
          p.vx *= 0.985;
          p.vy *= 0.985;
          const speed = Math.hypot(p.vx, p.vy);
          if (speed < 0.12) { p.vx += (Math.random() - 0.5) * 0.04; p.vy += (Math.random() - 0.5) * 0.04; }
          p.x += p.vx;
          p.y += p.vy;
          if (p.x < -20) p.x = w + 20; else if (p.x > w + 20) p.x = -20;
          if (p.y < -20) p.y = h + 20; else if (p.y > h + 20) p.y = -20;
          p.tw += 0.03;
        }
      }

      // links between nearby particles
      ctx.lineWidth = 1;
      for (let i = 0; i < particles.length; i++) {
        const a = particles[i];
        for (let j = i + 1; j < particles.length; j++) {
          const b = particles[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < LINK * LINK) {
            const alpha = (1 - Math.sqrt(d2) / LINK) * 0.32 * baseA;
            ctx.strokeStyle = color(a, alpha);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      // links to the pointer
      if (pointer.active) {
        for (const p of particles) {
          const d = Math.hypot(pointer.x - p.x, pointer.y - p.y);
          if (d < POINTER_LINK) {
            ctx.strokeStyle = color(p, (1 - d / POINTER_LINK) * 0.65 * baseA);
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.moveTo(pointer.x, pointer.y);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
          }
        }
        ctx.lineWidth = 1;
      }

      // particles with a twinkle
      for (const p of particles) {
        const tw = 0.55 + Math.sin(p.tw) * 0.45;
        ctx.fillStyle = color(p, (0.5 + tw * 0.5) * baseA);
        ctx.shadowColor = color(p, 0.8 * baseA);
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * (0.8 + tw * 0.4), 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.shadowBlur = 0;

      // shooting stars
      if (!reduced && Math.random() < 0.004 && meteors.length < 2) {
        const fromLeft = Math.random() < 0.5;
        meteors.push({ x: fromLeft ? Math.random() * w * 0.5 : w * 0.5 + Math.random() * w * 0.5, y: -20,
          vx: (fromLeft ? 1 : -1) * (6 + Math.random() * 4), vy: 4 + Math.random() * 3, life: 1 });
      }
      for (let i = meteors.length - 1; i >= 0; i--) {
        const m = meteors[i];
        m.x += m.vx; m.y += m.vy; m.life -= 0.012;
        if (m.life <= 0 || m.y > h + 40) { meteors.splice(i, 1); continue; }
        const tail = 14;
        const grad = ctx.createLinearGradient(m.x, m.y, m.x - m.vx * tail, m.y - m.vy * tail);
        grad.addColorStop(0, `rgba(255,255,255,${0.9 * m.life * baseA})`);
        grad.addColorStop(0.3, `rgba(${accent2.join(",")},${0.5 * m.life * baseA})`);
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(m.x, m.y);
        ctx.lineTo(m.x - m.vx * tail, m.y - m.vy * tail);
        ctx.stroke();
      }

      if (!reduced) raf = requestAnimationFrame(draw);
    };

    const onMove = (e: PointerEvent) => { pointer.x = e.clientX; pointer.y = e.clientY; pointer.active = true; };
    const onLeave = () => { pointer.active = false; };
    const onDown = (e: PointerEvent) => {
      // shockwave: scatter nearby particles
      for (const p of particles) {
        const dx = p.x - e.clientX, dy = p.y - e.clientY;
        const d = Math.hypot(dx, dy);
        if (d < 260 && d > 0.5) {
          const f = (1 - d / 260) * 5;
          p.vx += (dx / d) * f;
          p.vy += (dy / d) * f;
        }
      }
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && !reduced) raf = requestAnimationFrame(draw);
    };
    const onResize = () => { resize(); if (reduced) draw(); };

    readTheme();
    resize();
    draw();
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    document.addEventListener("mouseleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    const themeWatch = new MutationObserver(() => { readTheme(); if (reduced) draw(); });
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      document.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
      themeWatch.disconnect();
    };
  }, []);

  return (
    <div className="bg-fx" aria-hidden="true">
      <div className="aurora"><span /><span /><span /></div>
      <div className="bg-grid" />
      <canvas ref={canvasRef} className="bg-canvas" />
    </div>
  );
}
