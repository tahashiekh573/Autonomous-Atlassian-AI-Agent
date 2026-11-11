import { useState } from "react";
import { api, setToken } from "../api";
import { errorText } from "../hooks";
import type { User } from "../types";
import { Icon, type IconName } from "./Icons";

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  { icon: "mic", title: "Speak or type", text: "English, Urdu or Roman Urdu, by voice or text." },
  { icon: "brain", title: "Eight cooperating agents", text: "Understand, plan, build, verify and report." },
  { icon: "shield", title: "You stay in control", text: "Review every plan; risky steps need approval." },
  { icon: "check", title: "Verified, not guessed", text: "Results are re-read from Jira, JSM and Confluence." },
];

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(email, password);
      setToken(result.access_token);
      onLogin(result.user);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login login-split">
      <section className="login-hero">
        <div className="brand-logo big" aria-hidden="true"><Icon name="bolt" size={26} /></div>
        <h1>Your Atlassian site,<br /><span className="grad-text">run by AI agents.</span></h1>
        <p>Describe a project, a service desk or a knowledge base. The agents plan it, you approve it, they build and verify it.</p>
        <ul className="features">
          {FEATURES.map((f, i) => (
            <li key={f.title} style={{ animationDelay: `${0.15 + i * 0.08}s` }}>
              <span className="feature-ico"><Icon name={f.icon} /></span>
              <span><b>{f.title}</b><small>{f.text}</small></span>
            </li>
          ))}
        </ul>
      </section>
      <form className="card stack login-card" onSubmit={submit}>
        <div><h2 className="login-title">Welcome back</h2><p className="muted" style={{ margin: 0 }}>Sign in to your admin console</p></div>
        <label>Email<input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password<input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <div className="alert err">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
