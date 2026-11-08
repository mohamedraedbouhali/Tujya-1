import { Link } from "react-router-dom";
import type { ActivityAction, ActivityEvent } from "../../api";
import { formatDate, getLang, useT, type Messages } from "../../i18n";
import { Icon, type IconName } from "../../icons";

/** The filters of the Activity page: each kind is a group of actions. */
export const KINDS = {
  access: ["sign_up", "sign_in", "sign_in_failed", "sign_in_blocked", "sign_out"],
  scan: ["scan"],
  interactions: ["interactions"],
  chat: ["chat"],
  toxicity: ["toxicity"],
  reports: ["report_create", "report_share", "report_unshare", "report_delete"],
  account: [
    "profile_update",
    "photo_update",
    "photo_delete",
    "signature_update",
    "signature_delete",
    "password_change",
  ],
  admin: ["user_create", "user_update", "password_reset", "user_delete", "data_export"],
} satisfies Record<string, ActivityAction[]>;

export type Kind = keyof typeof KINDS;
export const KIND_NAMES = Object.keys(KINDS) as Kind[];

export function kindLabel(t: Messages, kind: Kind): string {
  const labels: Record<Kind, string> = {
    access: t.activity.kindAccess,
    scan: t.activity.kindScan,
    interactions: t.activity.kindInteractions,
    chat: t.activity.kindChat,
    toxicity: t.activity.kindToxicity,
    reports: t.activity.kindReports,
    account: t.activity.kindAccount,
    admin: t.activity.kindAdmin,
  };
  return labels[kind];
}

function kindOf(action: ActivityAction): Kind {
  return KIND_NAMES.find((kind) => (KINDS[kind] as ActivityAction[]).includes(action)) ?? "account";
}

const ICONS: Record<ActivityAction, IconName> = {
  sign_up: "plus",
  sign_in: "login",
  sign_in_failed: "alert",
  sign_in_blocked: "ban",
  sign_out: "logout",
  scan: "scan",
  interactions: "shield",
  chat: "chat",
  toxicity: "flask",
  profile_update: "pen",
  photo_update: "camera",
  photo_delete: "camera",
  signature_update: "pen",
  signature_delete: "pen",
  password_change: "lock",
  user_create: "plus",
  user_update: "users",
  password_reset: "lock",
  user_delete: "trash",
  report_create: "file",
  report_share: "share",
  report_unshare: "share",
  report_delete: "trash",
  data_export: "download",
};

/** One sentence for an event, in the interface language. Counts only, never a medicine. */
export function describe(t: Messages, event: ActivityEvent): string {
  const a = t.activity;
  const d = event.details;
  const target = d.name ?? `#${event.target_id ?? "?"}`;
  const email = d.email ?? "";
  switch (event.action) {
    case "sign_up":
      return a.signUp;
    case "sign_in":
      return a.signIn;
    case "sign_in_failed":
      return a.signInFailed;
    case "sign_in_blocked":
      return a.signInBlocked;
    case "sign_out":
      return a.signOut;
    case "scan":
      return a.scan(d.pills ?? 0);
    case "interactions":
      return a.interactions(d.items ?? 0);
    case "chat":
      return d.pills ? a.chatAbout(d.pills) : a.chat;
    case "toxicity":
      return a.toxicity(d.molecules ?? 1);
    case "profile_update": {
      const names: Record<string, string> = {
        name: a.fieldName,
        email: a.fieldEmail,
        phone: a.fieldPhone,
      };
      return a.profileUpdate((d.fields ?? []).map((field) => names[field] ?? field).join(", "));
    }
    case "photo_update":
      return a.photoUpdate;
    case "photo_delete":
      return a.photoDelete;
    case "signature_update":
      return a.signatureUpdate;
    case "signature_delete":
      return a.signatureDelete;
    case "password_change":
      return a.passwordChange;
    case "user_create": {
      const extras = [
        d.role === "admin" ? a.changeRole(t.roles.admin) : null,
        d.active === false ? a.changeDeactivated : null,
      ].filter(Boolean);
      const text = a.userCreate(target, email);
      return extras.length ? `${text} · ${extras.join(", ")}` : text;
    }
    case "user_update": {
      const changes = d.changes ?? {};
      const parts = [
        changes.name ? a.fieldName : null,
        changes.email ? a.fieldEmail : null,
        changes.role ? a.changeRole(t.roles[changes.role]) : null,
        changes.active === false ? a.changeDeactivated : null,
        changes.active === true ? a.changeReactivated : null,
      ].filter(Boolean);
      return a.userUpdate(target, parts.join(", "));
    }
    case "password_reset":
      return a.passwordReset(target);
    case "user_delete":
      return a.userDelete(target, email);
    case "report_create":
      return a.reportCreate(d.items ?? 0, d.answers ?? 0);
    case "report_share":
      return a.reportShare(d.days ?? 0);
    case "report_unshare":
      return a.reportUnshare;
    case "report_delete":
      return a.reportDelete;
    case "data_export":
      return d.table === "users" ? a.exportUsers(d.rows ?? 0) : a.exportActivity(d.rows ?? 0);
  }
}

/** "Chrome · Windows" from a user agent; null when it says nothing recognisable. */
export function device(userAgent: string | null): string | null {
  if (!userAgent) return null;
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /OPR\/|Opera/.test(userAgent)
      ? "Opera"
      : /Firefox\//.test(userAgent)
        ? "Firefox"
        : /Chrome\//.test(userAgent)
          ? "Chrome"
          : /Safari\//.test(userAgent)
            ? "Safari"
            : null;
  const system = /Windows/.test(userAgent)
    ? "Windows"
    : /iPhone|iPad|iPod/.test(userAgent)
      ? "iOS"
      : /Android/.test(userAgent)
        ? "Android"
        : /Mac OS X|Macintosh/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : null;
  if (!browser && !system) return null;
  return [browser, system].filter(Boolean).join(" · ");
}

function dayLabel(t: Messages, iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return t.activity.today;
  if (date.toDateString() === yesterday.toDateString()) return t.activity.yesterday;
  return date.toLocaleDateString(getLang(), {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

/** The events grouped by day, newest first, each with who, what, when and from where. */
export function ActivityList({ events }: { events: ActivityEvent[] }) {
  const t = useT();
  const days: { label: string; events: ActivityEvent[] }[] = [];
  for (const event of events) {
    const label = dayLabel(t, event.created_at);
    const last = days.at(-1);
    if (last?.label === label) last.events.push(event);
    else days.push({ label, events: [event] });
  }

  return (
    <div className="activity-days">
      {days.map((day) => (
        <section key={day.label} className="activity-day">
          <h3 className="activity-day-title">{day.label}</h3>
          <ul className="activity-list">
            {day.events.map((event) => {
              const warn = event.action === "sign_in_failed" || event.action === "sign_in_blocked";
              const tone = warn ? "warn" : kindOf(event.action);
              const time = new Date(event.created_at).toLocaleTimeString(getLang(), {
                hour: "2-digit",
                minute: "2-digit",
              });
              return (
                <li key={event.id} className={`activity-item activity-${tone}`}>
                  <span className="activity-icon" aria-hidden="true">
                    <Icon name={ICONS[event.action]} size={17} />
                  </span>
                  <div className="activity-body">
                    <p className="activity-text">
                      <Link
                        to={`/admin/activity?user=${event.user.id}`}
                        className="activity-user"
                        title={t.activity.showUser(event.user.full_name)}
                      >
                        {event.user.full_name}
                      </Link>
                      <span className="activity-what">{describe(t, event)}</span>
                    </p>
                    <p className="activity-meta">
                      <time dateTime={event.created_at} title={formatDate(event.created_at, true)}>
                        {time}
                      </time>
                      <span>{device(event.user_agent) ?? t.activity.unknownDevice}</span>
                      {event.ip && <span>{event.ip}</span>}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
