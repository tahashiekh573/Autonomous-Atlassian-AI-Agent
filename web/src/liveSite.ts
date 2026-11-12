// "Watch it live": while a run executes, a second browser tab shows the connected Atlassian site
// and jumps to every resource the moment an agent finishes creating it. Atlassian pages refuse
// to load inside an iframe, so a tab we opened (and may therefore navigate) is the only way.
import { useEffect, useRef, useState } from "react";
import type { Operation, RunDetail } from "./types";

// Off unless the user ticks the box: by default everything stays inside the dashboard.
const PREF_KEY = "aaa.liveSite.optin";
const MIN_SHOW_MS = 3500; // keep each page on screen long enough to see it

let liveTab: Window | null = null;

export function liveEnabled(): boolean {
  try { return localStorage.getItem(PREF_KEY) === "on"; } catch { return false; }
}

export function setLiveEnabled(on: boolean): void {
  try { localStorage.setItem(PREF_KEY, on ? "on" : "off"); } catch { /* optional */ }
}

export function liveTabOpen(): boolean {
  return !!liveTab && !liveTab.closed;
}

/** Must run inside a click handler (browsers block pop-ups otherwise). Returns false if blocked. */
export function openLiveSite(url: string): boolean {
  if (liveTabOpen()) {
    liveTab?.focus();
    return true;
  }
  const tab = window.open("about:blank", "atlassian-live");
  if (!tab) return false;
  try { tab.opener = null; } catch { /* the page we navigate to can't reach back into the app */ }
  tab.location.href = url;
  liveTab = tab;
  return true;
}

function show(url: string): void {
  if (liveTabOpen()) {
    try { liveTab!.location.href = url; } catch { /* closed meanwhile */ }
  }
}

function siteHome(site: string, product: string): string {
  if (product === "confluence") return `${site}/wiki/home`;
  if (product === "jsm") return `${site}/jira/servicedesk/projects`;
  return `${site}/jira/your-work`;
}

/** Where to look at an operation's result on the site (its own link, else the closest page). */
export function resultUrl(op: Operation, site: string): string | null {
  const own = op.outcome?.resource?.url || (op.outcome?.outputs?.url as string | undefined);
  if (own) return own;
  const params = { ...(op.params ?? {}), ...(op.resolved_params ?? {}) } as Record<string, unknown>;
  const key = (params.project_key as string | undefined) ?? (op.outcome?.outputs?.key as string | undefined);
  const name = op.operation;
  if (name.includes("automation")) return key ? `${site}/jira/settings/automation#/rule-list?projectKey=${key}` : `${site}/jira/settings/automation`;
  if (name.includes("workflow")) return key ? `${site}/browse/${key}` : `${site}/jira/settings/issues/workflows`;
  if (name.includes("request_type") || name.includes("queue") || name.includes("form") || name.includes("sla")) {
    return key ? `${site}/jira/servicedesk/projects/${key}` : siteHome(site, "jsm");
  }
  if (key) return `${site}/browse/${key}`;
  return null;
}

/**
 * Follows a run: every newly completed step with a page on the site is queued and shown in the
 * live tab one after another; when the run ends, the first resource created is shown last.
 */
export function useLiveFollow(run: RunDetail | null, site: string | null): string | null {
  const seen = useRef<Set<string>>(new Set());
  const queue = useRef<string[]>([]);
  const busyUntil = useRef(0);
  const runId = useRef<string | null>(null);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (!run || !site) return;
    if (runId.current !== run.id) {
      runId.current = run.id;
      // steps already finished before we started watching are not replayed
      seen.current = new Set(run.operations.filter((o) => o.status === "completed").map((o) => o.op_id));
      queue.current = [];
    }
    for (const op of run.operations) {
      if (op.status !== "completed" || seen.current.has(op.op_id)) continue;
      seen.current.add(op.op_id);
      const url = resultUrl(op, site);
      if (url && queue.current[queue.current.length - 1] !== url) queue.current.push(url);
    }
    if (queue.current.length > 6) queue.current = queue.current.slice(-6); // fast runs: keep up
    if (["completed", "completed_with_errors"].includes(run.status)) {
      const first = run.operations.find((o) => o.status === "completed" && resultUrl(o, site));
      const finale = first ? resultUrl(first, site) : null;
      if (finale && queue.current[queue.current.length - 1] !== finale) queue.current.push(finale);
    }
  }, [run, site]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!liveTabOpen() || Date.now() < busyUntil.current) return;
      const next = queue.current.shift();
      if (!next) return;
      show(next);
      setCurrent(next);
      busyUntil.current = Date.now() + MIN_SHOW_MS;
    }, 400);
    return () => window.clearInterval(timer);
  }, []);

  return current;
}

export { siteHome };
