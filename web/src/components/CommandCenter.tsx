import { useState } from "react";
import { api } from "../api";
import { errorText, useLoad } from "../hooks";
import { ACTIVE, type Connection, type Role, type RunDetail } from "../types";
import { RunView } from "./RunView";
import { liveEnabled, liveTabOpen, openLiveSite, setLiveEnabled, useLiveFollow } from "../liveSite";
import { VoiceButton } from "./VoiceButton";
import { Icon, type IconName } from "./Icons";

const ORBIT: IconName[] = ["brain", "map", "jira", "lifebuoy", "book", "link", "check", "doc"];

const EXAMPLES = [
  "Create a Bank IT Service Desk project in JSM with incident and service request workflows, SLAs, queues and automation.",
  "Jira mein ek Scrum project banao, usmein Epic, Story, Bug aur Task issue types configure karo aur Scrum board create karo.",
  "Create a Confluence space for the Bank IT Service Desk and add IT policies, password reset guides and troubleshooting articles.",
  "JSM ke tamam incidents ka Jira dashboard banao aur SLA reports add karo.",
];

interface Props {
  connection: Connection | null;
  role: Role;
  runId: string | null;
  draft: string;
  setDraft: (text: string) => void;
  onRunId: (id: string | null) => void;
  speak: (text: string) => void;
}

const MAX_CHARS = 50000; // matches MAX_COMMAND_CHARS in app/schemas/run.py

export function CommandCenter({ connection, role, runId, draft, setDraft, onRunId, speak }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // bumping it restarts live polling
  const [liveOn, setLiveOn] = useState(liveEnabled());
  const [liveBlocked, setLiveBlocked] = useState(false);
  const { data: run, setData: setRun } = useLoad<RunDetail | null>(
    () => (runId ? api.run(runId) : Promise.resolve(null)),
    [runId, tick],
    (r) => !!r && ACTIVE.includes(r.status),
  );

  const site = connection?.site_url ?? null;
  const showing = useLiveFollow(liveOn ? run ?? null : null, site);
  const runActive = !!run && ACTIVE.includes(run.status);

  // Called from click handlers only: browsers allow opening a tab during a user gesture.
  function openLive() {
    if (!liveOn || !site) return;
    setLiveBlocked(!openLiveSite(`${site}/jira/your-work`));
  }

  const tooLong = draft.length > MAX_CHARS;
  const canRevise = run && ["needs_clarification", "blocked", "awaiting_approval"].includes(run.status);
  const disabled = !connection || busy || role === "viewer" || (!!run && ACTIVE.includes(run.status));

  async function submit(fn: () => Promise<RunDetail>) {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      setDraft("");
      onRunId(result.id);
      setRun(result);
      setTick((t) => t + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function send() {
    const text = draft.trim();
    if (!text || !connection) return;
    openLive();
    if (run && canRevise) void submit(() => api.clarify(run.id, text));
    else void submit(() => api.createRun(connection.id, text));
  }

  // Re-poll when an action (approve / clarify) moves the run back into an active state.
  function onRunChange(updated: RunDetail) {
    setRun(updated);
    setTick((t) => t + 1);
  }

  return (
    <div className="grid-cmd">
      <div className="card stack sticky glow-card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }} className="row"><span className="title-ico"><Icon name="spark" size={16} /></span>AI command</h2>
          {run && <button className="link" onClick={() => onRunId(null)}>New command</button>}
        </div>
        {!connection && <div className="alert warn">Connect and test an Atlassian site first (Settings).</div>}

        <div className="chat" aria-live="polite">
          {(run?.conversation ?? []).map((t, n) => (
            <div key={n} className={`bubble ${t.role}`}>{t.content}</div>
          ))}
          {!run && <div className="muted">Describe what to build in English, Urdu or Roman Urdu — by typing or with the microphone. You will review the plan before anything changes.</div>}
        </div>

        <label>
          <span className="sr-only" style={{ position: "absolute", left: -9999 }}>Command</span>
          <textarea
            value={draft}
            placeholder={canRevise ? "Answer or ask for changes to the plan…" : "e.g. Create a Scrum project for the mobile team with a board and two sprints"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); }}
            disabled={!connection || role === "viewer"}
          />
        </label>
        <div className="row">
          <VoiceButton
            disabled={disabled}
            onError={setError}
            onRecorded={(audio) => connection && void submit(() => api.voiceCommand(connection.id, audio))}
          />
          <button className="primary" onClick={send} disabled={disabled || !draft.trim() || tooLong}>
            {canRevise ? "Send reply" : "Plan it"}
          </button>
          <span className="small muted">Ctrl+Enter to send</span>
          <span className="small muted" style={{ marginLeft: "auto", color: tooLong ? "var(--err)" : undefined }}>
            {draft.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
          </span>
        </div>
        {error && <div className="alert err">{error}</div>}
        <label className="live-toggle">
          <input type="checkbox" checked={liveOn}
            onChange={(e) => { setLiveOn(e.target.checked); setLiveEnabled(e.target.checked); }} />
          <span>Watch it live on my site <span className="muted small">(opens your Atlassian site in a new tab and follows every change)</span></span>
        </label>
        {liveOn && run && (runActive || showing) && (
          <div className="live-bar" aria-live="polite">
            <span className={`pulse ${runActive ? "" : "idle"}`} aria-hidden="true" />
            <span className="live-text">
              {liveTabOpen()
                ? showing ? <>Showing on your site: <a href={showing} target="atlassian-live" rel="noreferrer">{showing.replace(/^https?:\/\/[^/]+/, "")}</a></> : "Your site is open in the live tab — changes appear there as each step finishes."
                : liveBlocked ? "Your browser blocked the live tab." : "Live tab is closed."}
            </span>
            {!liveTabOpen() && <button className="link" onClick={openLive}>Open live tab</button>}
          </div>
        )}
        {!run && (
          <div>
            <div className="small muted" style={{ marginBottom: 6 }}>Try:</div>
            <div className="chips">
              {EXAMPLES.map((e, i) => <button key={e} className="chip" style={{ animationDelay: `${i * 0.06}s` }} onClick={() => setDraft(e)}>{e.slice(0, 70)}…</button>)}
            </div>
          </div>
        )}
      </div>

      <div>
        {run ? <RunView run={run} role={role} onChange={onRunChange} speak={speak} onExecuteClick={openLive} /> : (
          <div className="card empty">
            <div className="orbit" aria-hidden="true">
              <div className="orbit-core"><Icon name="bolt" size={26} /></div>
              <div className="orbit-ring">
                {ORBIT.map((name, i) => (
                  <span key={name} className="orbit-node" style={{ "--i": i } as React.CSSProperties}><Icon name={name} size={16} /></span>
                ))}
              </div>
            </div>
            <b className="empty-title">Your agents are ready</b>
            <span>The execution plan, approvals, live agent status and the verified report appear here.</span>
          </div>
        )}
      </div>
    </div>
  );
}
