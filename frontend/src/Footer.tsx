import { Link } from "react-router-dom";
import { APP_NAME, DISCLAIMER, SOURCES } from "./brand";
import { Logo } from "./components";
import { useT } from "./i18n";
import { Icon } from "./icons";

/** A footer link: a page of the app (`to`) or a place on the current page (`href`, "#how"). */
export interface FooterLink {
  label: string;
  to?: string;
  href?: string;
}

export interface FooterGroup {
  title: string;
  links: FooterLink[];
}

function scrollToTop() {
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
}

/**
 * The footer of every page: the logo, the link groups the page passes in, the data sources,
 * and the safety disclaimer. `landing` styles it for the always-dark start page.
 */
export function SiteFooter({ groups, landing = false }: { groups: FooterGroup[]; landing?: boolean }) {
  const t = useT();
  const year = new Date().getFullYear();

  return (
    <footer className={landing ? "site-footer site-footer-landing" : "site-footer"}>
      <div className="site-footer-inner">
        <div className="site-footer-grid">
          <div className="site-footer-brand">
            <Logo height={46} tone={landing ? "dark" : "auto"} />
            <p>{t.footer.tagline}</p>
          </div>

          {groups.map((group) => (
            <nav className="site-footer-group" aria-label={group.title} key={group.title}>
              <h2 className="site-footer-title">{group.title}</h2>
              <ul>
                {group.links.map((link) => (
                  <li key={link.label}>
                    {link.to ? <Link to={link.to}>{link.label}</Link> : <a href={link.href}>{link.label}</a>}
                  </li>
                ))}
              </ul>
            </nav>
          ))}

          <div className="site-footer-group">
            <h2 className="site-footer-title">{t.footer.sources}</h2>
            <ul>
              {SOURCES.map((source) => (
                <li key={source.name}>
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.name}
                    <Icon name="external" size={13} />
                    <span className="sr-only">{t.footer.newTab}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="site-footer-bottom">
          {/* Stays in French in every language (decision D53). */}
          <p className="site-footer-disclaimer" lang="fr">
            <Icon name="shield" size={15} />
            {DISCLAIMER}
          </p>
          <p className="site-footer-legal">{t.footer.rights(year, APP_NAME)}</p>
          <nav className="site-footer-pages" aria-label={t.footer.info}>
            <Link to="/about">{t.shell.about}</Link>
            <Link to="/privacy">{t.shell.privacy}</Link>
            <Link to="/help">{t.shell.help}</Link>
          </nav>
          <button type="button" className="site-footer-top" onClick={scrollToTop}>
            {t.footer.backToTop}
            <Icon name="up" size={15} />
          </button>
        </div>
      </div>
    </footer>
  );
}
