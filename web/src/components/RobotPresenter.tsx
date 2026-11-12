// A holographic assistant that tells the user, out loud, what the run did and what it could not do.
// Speech uses the browser's voices sentence by sentence, so the caption and the robot's mouth stay
// in step with what is being said. Everything shown comes from the run's verified report.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIVE, type Report, type RunDetail } from "../types";

type Lang = "en" | "ur";
const LANG_KEY = "aaa.robot.lang";
const AUTO_KEY = "aaa.robot.auto";

function stored(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function store(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* optional */ }
}

function list(items: string[], max = 4): string {
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return shown.join(", ") + (rest > 0 ? ` and ${rest} more` : "");
}

/** The narration, sentence by sentence, built only from the verified report. */
export function narration(report: Report, lang: Lang): string[] {
  const reqs = report.requirements ?? [];
  const done = reqs.filter((r) => r.status === "done").map((r) => r.requirement);
  const notDone = reqs.filter((r) => r.status === "failed" || r.status === "missing").map((r) => r.requirement);
  const partial = reqs.filter((r) => r.status === "partial").map((r) => r.requirement);
  const manual = reqs.filter((r) => r.status === "manual").map((r) => r.requirement);
  const pct = report.completion_percent;

  if (lang === "ur") {
    const out: string[] = [];
    if (reqs.length) {
      out.push(`آپ کی ${reqs.length} مانگی ہوئی چیزوں میں سے ${done.length} مکمل اور تصدیق شدہ ہیں۔`);
    } else {
      out.push(`${report.completed} مراحل مکمل اور تصدیق شدہ ہیں۔`);
    }
    if (pct != null) out.push(`کام ${pct} فیصد مکمل ہے۔`);
    if (done.length) out.push(`جو بن گیا: ${list(done)}۔`);
    if (partial.length) out.push(`جزوی طور پر ہوا: ${list(partial)}۔`);
    if (notDone.length) out.push(`جو نہیں ہو سکا: ${list(notDone)}۔`);
    else if (report.failed > 0) out.push(`${report.failed} مراحل ناکام ہوئے۔`);
    if (manual.length) out.push(`یہ ہاتھ سے کرنا ہوگا، کیونکہ اس کا API نہیں ہے: ${list(manual)}۔`);
    if (!notDone.length && !report.failed) out.push("کوئی غلطی نہیں ہوئی۔");
    return out;
  }

  const out: string[] = [];
  if (reqs.length) out.push(`${done.length} of the ${reqs.length} things you asked for are done and verified.`);
  else out.push(`${report.completed} steps were completed and verified.`);
  if (pct != null) out.push(`The work is ${pct} percent complete.`);
  if (done.length) out.push(`Done: ${list(done)}.`);
  if (partial.length) out.push(`Partly done: ${list(partial)}.`);
  if (notDone.length) out.push(`Not done: ${list(notDone)}.`);
  else if (report.failed > 0) out.push(`${report.failed} steps failed.`);
  if (manual.length) out.push(`You need to do this by hand, because there is no API for it: ${list(manual)}.`);
  if (!notDone.length && !report.failed) out.push("Nothing failed.");
  return out;
}

function pickVoice(lang: Lang): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  const want = lang === "ur" ? ["ur-PK", "ur-IN", "ur", "hi-IN"] : ["en-US", "en-GB", "en"];
  for (const tag of want) {
    const v = voices.find((x) => x.lang.toLowerCase().startsWith(tag.toLowerCase()) && /natural|online|neural/i.test(x.name))
      ?? voices.find((x) => x.lang.toLowerCase().startsWith(tag.toLowerCase()));
    if (v) return v;
  }
  return null;
}

function useNarrator() {
  const [speaking, setSpeaking] = useState(false);
  const [caption, setCaption] = useState("");
  const token = useRef(0);

  const stop = useCallback(() => {
    token.current += 1;
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }, []);

  const say = useCallback((sentences: string[], lang: Lang) => {
    if (!("speechSynthesis" in window)) { setCaption(sentences.join(" ")); return; }
    const mine = ++token.current;
    window.speechSynthesis.cancel();
    const voice = pickVoice(lang);
    setSpeaking(true);
    const next = (i: number) => {
      if (mine !== token.current) return;
      if (i >= sentences.length) { setSpeaking(false); return; }
      setCaption(sentences[i]);
      const u = new SpeechSynthesisUtterance(sentences[i]);
      if (voice) u.voice = voice;
      u.lang = voice?.lang ?? (lang === "ur" ? "ur-PK" : "en-US");
      u.rate = 1;
      u.onend = () => next(i + 1);
      u.onerror = () => next(i + 1);
      window.speechSynthesis.speak(u);
    };
    next(0);
  }, []);

  useEffect(() => () => { window.speechSynthesis?.cancel(); }, []);
  return { speaking, caption, setCaption, say, stop };
}

const CAPABILITIES = [
  "Jira projects, boards, sprints and issues",
  "Workflows, schemes and transitions",
  "Automation rules and dashboards",
  "JSM service desks and request types",
  "Queues, SLA goals and forms",
  "Confluence spaces, pages and knowledge base",
  "Links between Jira, JSM and Confluence",
  "Every step verified on your live site",
];

function greeting(lang: Lang): string[] {
  return lang === "ur"
    ? [
        "السلام علیکم، میں طہٰ اے آئی ہوں۔",
        "مجھے بتائیں کہ جیرا، سروس مینجمنٹ یا کنفلوئنس میں کیا بنانا ہے۔",
        "میں پلان بناؤں گا، آپ کی منظوری لوں گا، پھر ہر قدم بنا کر اس کی تصدیق کروں گا۔",
      ]
    : [
        "Hello, I am TAHA AI.",
        "Tell me what to build in Jira, Service Management or Confluence.",
        "I will plan it, wait for your approval, then build and verify every step on your site.",
      ];
}

const STATUS_TEXT: Record<string, string> = {
  planning: "Planning",
  needs_clarification: "Needs your answer",
  blocked: "Blocked",
  awaiting_approval: "Awaiting approval",
  executing: "Working",
  rejected: "Plan rejected",
  failed: "Run failed",
};

export function RobotPresenter({ run, agentCount = 8 }: { run: RunDetail | null; agentCount?: number }) {
  const report = run?.report ?? null;
  const active = !!run && ACTIVE.includes(run.status);
  const [lang, setLang] = useState<Lang>(() => (stored(LANG_KEY, "en") === "ur" ? "ur" : "en"));
  const [auto, setAuto] = useState(() => stored(AUTO_KEY, "on") === "on");
  const { speaking, caption, setCaption, say, stop } = useNarrator();
  const sentences = useMemo(() => (report ? narration(report, lang) : run ? [] : greeting(lang)), [report, run, lang]);
  const wasActive = useRef(active);

  // Speak on its own only when a run finishes while it is being watched (not for old runs).
  useEffect(() => {
    if (wasActive.current && !active && report && auto) say(narration(report, lang), lang);
    wasActive.current = active;
  }, [active, report, auto, lang, say]);

  // A different run: stop talking about the previous one.
  const runId = run?.id ?? null;
  useEffect(() => { stop(); setCaption(""); }, [runId, stop, setCaption]);

  const ops = run?.operations ?? [];
  const reqs = report?.requirements ?? [];
  const counts = {
    done: reqs.length ? reqs.filter((r) => r.status === "done").length : report?.completed ?? ops.filter((o) => o.status === "completed").length,
    failed: reqs.length ? reqs.filter((r) => r.status === "failed" || r.status === "missing").length : report?.failed ?? ops.filter((o) => o.status === "failed").length,
    manual: reqs.filter((r) => r.status === "manual").length,
    partial: reqs.filter((r) => r.status === "partial").length,
  };
  const total = Math.max(1, reqs.length || (report ? report.completed + report.failed + report.skipped : ops.length));
  const finishedOps = ops.filter((o) => ["completed", "failed", "skipped"].includes(o.status)).length;
  const pct = report?.completion_percent ?? (report ? Math.round((100 * counts.done) / total) : Math.round((100 * finishedOps) / Math.max(1, ops.length)));
  const opState = (s: string) => (s === "completed" ? "done" : s);
  const feed: { text: string; state: string }[] = !run
    ? CAPABILITIES.map((text) => ({ text, state: "done" }))
    : report
      ? reqs.length
        ? reqs.map((r) => ({ text: r.requirement, state: r.status }))
        : ops.map((o) => ({ text: o.description, state: opState(o.status) }))
      : run.status === "executing"
        ? ops.filter((o) => o.status !== "pending").map((o) => ({ text: o.description, state: opState(o.status) }))
        : ops.map((o) => ({ text: o.description, state: "pending" }));

  const mood = speaking ? "speaking" : active ? "working" : counts.failed || run?.status === "failed" ? "concerned" : "idle";
  const statusText = speaking ? "Speaking" : !run ? "Online" : report ? "Report ready" : STATUS_TEXT[run.status] ?? "Standing by";
  const ur = lang === "ur";
  const line = caption
    || (!run ? (ur ? "میں تیار ہوں — اپنا کام لکھیں یا مائیک سے بولیں۔" : "I'm ready — type your request or use the microphone.") : "")
    || (active ? run?.progress_message || (ur ? "آپ کے کام پر لگا ہوا ہوں…" : "Working on your request…") : "")
    || (run?.status === "awaiting_approval" ? (ur ? `${ops.length} قدم کا پلان تیار ہے — دیکھ کر منظوری دیں۔` : `Plan ready: ${ops.length} steps. Review and approve to start.`) : "")
    || (run?.status === "needs_clarification" ? (ur ? "مجھے آپ سے ایک سوال پوچھنا ہے — چیٹ دیکھیں۔" : "I need an answer from you — see the chat.") : "")
    || (report ? (ur ? "رپورٹ سننے کے لیے بٹن دبائیں۔" : "Press “Tell me” to hear what was done and what was not.") : "")
    || run?.progress_message || "";

  const R = 34;
  const C = 2 * Math.PI * R;
  const idle = !run;
  const planOnly = !!run && !report && run.status !== "executing";

  return (
    <section className={`holo mood-${mood}`} aria-label="AI assistant">
      <div className="holo-bg" aria-hidden="true">
        <div className="holo-waves">
          <svg viewBox="0 0 2400 300" preserveAspectRatio="none">
            <defs>
              <linearGradient id="hw1" x1="0" x2="1">
                <stop offset="0" stopColor="#9b6bff" />
                <stop offset=".25" stopColor="#4fd8ff" />
                <stop offset=".5" stopColor="#b06bff" />
                <stop offset=".75" stopColor="#4fd8ff" />
                <stop offset="1" stopColor="#9b6bff" />
              </linearGradient>
            </defs>
            {[0, 1, 2, 3, 4].map((i) => (
              <path key={i} className={`hw hw${i}`} stroke="url(#hw1)" fill="none"
                d={wave(150 + (i - 2) * 6, 26 + i * 7, i * 70)} />
            ))}
          </svg>
        </div>
        <div className="holo-particles">
          {Array.from({ length: 18 }, (_, i) => (
            <i key={i} style={{ "--x": `${(i * 53) % 100}%`, "--y": `${(i * 37) % 90 + 5}%`, "--d": `${(i % 6) * 0.7}s` } as React.CSSProperties} />
          ))}
        </div>
      </div>

      <header className="holo-top">
        <span className="holo-title">TAHA AI · {idle ? "Atlassian assistant" : report ? "Mission report" : "Mission control"}</span>
        <span className={`holo-status s-${mood}`}><i />{statusText}</span>
      </header>

      <div className="holo-body">
        <div className="holo-panel holo-feed" aria-label={idle ? "What I can do" : "Steps"}>
          <div className="holo-label">{idle ? "What I can build" : report ? "Your request" : planOnly ? "Planned steps" : "Live steps"}</div>
          <ul>
            {feed.slice(0, 60).map((f, i) => (
              <li key={i} className={`f-${f.state}`}>
                <span className="mark">{idle ? "◆" : f.state === "done" ? "✓" : f.state === "manual" ? "✋" : f.state === "partial" ? "◐" : f.state === "running" ? "▸" : f.state === "failed" || f.state === "missing" ? "✕" : "·"}</span>
                <span className="txt" title={f.text}>{f.text}</span>
              </li>
            ))}
            {!feed.length && <li className="f-pending"><span className="mark">·</span><span className="txt">Waiting for the first step…</span></li>}
          </ul>
        </div>

        <div className="holo-robot">
          <Robot />
        </div>

        <div className="holo-panel holo-stats">
          <div className="holo-label">{idle ? "Agents online" : planOnly ? "Plan" : "Completion"}</div>
          <div className="holo-ring">
            <svg viewBox="0 0 80 80" aria-hidden="true">
              <circle cx="40" cy="40" r={R} className="ring-bg" />
              <circle cx="40" cy="40" r={R} className="ring-fg" strokeDasharray={C}
                strokeDashoffset={idle || planOnly ? 0 : C * (1 - Math.min(100, pct) / 100)} />
            </svg>
            <b>{idle ? agentCount : planOnly ? ops.length : `${pct}%`}</b>
          </div>
          {idle ? (
            <>
              <Bar label="Jira" value={1} total={1} tone="ok" text="ready" />
              <Bar label="Service Management" value={1} total={1} tone="info" text="ready" />
              <Bar label="Confluence" value={1} total={1} tone="ok" text="ready" />
            </>
          ) : planOnly ? (
            <>
              <Bar label="Steps planned" value={ops.length} total={Math.max(1, ops.length)} tone="info" />
              <Bar label="Need approval" value={ops.filter((o) => o.requires_approval && !o.approved).length} total={Math.max(1, ops.length)} tone="warn" />
            </>
          ) : (
            <>
              <Bar label="Done" value={counts.done} total={total} tone="ok" />
              {counts.partial > 0 && <Bar label="Partial" value={counts.partial} total={total} tone="warn" />}
              <Bar label="Not done" value={counts.failed} total={total} tone="err" />
              {(report || counts.manual > 0) && <Bar label="By hand" value={counts.manual} total={total} tone="info" />}
            </>
          )}
        </div>
      </div>

      <footer className="holo-foot">
        <p className="holo-caption" aria-live="polite" lang={caption && lang === "ur" ? "ur" : undefined} dir={caption && lang === "ur" ? "rtl" : undefined}>
          {line}
        </p>
        <div className="holo-actions">
          {sentences.length > 0 && (speaking
            ? <button className="holo-btn" onClick={stop}>■ Stop</button>
            : <button className="holo-btn primary" onClick={() => say(sentences, lang)}>🔊 Tell me</button>)}
          <div className="holo-seg" role="group" aria-label="Voice language">
            {(["en", "ur"] as Lang[]).map((l) => (
              <button key={l} className={lang === l ? "on" : ""} onClick={() => { stop(); setLang(l); store(LANG_KEY, l); }}>
                {l === "en" ? "English" : "اردو"}
              </button>
            ))}
          </div>
          <label className="holo-auto">
            <input type="checkbox" checked={auto} onChange={(e) => { setAuto(e.target.checked); store(AUTO_KEY, e.target.checked ? "on" : "off"); }} />
            Speak when finished
          </label>
        </div>
      </footer>
    </section>
  );
}

function Bar({ label, value, total, tone, text }: { label: string; value: number; total: number; tone: string; text?: string }) {
  return (
    <div className={`holo-bar t-${tone}`}>
      <div className="row-l"><span>{label}</span><b>{text ?? value}</b></div>
      <div className="track"><span style={{ width: `${Math.round((100 * value) / total)}%` }} /></div>
    </div>
  );
}

/** A smooth sine path, two periods wider than the view so it can slide seamlessly. */
function wave(mid: number, amp: number, phase: number): string {
  // Repeats every 1200 units, so sliding the 2400-wide drawing by half is seamless.
  const pts: string[] = [];
  for (let x = 0; x <= 2400; x += 25) {
    const y = mid + amp * Math.sin(((x + phase) / 300) * Math.PI) * (0.6 + 0.4 * Math.sin(((x + phase) / 600) * Math.PI));
    pts.push(`${x === 0 ? "M" : "L"}${x},${y.toFixed(1)}`);
  }
  return pts.join(" ");
}

function Robot() {
  return (
    <svg className="robot" viewBox="0 0 320 300" role="img" aria-label="AI assistant">
      <defs>
        <linearGradient id="rb-skin" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e6fbff" />
          <stop offset=".35" stopColor="#8fe3ff" />
          <stop offset="1" stopColor="#2a7bd6" />
        </linearGradient>
        <linearGradient id="rb-skin-side" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#3a8fe0" />
          <stop offset=".5" stopColor="#a8ecff" />
          <stop offset="1" stopColor="#3a8fe0" />
        </linearGradient>
        <linearGradient id="rb-dark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1d2b44" />
          <stop offset="1" stopColor="#0b1222" />
        </linearGradient>
        <radialGradient id="rb-halo" cx=".5" cy=".45" r=".5">
          <stop offset="0" stopColor="#5fe1ff" stopOpacity=".55" />
          <stop offset=".6" stopColor="#3a7bff" stopOpacity=".12" />
          <stop offset="1" stopColor="#3a7bff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="rb-eye" x1="0" x2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#7af0ff" />
        </linearGradient>
      </defs>

      <ellipse cx="160" cy="130" rx="150" ry="130" fill="url(#rb-halo)" className="rb-halo" />

      {/* shoulders and chest */}
      <g className="rb-body">
        <path d="M20 300 C 26 250 60 226 112 218 L 208 218 C 260 226 294 250 300 300 Z" fill="url(#rb-skin)" opacity=".95" />
        <path d="M70 300 C 74 262 96 240 128 234 L 192 234 C 224 240 246 262 250 300 Z" fill="#cdf6ff" opacity=".35" />
        <path d="M40 262 C 52 246 70 238 92 234" stroke="#0e2a4a" strokeWidth="3" fill="none" opacity=".5" />
        <path d="M280 262 C 268 246 250 238 228 234" stroke="#0e2a4a" strokeWidth="3" fill="none" opacity=".5" />
        <rect x="64" y="244" width="22" height="40" rx="6" fill="url(#rb-dark)" />
        <rect x="234" y="244" width="22" height="40" rx="6" fill="url(#rb-dark)" />
        <path d="M160 236 L160 300" stroke="#0e2a4a" strokeWidth="3" opacity=".55" />
        <path d="M136 250 L160 262 L184 250" stroke="#0e2a4a" strokeWidth="2.5" fill="none" opacity=".55" />
        <circle cx="160" cy="276" r="6" className="rb-core" />
      </g>

      {/* neck: dark joint with glowing cables */}
      <g className="rb-neck">
        <rect x="132" y="178" width="56" height="46" rx="10" fill="url(#rb-dark)" />
        {[140, 152, 164, 176].map((x, i) => (
          <rect key={x} x={x} y="182" width="5" height="38" rx="2.5" fill="#46d9ff" opacity={0.5 + (i % 2) * 0.3} className="rb-cable" style={{ animationDelay: `${i * 0.25}s` }} />
        ))}
        <rect x="124" y="208" width="72" height="12" rx="6" fill="#16223a" />
      </g>

      {/* head */}
      <g className="rb-head">
        <rect x="88" y="78" width="20" height="46" rx="8" fill="url(#rb-dark)" />
        <rect x="212" y="78" width="20" height="46" rx="8" fill="url(#rb-dark)" />
        <circle cx="98" cy="90" r="3" className="rb-led" />
        <circle cx="222" cy="90" r="3" className="rb-led" style={{ animationDelay: ".6s" }} />
        <path d="M160 14 C 214 14 228 56 226 104 C 224 150 200 190 160 192 C 120 190 96 150 94 104 C 92 56 106 14 160 14 Z" fill="url(#rb-skin)" />
        <path d="M160 14 C 214 14 228 56 226 104 C 225 128 218 150 206 166 C 214 140 214 70 160 30 Z" fill="url(#rb-skin-side)" opacity=".35" />
        {/* face plate */}
        <path d="M160 52 C 196 52 206 80 205 110 C 203 146 186 174 160 176 C 134 174 117 146 115 110 C 114 80 124 52 160 52 Z" fill="#dff9ff" opacity=".55" />
        <path d="M118 70 C 140 60 180 60 202 70" stroke="#2a6fb8" strokeWidth="1.5" fill="none" opacity=".5" />
        <path d="M160 14 L160 48" stroke="#2a6fb8" strokeWidth="1.5" opacity=".35" />
        {/* brows */}
        <path d="M128 98 Q 141 92 152 98" stroke="#2a6fb8" strokeWidth="2" fill="none" opacity=".6" />
        <path d="M168 98 Q 179 92 192 98" stroke="#2a6fb8" strokeWidth="2" fill="none" opacity=".6" />
        {/* eyes */}
        <g className="rb-eyes">
          <path d="M128 112 Q 140 104 152 112 Q 140 118 128 112 Z" fill="url(#rb-eye)" className="rb-eye" />
          <path d="M168 112 Q 180 104 192 112 Q 180 118 168 112 Z" fill="url(#rb-eye)" className="rb-eye" />
          <circle cx="140" cy="111" r="2.6" fill="#0a5b9c" />
          <circle cx="180" cy="111" r="2.6" fill="#0a5b9c" />
        </g>
        {/* nose and mouth */}
        <path d="M160 116 L157 138 L163 138" stroke="#2a6fb8" strokeWidth="1.6" fill="none" opacity=".55" />
        <rect x="142" y="152" width="36" height="5" rx="2.5" className="rb-mouth" />
        {/* data dots across the face */}
        <g className="rb-data" fill="#2a8fe6">
          {Array.from({ length: 14 }, (_, i) => (
            <rect key={i} x={150 + (i % 7) * 5} y={66 + Math.floor(i / 7) * 6} width="2.5" height="2.5" opacity={0.25 + ((i * 7) % 5) / 8} />
          ))}
        </g>
      </g>
    </svg>
  );
}
