import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, type Report, type ReportSummary } from "../api";
import {
  Alert,
  Badge,
  formatDate,
  Modal,
  Pagination,
  Spinner,
  staggerIndex,
  TableSkeleton,
} from "../components";
import { useQuery } from "../hooks";
import { useT } from "../i18n";
import { Icon } from "../icons";
import { reportReference, ReportDocument, SEVERITY_TONE, useReportTitle } from "../ReportDocument";

const SHARE_DAYS = [1, 3, 7, 14, 30];

/** The address a pharmacist opens. The token sits after the #: browsers never send it. */
export function shareUrl(token: string): string {
  return `${window.location.origin}/shared#${token}`;
}

function ConfirmDelete({ onCancel, onDone, id }: { onCancel: () => void; onDone: () => void; id: number }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.my.deleteReport(id);
      onDone();
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  };
  return (
    <Modal title={t.report.delete} onClose={onCancel}>
      <p>{t.reports.confirmDelete}</p>
      {error && <Alert>{error}</Alert>}
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t.common.cancel}
        </button>
        <button type="button" className="btn btn-danger" disabled={busy} onClick={remove}>
          {busy && <span className="btn-spinner" aria-hidden="true" />}
          {t.reports.delete}
        </button>
      </div>
    </Modal>
  );
}

function ShareState({ report }: { report: ReportSummary | Report }) {
  const t = useT();
  if (!report.share) return null;
  if (!report.share.active) return <Badge tone="neutral">{t.reports.linkExpired}</Badge>;
  return (
    <Badge tone="info">
      <Icon name="share" size={13} /> {t.reports.sharedUntil(formatDate(report.share.expires_at))}
    </Badge>
  );
}

/** "My reports": every saved check, newest first. */
export default function ReportsPage() {
  const t = useT();
  const titleOf = useReportTitle();
  const [page, setPage] = useState(1);
  const [deleting, setDeleting] = useState<number | null>(null);
  const list = useQuery((signal) => api.my.reports(page, signal), [page]);

  return (
    <>
      <header className="page-header">
        <div className="page-title">
          <span className="page-icon">
            <Icon name="file" size={24} />
          </span>
          <div>
            <h1>{t.reports.title}</h1>
            <p className="muted">{t.reports.subtitle}</p>
          </div>
        </div>
      </header>

      {list.error && <Alert>{list.error}</Alert>}
      {!list.data && list.loading && <TableSkeleton rows={4} />}
      {list.data && list.data.items.length === 0 && (
        <div className="card empty-card">
          <Icon name="file" size={32} />
          <p>{t.reports.empty}</p>
          <Link className="btn btn-primary" to="/scan">
            <Icon name="scan" size={16} />
            {t.reports.openScanner}
          </Link>
        </div>
      )}
      {list.data && list.data.items.length > 0 && (
        <>
          <ul className="report-list">
            {list.data.items.map((report, index) => (
              <li key={report.id} className="card report-item lift" style={staggerIndex(index)}>
                <Link className="report-item-main" to={`/reports/${report.id}`}>
                  <span className="report-item-icon">
                    <Icon name="file" size={20} />
                  </span>
                  <span className="report-item-text">
                    <strong>{titleOf(report)}</strong>
                    <span className="cell-sub">
                      <span className="report-ref">{reportReference(report)}</span>
                      {" · "}
                      {formatDate(report.created_at, true)}
                      {report.pill_names.length > 0 && ` · ${t.reports.medicines(report.pill_names.length)}`}
                      {report.chat_answers > 0 && ` · ${t.reports.answers(report.chat_answers)}`}
                    </span>
                    {report.pill_names.length > 0 && (
                      <span className="report-item-pills">{report.pill_names.join(" · ")}</span>
                    )}
                  </span>
                </Link>
                <span className="report-item-badges">
                  {report.highest_severity ? (
                    <Badge tone={SEVERITY_TONE[report.highest_severity]}>
                      {t.reports.withInteraction(report.pairs_with_interaction)}
                    </Badge>
                  ) : (
                    report.pill_names.length > 1 && <Badge tone="neutral">{t.reports.noInteraction}</Badge>
                  )}
                  <ShareState report={report} />
                </span>
                <span className="report-item-actions">
                  <Link className="btn btn-secondary btn-sm" to={`/reports/${report.id}`}>
                    {t.reports.open}
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost btn-ghost-danger btn-sm"
                    onClick={() => setDeleting(report.id)}
                  >
                    <Icon name="trash" size={15} />
                    <span className="sr-only">{titleOf(report)}</span>
                    {t.reports.delete}
                  </button>
                </span>
              </li>
            ))}
          </ul>
          {list.data.total > list.data.page_size && (
            <Pagination page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />
          )}
        </>
      )}

      {deleting !== null && (
        <ConfirmDelete
          id={deleting}
          onCancel={() => setDeleting(null)}
          onDone={() => {
            setDeleting(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function ShareDialog({
  report,
  onClose,
  onChanged,
}: {
  report: Report;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useT();
  const [days, setDays] = useState(7);
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const active = report.share?.active ?? false;

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.my.share(report.id, days);
      setLink(shareUrl(created.token));
      setCopied(false);
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      input.current?.select(); // no clipboard access: select it for Ctrl+C
    }
  };

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.my.stopSharing(report.id);
      setLink(null);
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t.report.shareTitle} onClose={onClose}>
      <p className="muted">{t.report.shareText}</p>
      {error && <Alert>{error}</Alert>}

      {link ? (
        <div className="share-link">
          <label className="field">
            <span>{t.report.linkLabel}</span>
            <span className="share-link-row">
              <input ref={input} type="text" readOnly value={link} onFocus={(e) => e.target.select()} />
              <button type="button" className="btn btn-primary" onClick={copy}>
                <Icon name={copied ? "tick" : "copy"} size={16} />
                {copied ? t.report.copied : t.report.copy}
              </button>
            </span>
          </label>
          <p className="hint">{t.report.linkOnce}</p>
        </div>
      ) : (
        <div className="field">
          <label htmlFor="share-days">{t.report.shareFor}</label>
          <span className="share-link-row">
            <select id="share-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {SHARE_DAYS.map((n) => (
                <option key={n} value={n}>
                  {t.report.days(n)}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={create}>
              {busy && <span className="btn-spinner" aria-hidden="true" />}
              <Icon name="link" size={16} />
              {active ? t.report.newLink : t.report.createLink}
            </button>
          </span>
        </div>
      )}

      {report.share?.active && (
        <div className="share-state">
          <p>
            <Icon name="share" size={15} />{" "}
            {t.report.sharedState(formatDate(report.share.expires_at, true), report.share.views)}
          </p>
          <button type="button" className="btn btn-ghost btn-ghost-danger btn-sm" disabled={busy} onClick={stop}>
            {t.report.stopSharing}
          </button>
        </div>
      )}
    </Modal>
  );
}

/** One report, as it prints. */
export function ReportPage() {
  const t = useT();
  const navigate = useNavigate();
  const id = Number(useParams().id);
  const report = useQuery((signal) => api.my.report(id, signal), [id]);
  const [sharing, setSharing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [stopped, setStopped] = useState(false);
  const data = report.data;

  const stop = async () => {
    try {
      await api.my.stopSharing(id);
      setStopped(true);
      report.reload();
    } catch {
      report.reload();
    }
  };

  return (
    <>
      <div className="rdoc-toolbar no-print">
        <Link className="btn btn-ghost btn-sm" to="/reports">
          <Icon name="arrow" size={16} />
          {t.report.back}
        </Link>
        {data && (
          <span className="rdoc-toolbar-actions">
            <button type="button" className="btn btn-primary" onClick={() => window.print()}>
              <Icon name="print" size={17} />
              {t.report.print}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setSharing(true)}>
              <Icon name="share" size={17} />
              {t.report.share}
            </button>
            <button type="button" className="btn btn-ghost btn-ghost-danger" onClick={() => setDeleting(true)}>
              <Icon name="trash" size={17} />
              {t.report.delete}
            </button>
          </span>
        )}
      </div>

      {report.error && <Alert>{report.error}</Alert>}
      {!data && report.loading && <Spinner label={t.report.loading} />}
      {data && (
        <>
          {stopped && !data.share && (
            <div className="no-print">
              <Alert kind="success">{t.report.stopped}</Alert>
            </div>
          )}
          {data.share && (
            <div className="rdoc-share-bar no-print">
              {data.share.active ? (
                <>
                  <span>
                    <Icon name="share" size={16} />
                    {t.report.sharedState(formatDate(data.share.expires_at, true), data.share.views)}
                  </span>
                  <button type="button" className="btn btn-ghost btn-ghost-danger btn-sm" onClick={stop}>
                    {t.report.stopSharing}
                  </button>
                </>
              ) : (
                <span>{t.report.expiredState}</span>
              )}
            </div>
          )}
          <ReportDocument report={data} owner />
        </>
      )}

      {sharing && data && (
        <ShareDialog report={data} onClose={() => setSharing(false)} onChanged={report.reload} />
      )}
      {deleting && (
        <ConfirmDelete id={id} onCancel={() => setDeleting(false)} onDone={() => navigate("/reports")} />
      )}
    </>
  );
}
