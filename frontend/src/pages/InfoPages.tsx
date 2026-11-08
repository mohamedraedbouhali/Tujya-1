import { useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { homePath, useAuth } from "../auth";
import { DISCLAIMER, SOURCES } from "../brand";
import { LanguageMenu, Logo, staggerIndex, ThemeToggle } from "../components";
import { SiteFooter, type FooterGroup } from "../Footer";
import { useT } from "../i18n";
import { Icon, type IconName } from "../icons";
import { useNavLayout } from "../layouts";

const PAGES: { to: string; icon: IconName; label: "about" | "privacy" | "help" }[] = [
  { to: "/about", icon: "book", label: "about" },
  { to: "/privacy", icon: "lock", label: "privacy" },
  { to: "/help", icon: "help", label: "help" },
];

/** About, Privacy and Help: open to everyone, signed in or not. */
export function InfoLayout() {
  const { user } = useAuth();
  const location = useLocation();
  const t = useT();
  const bar = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLElement>(null);
  const layout = useNavLayout(bar, menu, user?.id);
  const footer: FooterGroup[] = user
    ? [
        {
          title: t.footer.tools,
          links: [
            { to: "/scan", label: t.shell.scanner },
            { to: "/reports", label: t.shell.reports },
            { to: "/toxicity", label: t.shell.toxicity },
          ],
        },
        { title: t.footer.account, links: [{ to: homePath(user), label: t.info.openApp }] },
      ]
    : [
        {
          title: t.footer.explore,
          // Plain links: a full load of "/" lets the browser scroll to the section.
          links: [
            { href: "/#how", label: t.intro.linkHow },
            { href: "/#features", label: t.intro.linkFeatures },
            { href: "/#safety", label: t.intro.linkSafety },
            { href: "/#sources", label: t.intro.linkData },
          ],
        },
        {
          title: t.footer.account,
          links: [
            { to: "/login", label: t.common.signIn },
            { to: "/signup", label: t.intro.createAccount },
          ],
        },
      ];

  return (
    <div className="shell">
      <header className="topbar">
        <div className={`topbar-inner nav-${layout}`} ref={bar}>
          <Link className="brand" to={user ? homePath(user) : "/"}>
            <Logo height={52} />
          </Link>
          <nav className="nav" aria-label={t.footer.info} ref={menu}>
            {PAGES.map((page) => (
              <NavLink key={page.to} to={page.to} className="nav-link">
                <Icon name={page.icon} />
                {t.shell[page.label]}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-actions">
            <LanguageMenu />
            <ThemeToggle />
            <Link className="btn btn-primary btn-sm" to={user ? homePath(user) : "/login"}>
              {user ? t.info.openApp : t.common.signIn}
            </Link>
          </div>
        </div>
      </header>
      <main className="page info-page">
        <div className="page-enter" key={location.pathname}>
          <Outlet />
        </div>
      </main>
      <SiteFooter groups={footer} />
    </div>
  );
}

function InfoHeader({ icon, title, lead }: { icon: IconName; title: string; lead: string }) {
  return (
    <header className="info-head">
      <span className="page-icon">
        <Icon name={icon} size={24} />
      </span>
      <h1>{title}</h1>
      <p className="info-lead">{lead}</p>
    </header>
  );
}

export function AboutPage() {
  const t = useT();
  return (
    <>
      <InfoHeader icon="book" title={t.info.aboutTitle} lead={t.info.aboutLead} />
      <div className="info-grid">
        {t.info.aboutSections.map((section, index) => (
          <section key={section.title} className="card info-card" style={staggerIndex(index)}>
            <h2>{section.title}</h2>
            <p>{section.text}</p>
          </section>
        ))}
      </div>
      <h2 className="section-title">{t.info.sourcesTitle}</h2>
      <ul className="info-sources">
        {SOURCES.map((source, index) => (
          <li key={source.name} className="card">
            <span className="info-source-icon">
              <Icon name="database" size={18} />
            </span>
            <div>
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.name}
                <Icon name="external" size={13} />
              </a>
              <span className="cell-sub">{t.intro.sourceGives[index]}</span>
            </div>
            <em>{source.licence ?? t.intro.nlmTerms}</em>
          </li>
        ))}
      </ul>
      <p className="disclaimer" lang="fr">
        <Icon name="shield" size={16} />
        {DISCLAIMER}
      </p>
    </>
  );
}

export function PrivacyPage() {
  const t = useT();
  return (
    <>
      <InfoHeader icon="lock" title={t.info.privacyTitle} lead={t.info.privacyLead} />
      <div className="info-stack">
        {t.info.privacySections.map((section, index) => (
          <section key={section.title} className="card info-card" style={staggerIndex(index)}>
            <h2>{section.title}</h2>
            <ul className="info-list">
              {section.items.map((item) => (
                <li key={item}>
                  <span className="info-dot" aria-hidden="true" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}

export function HelpPage() {
  const t = useT();
  return (
    <>
      <InfoHeader icon="help" title={t.info.helpTitle} lead={t.info.helpLead} />
      <div className="faq">
        {t.info.faq.map((item, index) => (
          <details key={item.q} className="card faq-item" open={index === 0}>
            <summary>
              {item.q}
              <Icon name="chevron" size={18} />
            </summary>
            <p>{item.a}</p>
          </details>
        ))}
      </div>
      <p className="muted info-more">
        <Icon name="help" size={16} /> {t.info.stillStuck}
      </p>
      <p className="disclaimer" lang="fr">
        <Icon name="shield" size={16} />
        {DISCLAIMER}
      </p>
    </>
  );
}
