import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { errorMessage, type User } from "../api";
import { homePath, useAuth } from "../auth";
import { APP_NAME, DISCLAIMER, FACTS } from "../brand";
import {
  Alert,
  LanguageMenu,
  Logo,
  PasswordStrength,
  Spinner,
  SubmitButton,
  TextField,
  ThemeToggle,
} from "../components";
import { FloatCards, parallax } from "../FloatCards";
import { useT } from "../i18n";
import { CountUp } from "../motion";
import { Scene3D } from "../Scene3D";

const MIN_PASSWORD_LENGTH = 8;

/** Go back to the page that asked for a sign-in, but only inside the user's own area. */
function destination(user: User, from: unknown): string {
  const home = homePath(user);
  if (typeof from !== "string") return home;
  const adminArea = from.startsWith("/admin");
  return adminArea === (user.role === "admin") ? from : home;
}

export default function AuthPage({ mode }: { mode: "signin" | "signup" }) {
  const { user, ready, signIn, signUp } = useAuth();
  const location = useLocation();
  const t = useT();
  const from = (location.state as { from?: unknown } | null)?.from;

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signingUp = mode === "signup";

  useEffect(() => {
    setError(null);
    setPassword("");
    setConfirm("");
  }, [mode]);

  if (!ready) return <Spinner label={t.common.checkingSession} />;
  // Also what moves the user on after a successful sign-in or sign-up.
  if (user) return <Navigate to={destination(user, from)} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (signingUp && password !== confirm) {
      setError(t.auth.mismatch);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (signingUp) {
        await signUp({ email, full_name: fullName, password });
      } else {
        await signIn(email, password);
      }
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  };

  const facts = [
    { value: FACTS.pills, label: t.auth.factPills },
    { value: FACTS.ingredients, label: t.auth.factIngredients },
    { value: FACTS.interactions, label: t.auth.factPairs },
  ];

  return (
    <div className="auth">
      <aside className="auth-aside" onPointerMove={parallax}>
        <span className="aurora aurora-1" aria-hidden="true" />
        <span className="aurora aurora-2" aria-hidden="true" />
        <span className="lp-grid-lines" aria-hidden="true" />
        <p className="eyebrow">{t.auth.eyebrow}</p>
        <div className="auth-aside-body">
          <div className="auth-visual">
            <Scene3D variant="compact" className="auth-scene" />
            <FloatCards variant="auth" />
          </div>
          <h1>
            {t.auth.title1}
            <span className="text-gradient shimmer"> {t.auth.title2}</span>
          </h1>
          <p>{t.auth.lead}</p>
          <ul className="auth-facts">
            {facts.map((fact) => (
              <li key={fact.label}>
                <strong>
                  <CountUp value={fact.value} duration={1400} />
                </strong>
                {fact.label}
              </li>
            ))}
          </ul>
        </div>
        <p className="auth-footnote">{DISCLAIMER}</p>
      </aside>

      <main className="auth-main">
        <div className="auth-bg" aria-hidden="true">
          <span />
          <span />
        </div>
        <div className="auth-corner">
          <LanguageMenu />
          <ThemeToggle className="auth-theme-toggle" />
        </div>
        <div className="auth-column">
          <Link to="/" className="auth-logo" title={t.auth.about(APP_NAME)}>
            <Logo height={96} />
          </Link>

          <div className="auth-card">
            <h2>{signingUp ? t.auth.titleSignUp : t.auth.titleSignIn}</h2>
            <p className="muted">{signingUp ? t.auth.subSignUp : t.auth.subSignIn}</p>

            <nav className="tabs" data-mode={mode} aria-label={t.auth.tabs}>
              <Link
                to="/login"
                state={location.state}
                aria-current={signingUp ? undefined : "page"}
                className={signingUp ? "tab" : "tab tab-active"}
              >
                {t.common.signIn}
              </Link>
              <Link
                to="/signup"
                state={location.state}
                aria-current={signingUp ? "page" : undefined}
                className={signingUp ? "tab tab-active" : "tab"}
              >
                {t.common.signUp}
              </Link>
            </nav>

            <form onSubmit={submit} className="form">
              {error && <Alert>{error}</Alert>}
              {/* Sign-up puts its fields two by two, so the page fits the screen. */}
              <div className={signingUp ? "field-row" : "field-stack"}>
                {signingUp && (
                  <div className="field-enter">
                    <TextField
                      label={t.common.fullName}
                      value={fullName}
                      onChange={setFullName}
                      autoComplete="name"
                      maxLength={120}
                      required
                      autoFocus
                    />
                  </div>
                )}
                <TextField
                  label={t.common.email}
                  type="email"
                  value={email}
                  onChange={setEmail}
                  autoComplete={signingUp ? "email" : "username"}
                  placeholder={t.auth.emailPlaceholder}
                  required
                  autoFocus={!signingUp}
                />
              </div>
              <div className={signingUp ? "field-row" : "field-stack"}>
                <TextField
                  label={t.common.password}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={setPassword}
                  autoComplete={signingUp ? "new-password" : "current-password"}
                  minLength={signingUp ? MIN_PASSWORD_LENGTH : undefined}
                  maxLength={128}
                  placeholder={signingUp ? t.auth.passwordPlaceholder(MIN_PASSWORD_LENGTH) : undefined}
                  required
                />
                {signingUp && (
                  <div className="field-enter">
                    <TextField
                      label={t.auth.confirmPassword}
                      type={showPassword ? "text" : "password"}
                      value={confirm}
                      onChange={setConfirm}
                      autoComplete="new-password"
                      maxLength={128}
                      required
                    />
                  </div>
                )}
              </div>
              {signingUp && <PasswordStrength password={password} minLength={MIN_PASSWORD_LENGTH} />}
              <label className="check">
                <input
                  type="checkbox"
                  checked={showPassword}
                  onChange={(event) => setShowPassword(event.target.checked)}
                />
                {t.auth.showPassword}
              </label>
              <SubmitButton busy={busy} className="btn btn-primary btn-lg btn-block">
                {signingUp ? t.auth.createAccount : t.common.signIn}
              </SubmitButton>
            </form>

            <p className="auth-switch muted">
              {signingUp ? t.auth.haveAccount : t.auth.newHere}
              <Link to={signingUp ? "/login" : "/signup"} state={location.state}>
                {signingUp ? t.common.signIn : t.auth.createAnAccount}
              </Link>
              {/* What an account keeps, before creating one (D83). Same line: no extra height. */}
              {signingUp && (
                <>
                  {" · "}
                  <Link to="/privacy">{t.shell.privacy}</Link>
                </>
              )}
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
