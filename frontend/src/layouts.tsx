import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { errorMessage, type Role, type User } from "./api";
import { homePath, useAuth } from "./auth";
import { Alert, Avatar, LanguageMenu, Logo, Spinner, ThemeToggle } from "./components";
import { SiteFooter, type FooterGroup } from "./Footer";
import { useT } from "./i18n";
import { Icon, type IconName } from "./icons";

/** Gate for a group of routes: signed in, and (when `role` is given) with that role. */
export function RequireAuth({ role }: { role?: Role }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  const t = useT();

  if (!ready) return <Spinner label={t.common.checkingSession} />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (role && user.role !== role) return <Navigate to={homePath(user)} replace />;
  return <Outlet />;
}

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Match the path exactly, so "/admin" is not highlighted on "/admin/users". */
  end?: boolean;
}

export type NavLayout = "full" | "compact" | "stacked";

const width = (element: Element) => element.getBoundingClientRect().width;

/**
 * How the main menu fits beside the logo and the buttons of the top bar: on one row with its
 * icons, on one row without them, or on a row of its own. It depends on the language (French
 * and Russian labels are longer), the role (the Admin item) and the name in the account
 * button, so it is measured, not guessed from the window width. The widths used do not
 * depend on the layout chosen, so the choice never flips back and forth.
 */
export function useNavLayout(
  row: RefObject<HTMLElement | null>,
  nav: RefObject<HTMLElement | null>,
  watch: unknown,
): NavLayout {
  const [layout, setLayout] = useState<NavLayout>("full");

  useLayoutEffect(() => {
    const bar = row.current;
    const menu = nav.current;
    if (!bar || !menu) return;

    const measure = () => {
      const barStyle = getComputedStyle(bar);
      const others = [...bar.children].filter((child) => child !== menu);
      const room =
        bar.clientWidth -
        parseFloat(barStyle.paddingLeft) -
        parseFloat(barStyle.paddingRight) -
        others.reduce((sum, child) => sum + width(child), 0) -
        (parseFloat(barStyle.columnGap) || 0) * others.length;

      const links = [...menu.children];
      const gaps = (parseFloat(getComputedStyle(menu).columnGap) || 0) * Math.max(0, links.length - 1);
      let bare = gaps; // every label without its icon
      let icons = 0; // what the icons add
      for (const link of links) {
        const icon = link.querySelector("svg");
        const space = icon ? Number(icon.getAttribute("width")) + (parseFloat(getComputedStyle(link).columnGap) || 0) : 0;
        const shown = icon !== null && getComputedStyle(icon).display !== "none";
        bare += width(link) - (shown ? space : 0);
        icons += space;
      }
      // Half a pixel of slack for rounding.
      setLayout(bare + icons <= room + 0.5 ? "full" : bare <= room + 0.5 ? "compact" : "stacked");
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    // A label, the account name or a web font changes a width without resizing the bar.
    for (const child of [...bar.children, ...menu.children]) observer.observe(child);
    return () => observer.disconnect();
  }, [row, nav, watch]);

  return layout;
}

/** The avatar in the top bar: click it to open a small menu with the profile link and sign out. */
function UserMenu({
  user,
  profilePath,
  onSignOut,
}: {
  user: User;
  profilePath: string;
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const t = useT();
  const roleLabel = user.role === "admin" ? t.shell.administrator : t.shell.member;

  // While open, a click anywhere else or the Escape key closes it.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="user-menu-trigger"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={t.shell.accountMenu(user.full_name)}
        onClick={() => setOpen((value) => !value)}
      >
        <Avatar name={user.full_name} src={user.photo_url} />
        <span className="user-id">
          <span className="user-name">{user.full_name}</span>
          <span className="user-role">{roleLabel}</span>
        </span>
        <span className="user-menu-chevron">
          <Icon name="chevron" size={16} />
        </span>
      </button>

      {open && (
        <div className="user-menu-panel" id={panelId}>
          <div className="user-menu-head">
            <Avatar name={user.full_name} src={user.photo_url} size="sm" />
            <span className="user-menu-who">
              <span className="user-menu-name">{user.full_name}</span>
              <span className="user-menu-email" title={user.email}>
                {user.email}
              </span>
            </span>
          </div>
          <Link className="user-menu-item" to={profilePath} onClick={() => setOpen(false)}>
            <Icon name="user" size={17} />
            {t.shell.editProfile}
          </Link>
          <Link className="user-menu-item" to="/reports" onClick={() => setOpen(false)}>
            <Icon name="file" size={17} />
            {t.shell.reports}
          </Link>
          <div className="user-menu-sep" role="separator" />
          <button
            type="button"
            className="user-menu-item user-menu-item-danger"
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            <Icon name="logout" size={17} />
            {t.shell.signOut}
          </button>
        </div>
      )}
    </div>
  );
}

function AppShell({
  items,
  footer,
  admin = false,
}: {
  items: NavItem[];
  footer: FooterGroup[];
  admin?: boolean;
}) {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const t = useT();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLElement>(null);
  // Measured again when the items or the account change (each new element gets observed).
  const layout = useNavLayout(bar, menu, `${items.length}|${user?.id}`);
  if (!user) return null;

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (failure) {
      // Never let someone walk away from a shared computer believing they signed out.
      setSignOutError(t.shell.stillSignedIn(errorMessage(failure)));
    }
  };

  return (
    <div className={admin ? "shell shell-admin" : "shell"}>
      <header className="topbar">
        <div className={`topbar-inner nav-${layout}`} ref={bar}>
          <Link className="brand" to={admin ? "/admin" : "/home"}>
            <Logo height={52} />
            {admin && <span className="brand-tag">{t.shell.adminTag}</span>}
          </Link>
          <nav className="nav" aria-label={t.shell.mainNav} ref={menu}>
            {items.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">
                <Icon name={item.icon} />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-actions">
            <LanguageMenu />
            <ThemeToggle />
            <UserMenu
              user={user}
              profilePath={admin ? "/admin/account" : "/profile"}
              onSignOut={handleSignOut}
            />
          </div>
        </div>
      </header>
      <main className="page">
        {signOutError && <Alert>{signOutError}</Alert>}
        {/* Keyed by address, so every page plays its entrance when you navigate to it. */}
        <div className="page-enter" key={location.pathname}>
          <Outlet />
        </div>
      </main>
      <SiteFooter groups={footer} />
    </div>
  );
}

export function UserLayout() {
  const { user } = useAuth();
  const t = useT();
  const items: NavItem[] = [
    { to: "/home", label: t.shell.home, icon: "home" },
    { to: "/scan", label: t.shell.scanner, icon: "scan" },
    { to: "/reports", label: t.shell.reports, icon: "file" },
    { to: "/toxicity", label: t.shell.toxicity, icon: "flask" },
    { to: "/drugs", label: t.shell.drugs, icon: "pill" },
    { to: "/cell-lines", label: t.shell.cellLines, icon: "cells" },
  ];
  const account: FooterGroup["links"] = [
    { to: "/profile", label: t.shell.editProfile },
    { to: "/reports", label: t.shell.reports },
  ];
  if (user?.role === "admin") {
    items.push({ to: "/admin", label: t.shell.admin, icon: "shield" });
    account.push({ to: "/admin", label: t.shell.admin });
  }
  const footer: FooterGroup[] = [
    { title: t.footer.tools, links: items.filter((item) => item.to !== "/admin") },
    { title: t.footer.account, links: account },
  ];
  return <AppShell items={items} footer={footer} />;
}

export function AdminLayout() {
  const t = useT();
  return (
    <AppShell
      admin
      items={[
        { to: "/admin", label: t.shell.dashboard, icon: "grid", end: true },
        { to: "/admin/users", label: t.shell.users, icon: "users" },
        { to: "/admin/activity", label: t.shell.activity, icon: "activity" },
        { to: "/admin/reports", label: t.shell.adminReports, icon: "file" },
        { to: "/home", label: t.shell.viewApp, icon: "eye" },
      ]}
      footer={[
        {
          title: t.footer.administration,
          links: [
            { to: "/admin", label: t.shell.dashboard },
            { to: "/admin/users", label: t.shell.users },
            { to: "/admin/activity", label: t.shell.activity },
            { to: "/admin/reports", label: t.shell.adminReports },
          ],
        },
        {
          title: t.footer.account,
          links: [
            { to: "/admin/account", label: t.shell.editProfile },
            { to: "/home", label: t.shell.viewApp },
          ],
        },
      ]}
    />
  );
}
