// Animation switch: rich motion on capable machines, a still backdrop on weak ones or on request.
const KEY = "aaa.fx";
const EVENT = "aaa-fx-change";

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/** Explicit choice if the user made one, otherwise on for machines with more than 4 cores. */
export function fxEnabled(): boolean {
  let pref: string | null = null;
  try { pref = localStorage.getItem(KEY); } catch { /* optional */ }
  if (pref === "on") return true;
  if (pref === "off") return false;
  return !reducedMotion() && (navigator.hardwareConcurrency ?? 8) > 4;
}

export function applyFx(on = fxEnabled()): void {
  document.documentElement.classList.toggle("fx-off", !on);
}

export function setFx(on: boolean): void {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* optional */ }
  applyFx(on);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: on }));
}

export function onFxChange(listener: (on: boolean) => void): () => void {
  const handler = (e: Event) => listener(Boolean((e as CustomEvent<boolean>).detail));
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
