import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { api, type AdminStats } from "../../api";
import { useAuth } from "../../auth";
import { APP_NAME } from "../../brand";
import {
  Alert,
  Avatar,
  Badge,
  formatDate,
  greeting,
  StatTile,
  staggerIndex,
  TableSkeleton,
} from "../../components";
import { useQuery } from "../../hooks";
import { useT } from "../../i18n";
import { Icon, type IconName } from "../../icons";
import { ActivityList } from "./activityView";

// Labels and notes are in the locale files (dashboard.tiles), keyed the same way.
const TILES: { key: keyof AdminStats; icon: IconName }[] = [
  { key: "users_total", icon: "users" },
  { key: "users_active", icon: "check" },
  { key: "users_inactive", icon: "ban" },
  { key: "admins", icon: "shield" },
  { key: "signups_last_7_days", icon: "spark" },
  { key: "active_sessions", icon: "clock" },
];

/** Share of accounts that can sign in, as a bar that fills when the numbers arrive. */
function AccessMeter({ stats }: { stats: AdminStats }) {
  const t = useT();
  const share = stats.users_total ? Math.round((stats.users_active / stats.users_total) * 100) : 0;
  return (
    <div className="card meter-card">
      <div className="meter-head">
        <h2>{t.dashboard.accessTitle}</h2>
        <strong>{t.dashboard.activeShare(share)}</strong>
      </div>
      <div
        className="meter"
        role="img"
        aria-label={t.dashboard.meterLabel(stats.users_active, stats.users_total)}
      >
        <span style={{ "--w": `${share}%` } as CSSProperties} />
      </div>
      <p className="meter-legend muted">
        <span>
          <i className="dot dot-active" /> {t.dashboard.activeCount(stats.users_active)}
        </span>
        <span>
          <i className="dot dot-inactive" /> {t.dashboard.deactivatedCount(stats.users_inactive)}
        </span>
      </p>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const t = useT();
  const stats = useQuery((signal) => api.admin.stats(signal), []);
  const recent = useQuery((signal) => api.admin.users({ page_size: 5 }, signal), []);
  const activity = useQuery((signal) => api.admin.activity({ page_size: 6 }, signal), []);
  const firstName = user?.full_name.split(/\s+/)[0] ?? "";

  return (
    <>
      <section className="banner banner-admin">
        <div className="orbs" aria-hidden="true">
          <span />
          <span />
        </div>
        <div className="banner-copy">
          <p className="eyebrow">{t.dashboard.eyebrow}</p>
          <h1>{t.dashboard.title}</h1>
          <p>{t.dashboard.intro(greeting(), firstName, APP_NAME)}</p>
          <div className="banner-actions">
            <Link className="btn btn-light" to="/admin/users">
              <Icon name="users" />
              {t.dashboard.manageUsers}
            </Link>
            <Link className="btn btn-on-dark" to="/home">
              <Icon name="eye" />
              {t.dashboard.viewApp}
            </Link>
          </div>
        </div>
      </section>

      {stats.error && <Alert>{stats.error}</Alert>}
      <section aria-label={t.dashboard.numbersLabel} className="stat-grid stat-grid-3">
        {TILES.map((tile) => (
          <StatTile
            key={tile.key}
            icon={tile.icon}
            label={t.dashboard.tiles[tile.key].label}
            note={t.dashboard.tiles[tile.key].note}
            value={stats.data?.[tile.key]}
            loading={!stats.data && stats.loading}
          />
        ))}
      </section>

      {stats.data && <AccessMeter stats={stats.data} />}

      <div className="section-head">
        <h2 className="section-title">{t.dashboard.recentTitle}</h2>
        <Link className="section-link" to="/admin/activity">
          {t.dashboard.seeAll}
          <Icon name="arrow" size={16} />
        </Link>
      </div>
      {activity.error && <Alert>{activity.error}</Alert>}
      {!activity.data && activity.loading && <TableSkeleton rows={4} />}
      {activity.data && (
        <div className="card table-card activity-card">
          {activity.data.items.length ? (
            <ActivityList events={activity.data.items} />
          ) : (
            <p className="empty">{t.dashboard.noActivity}</p>
          )}
        </div>
      )}

      <h2 className="section-title">{t.dashboard.newest}</h2>
      {recent.error && <Alert>{recent.error}</Alert>}
      {!recent.data && recent.loading && <TableSkeleton rows={5} />}
      {recent.data && (
        <div className="card table-card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t.table.user}</th>
                  <th>{t.table.role}</th>
                  <th>{t.table.status}</th>
                  <th>{t.table.created}</th>
                  <th>{t.table.lastSignIn}</th>
                </tr>
              </thead>
              <tbody>
                {recent.data.items.map((account, index) => (
                  <tr key={account.id} className="row-enter" style={staggerIndex(index)}>
                    <td>
                      <div className="cell-user">
                        <Avatar name={account.full_name} src={account.photo_url} size="sm" />
                        <div>
                          <span className="cell-title">{account.full_name}</span>
                          <span className="cell-sub">{account.email}</span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <Badge tone={account.role}>{t.roles[account.role]}</Badge>
                    </td>
                    <td>
                      <Badge tone={account.is_active ? "active" : "inactive"}>
                        {account.is_active ? t.common.active : t.common.deactivated}
                      </Badge>
                    </td>
                    <td>{formatDate(account.created_at)}</td>
                    <td>{formatDate(account.last_login_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
