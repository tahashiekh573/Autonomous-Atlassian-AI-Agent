import { useEffect, useRef } from "react";

/**
 * Modern cursor effects: a precise dot, a trailing blend-mode ring that grows over interactive
 * elements, a soft spotlight that follows the pointer, a glow on the hovered card, magnetic
 * buttons and a click ripple. Disabled on touch devices and for reduced motion.
 */
const INTERACTIVE = "a, button, [role='button'], summary, .chip, .nav-item, label";
const TEXT = "input, textarea, select, [contenteditable='true']";
const SPOT = ".card, .op:not(.failed)";
const MAGNETIC = "button.primary, .icon-btn, .mic, .brand-logo, .chip";

export function CursorFX() {
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const glow = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fine = window.matchMedia?.("(pointer: fine)").matches;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduced) return;
    const root = document.documentElement;
    root.classList.add("fx-cursor");

    let x = -100, y = -100, rx = x, ry = y, gx = x, gy = y, raf = 0;
    let spot: HTMLElement | null = null;
    let magnet: HTMLElement | null = null;

    const release = () => {
      if (magnet) magnet.style.transform = "";
      magnet = null;
    };

    const move = (e: PointerEvent) => {
      x = e.clientX;
      y = e.clientY;
      if (!root.classList.contains("fx-visible")) {
        rx = gx = x;
        ry = gy = y;
        root.classList.add("fx-visible");
      }
      const target = e.target instanceof Element ? e.target : null;

      const typing = !!target?.closest(TEXT);
      ring.current?.classList.toggle("text", typing);
      dot.current?.classList.toggle("text", typing);
      ring.current?.classList.toggle("hover", !typing && !!target?.closest(INTERACTIVE));

      const card = target?.closest<HTMLElement>(SPOT) ?? null;
      if (card !== spot) {
        spot?.style.removeProperty("--mx");
        spot?.style.removeProperty("--my");
        spot = card;
      }
      if (card) {
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${x - r.left}px`);
        card.style.setProperty("--my", `${y - r.top}px`);
      }

      const m = target?.closest<HTMLElement>(MAGNETIC) ?? null;
      if (m !== magnet) release();
      if (m && !(m as HTMLButtonElement).disabled) {
        const r = m.getBoundingClientRect();
        const dx = (x - (r.left + r.width / 2)) * 0.25;
        const dy = (y - (r.top + r.height / 2)) * 0.35;
        m.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`;
        magnet = m;
      }
    };

    const down = (e: PointerEvent) => {
      ring.current?.classList.add("down");
      const ripple = document.createElement("span");
      ripple.className = "fx-ripple";
      ripple.style.left = `${e.clientX}px`;
      ripple.style.top = `${e.clientY}px`;
      ripple.addEventListener("animationend", () => ripple.remove());
      document.body.appendChild(ripple);
    };
    const up = () => ring.current?.classList.remove("down");
    const leave = () => { root.classList.remove("fx-visible"); release(); };

    const tick = () => {
      rx += (x - rx) * 0.2;
      ry += (y - ry) * 0.2;
      gx += (x - gx) * 0.07;
      gy += (y - gy) * 0.07;
      if (dot.current) dot.current.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      if (ring.current) ring.current.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      if (glow.current) glow.current.style.transform = `translate3d(${gx}px, ${gy}px, 0)`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerdown", down, { passive: true });
    window.addEventListener("pointerup", up, { passive: true });
    document.addEventListener("mouseleave", leave);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      document.removeEventListener("mouseleave", leave);
      release();
      root.classList.remove("fx-cursor", "fx-visible");
    };
  }, []);

  return (
    <div aria-hidden="true">
      <div className="fx-glow" ref={glow} />
      <div className="fx-ring" ref={ring} />
      <div className="fx-dot" ref={dot} />
    </div>
  );
}
