import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { APP_NAME, DISCLAIMER, FACTS } from "../brand";
import { greeting, staggerIndex } from "../components";
import { useT } from "../i18n";
import { Icon, type IconName } from "../icons";
import { CountUp } from "../motion";
import { Scene3D } from "../Scene3D";

// The titles and texts are in the locale files (home.actions), in the same order.
const ACTIONS: { to: string; icon: IconName; tone: string }[] = [
  { to: "/scan", icon: "camera", tone: "blue" },
  { to: "/scan", icon: "shield", tone: "teal" },
  { to: "/scan", icon: "chat", tone: "green" },
];

export default function Home() {
  const { user } = useAuth();
  const t = useT();
  const firstName = user?.full_name.split(/\s+/)[0] ?? "";

  const knows: { value: number; label: string; icon: IconName }[] = [
    { value: FACTS.pills, label: t.home.knowsPills, icon: "pill" },
    { value: FACTS.ingredients, label: t.home.knowsIngredients, icon: "spark" },
    { value: FACTS.interactions, label: t.home.knowsInteractions, icon: "link" },
    { value: FACTS.passages, label: t.home.knowsPassages, icon: "book" },
  ];

  return (
    <>
      <section className="hx-hero">
        <span className="aurora aurora-1" aria-hidden="true" />
        <span className="aurora aurora-2" aria-hidden="true" />
        <div className="hx-hero-copy">
          <p className="eyebrow">
            {greeting()}, {firstName}
          </p>
          <h1>{t.home.heroTitle}</h1>
          <p>{t.home.heroText(APP_NAME)}</p>
          <div className="hx-hero-actions">
            <Link className="btn btn-glow btn-lg" to="/scan">
              <Icon name="scan" />
              {t.home.openScanner}
            </Link>
            <Link className="btn btn-glass btn-lg" to="/reports">
              <Icon name="file" />
              {t.shell.reports}
            </Link>
            <Link className="btn btn-glass btn-lg" to="/toxicity">
              <Icon name="flask" />
              {t.home.toxicityModel}
            </Link>
          </div>
        </div>
        <Scene3D variant="compact" className="hx-scene" />
      </section>

      <section className="hx-actions" aria-label={t.home.actionsLabel}>
        {ACTIONS.map((action, index) => (
          <Link
            key={index}
            to={action.to}
            className={`hx-action hx-action-${action.tone} lift`}
            style={staggerIndex(index)}
          >
            <span className="hx-action-icon">
              <Icon name={action.icon} size={24} />
            </span>
            <span className="hx-step">{t.home.step(index + 1)}</span>
            <h2>{t.home.actions[index].title}</h2>
            <p>{t.home.actions[index].text}</p>
            <span className="hx-action-go" aria-hidden="true">
              <Icon name="arrow" />
            </span>
          </Link>
        ))}
      </section>

      <div className="hx-split">
        <section className="card hx-knows" aria-label={t.home.knows(APP_NAME)}>
          <h2>{t.home.knows(APP_NAME)}</h2>
          <div className="hx-knows-grid">
            {knows.map((item) => (
              <div className="hx-know" key={item.icon}>
                <span className="hx-know-icon">
                  <Icon name={item.icon} size={18} />
                </span>
                <strong>
                  <CountUp value={item.value} duration={1300} />
                </strong>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card hx-safety" aria-label={t.home.safetyLabel}>
          <h2>
            <Icon name="shield" /> {t.home.safetyTitle}
          </h2>
          <ul>
            {t.home.safetyRules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          <p className="hx-disclaimer">{DISCLAIMER}</p>
        </section>
      </div>

      <section className="hx-research" aria-label={t.home.researchLabel}>
        <span className="muted">{t.home.researchText}</span>
        <Link to="/drugs">
          <Icon name="pill" size={16} /> {t.shell.drugs}
        </Link>
        <Link to="/cell-lines">
          <Icon name="cells" size={16} /> {t.shell.cellLines}
        </Link>
        <Link to="/profile">
          <Icon name="user" size={16} /> {t.home.profile}
        </Link>
      </section>
    </>
  );
}
