import { Link } from "react-router-dom";
import { api } from "../api";
import { APP_NAME } from "../brand";
import { Alert, formatDate, LanguageMenu, Logo, Spinner, ThemeToggle } from "../components";
import { useQuery } from "../hooks";
import { useT } from "../i18n";
import { Icon } from "../icons";
import { ReportDocument } from "../ReportDocument";

/**
 * A report opened from its share link (/shared#<token>), read only, without signing in.
 * The token is read from the part after the #, which browsers never send to a server.
 */
export default function SharedReportPage() {
  const t = useT();
  const token = window.location.hash.slice(1);
  const report = useQuery(
    (signal) => (token ? api.shared(token, signal) : Promise.reject(new Error(t.shared.noToken))),
    [token],
  );

  return (
    <div className="shell shared-shell">
      <header className="topbar no-print">
        <div className="topbar-inner">
          <Link className="brand" to="/">
            <Logo height={46} />
          </Link>
          <span className="shared-title">
            <Icon name="eye" size={17} />
            {t.shared.title}
          </span>
          <div className="topbar-actions">
            <LanguageMenu />
            <ThemeToggle />
            {report.data && (
              <button type="button" className="btn btn-primary btn-sm" onClick={() => window.print()}>
                <Icon name="print" size={16} />
                {t.report.print}
              </button>
            )}
          </div>
        </div>
      </header>
      <main className="page">
        {!report.data && report.loading && <Spinner label={t.shared.loading} />}
        {report.error && (
          <div className="card empty-card">
            <Icon name="ban" size={32} />
            <h1>{t.shared.failed}</h1>
            <Alert>{report.error}</Alert>
          </div>
        )}
        {report.data && (
          <>
            <p className="shared-note no-print">
              <Icon name="lock" size={15} />
              {t.shared.readOnly(formatDate(report.data.expires_at, true))}
            </p>
            <ReportDocument report={report.data} />
          </>
        )}
      </main>
      <footer className="shared-foot no-print">{t.shared.sharedFrom(APP_NAME)}</footer>
    </div>
  );
}
