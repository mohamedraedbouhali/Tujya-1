import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, type ActivityPage, type User } from "../../api";
import { Alert, Avatar, Badge, formatDate, Pagination, TableSkeleton } from "../../components";
import { useDebounced, useQuery } from "../../hooks";
import { useT, type Messages } from "../../i18n";
import { Icon } from "../../icons";
import { ActivityList, KIND_NAMES, KINDS, kindLabel, type Kind } from "./activityView";

const PAGE_SIZE = 30;
const REFRESH_MS = 10_000;
const PERIODS = [1, 7, 30] as const;

function isKind(value: string | null): value is Kind {
  return value !== null && (KIND_NAMES as string[]).includes(value);
}

/** How many events of each kind, from the per-action counts of the page. */
function kindCount(counts: ActivityPage["counts"], kind: Kind): number {
  return KINDS[kind].reduce((total, action) => total + (counts[action] ?? 0), 0);
}

function periodLabel(t: Messages, days: number): string {
  if (days === 1) return t.activity.periodDay;
  return days === 7 ? t.activity.periodWeek : t.activity.periodMonth;
}

/** The account whose activity is shown, or a note when it no longer exists. */
function UserSummary({ userId, counts }: { userId: number; counts: ActivityPage["counts"] | null }) {
  const t = useT();
  const account = useQuery(async (signal): Promise<User | "deleted"> => {
    try {
      return await api.admin.user(userId, signal);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) return "deleted";
      throw failure;
    }
  }, [userId]);

  const total = counts ? Object.values(counts).reduce((sum, n) => sum + (n ?? 0), 0) : null;
  return (
    <section className="card activity-person">
      {account.error && <Alert>{account.error}</Alert>}
      {account.data === "deleted" && <Alert kind="info">{t.activity.deletedAccount}</Alert>}
      {account.data && account.data !== "deleted" && (
        <div className="activity-person-head">
          <Avatar name={account.data.full_name} src={account.data.photo_url} />
          <div className="activity-person-who">
            <strong>{account.data.full_name}</strong>
            <span className="muted">{account.data.email}</span>
          </div>
          <span className="badge-row">
            <Badge tone={account.data.role}>{t.roles[account.data.role]}</Badge>
            <Badge tone={account.data.is_active ? "active" : "inactive"}>
              {account.data.is_active ? t.common.active : t.common.deactivated}
            </Badge>
          </span>
          <span className="muted activity-person-last">
            {t.table.lastSignIn}: {formatDate(account.data.last_login_at, true)}
          </span>
        </div>
      )}
      {counts && total !== null && (
        <p className="activity-person-counts">
          <strong>{t.activity.events(total)}</strong>
          {KIND_NAMES.map((kind) => {
            const n = kindCount(counts, kind);
            return n ? (
              <span key={kind} className="activity-chip">
                {kindLabel(t, kind)} <b>{n}</b>
              </span>
            ) : null;
          })}
        </p>
      )}
    </section>
  );
}

export default function Activity() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const userParam = Number(params.get("user"));
  const userId = Number.isInteger(userParam) && userParam > 0 ? userParam : undefined;
  const kindParam = params.get("kind");
  const kind = isKind(kindParam) ? kindParam : undefined;
  const daysParam = Number(params.get("days"));
  const days = (PERIODS as readonly number[]).includes(daysParam) ? daysParam : undefined;

  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const q = useDebounced(search.trim());

  const events = useQuery(
    (signal) =>
      api.admin.activity(
        {
          user_id: userId,
          action: kind ? KINDS[kind] : undefined,
          q: userId ? undefined : q,
          days,
          page,
          page_size: PAGE_SIZE,
        },
        signal,
      ),
    [userId, kind, days, q, page],
  );

  // New events appear on their own while the first page is open and the tab is visible.
  const { reload } = events;
  useEffect(() => {
    if (!autoRefresh || page !== 1) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [autoRefresh, page, reload]);

  /** Change one filter in the address (so a view can be linked to) and go back to page 1. */
  const setFilter = (name: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
    setPage(1);
  };

  const counts = events.data?.counts ?? null;

  return (
    <>
      <header className="page-header">
        <div className="page-title">
          <span className="page-icon">
            <Icon name="activity" size={24} />
          </span>
          <div>
            <h1>{t.activity.title}</h1>
            <p className="muted">{t.activity.subtitle}</p>
          </div>
        </div>
        {userId && (
          <Link className="btn btn-secondary" to="/admin/activity">
            <Icon name="users" />
            {t.activity.allAccounts}
          </Link>
        )}
      </header>

      {userId && <UserSummary userId={userId} counts={counts} />}

      <div className="toolbar">
        {!userId && (
          <label className="search-box">
            <Icon name="search" />
            <input
              type="search"
              aria-label={t.activity.search}
              placeholder={t.activity.search}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
            />
          </label>
        )}
        <select
          aria-label={t.activity.filterKind}
          value={kind ?? ""}
          onChange={(event) => setFilter("kind", event.target.value || undefined)}
        >
          <option value="">{t.activity.kindAll}</option>
          {KIND_NAMES.map((name) => (
            <option key={name} value={name}>
              {kindLabel(t, name)}
              {counts ? ` (${kindCount(counts, name)})` : ""}
            </option>
          ))}
        </select>
        <select
          aria-label={t.activity.filterPeriod}
          value={days ?? ""}
          onChange={(event) => setFilter("days", event.target.value || undefined)}
        >
          <option value="">{t.activity.periodAll}</option>
          {PERIODS.map((period) => (
            <option key={period} value={period}>
              {periodLabel(t, period)}
            </option>
          ))}
        </select>
        <label className="check activity-refresh">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(event) => setAutoRefresh(event.target.checked)}
          />
          {autoRefresh && page === 1 && <span className="live-dot" aria-hidden="true" />}
          {t.activity.autoRefresh}
        </label>
      </div>

      {events.error && <Alert>{events.error}</Alert>}
      {!events.data && events.loading && <TableSkeleton rows={8} />}

      {events.data && (
        <div className="card table-card activity-card" aria-busy={events.loading}>
          {events.data.items.length === 0 ? (
            <p className="empty">{t.activity.empty}</p>
          ) : (
            <ActivityList events={events.data.items} />
          )}
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={events.data.total}
            onPage={setPage}
          />
        </div>
      )}
    </>
  );
}
