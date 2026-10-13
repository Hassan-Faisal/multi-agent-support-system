import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DemoAccount } from "../api/types";
import { useAuth } from "../auth";
import { Switchboard } from "../components/Switchboard";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [demos, setDemos] = useState<DemoAccount[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.demoAccounts().then(setDemos, () => setDemos([]));
  }, []);

  const signIn = async (e: string, p: string) => {
    setBusy(e);
    setError(null);
    try {
      const user = await login(e, p);
      navigate(user.role === "agent" ? "/console" : "/chat", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      setBusy(null);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void signIn(email, password);
  };

  return (
    <main className="login">
      <section className="login-intro">
        <p className="wordmark">Nimbus Help</p>
        <h1>Every question goes to the specialist who can answer it.</h1>
        <p className="lede">
          A front desk reads your message and connects you to billing, technical support or orders. If they need
          each other, they pass the conversation along. If you need a person, the human team takes it from there.
        </p>
        <div className="login-board">
          <Switchboard path={["desk", "billing", "orders"]} live={false} />
        </div>
      </section>

      <section className="login-panel" aria-labelledby="signin-title">
        <h2 id="signin-title">Sign in</h2>
        <form onSubmit={onSubmit} className="stack">
          <label>
            Email
            <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && (
            <p className="notice notice-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-ink" type="submit" disabled={busy !== null}>
            {busy === email ? "Signing in" : "Sign in"}
          </button>
        </form>

        {demos.length > 0 && (
          <>
            <h3 className="demo-title">Or try a demo account</h3>
            <ul className="demo-list">
              {demos.map((d) => (
                <li key={d.email}>
                  <button
                    type="button"
                    className="demo"
                    disabled={busy !== null}
                    onClick={() => void signIn(d.email, d.password)}
                  >
                    <span className="demo-name">
                      {d.display_name}
                      {d.role === "agent" && <span className="pill">Staff</span>}
                    </span>
                    <span className="demo-blurb">{busy === d.email ? "Signing in…" : d.blurb}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}
