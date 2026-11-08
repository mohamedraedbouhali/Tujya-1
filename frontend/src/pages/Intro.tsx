import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { APP_NAME, DISCLAIMER, FACTS, SOURCES } from "../brand";
import { LanguageMenu, Logo, LogoMark } from "../components";
import { FloatCards, parallax, tilt, untilt } from "../FloatCards";
import { SiteFooter } from "../Footer";
import { useT, type Messages } from "../i18n";
import { Icon, type IconName } from "../icons";
import { CountUp, Reveal } from "../motion";
import { Scene3D } from "../Scene3D";

/** Pointer handlers of every card that tilts and lights up under the pointer. */
const TILT = { onPointerMove: tilt, onPointerLeave: untilt };

// The texts of the steps and rules are in the locale files, in the same order as these icons.
const STEP_ICONS: IconName[] = ["camera", "shield", "chat"];
const RULE_ICONS: IconName[] = ["ban", "shield", "book", "clock", "eye", "alert"];

const bar = (width: string) => ({ "--w": width }) as CSSProperties;

function ScanMock({ t }: { t: Messages }) {
  return (
    <div className="mock mock-scan" aria-hidden="true">
      <div className="mock-photo">
        <span className="mock-pill" />
        <span className="mock-box">
          <span className="mock-tag">pill · 0.99</span>
        </span>
        <span className="mock-sweep" />
      </div>
      <ol className="mock-top5">
        <li>
          <span>{t.intro.mockTablets}</span>
          <span className="mock-bar" style={bar("99.6%")} />
          <b>99.6 %</b>
        </li>
        <li>
          <span>{t.intro.mockSecond}</span>
          <span className="mock-bar" style={bar("3%")} />
          <b>&lt; 1 %</b>
        </li>
        <li>
          <span>{t.intro.mockThird}</span>
          <span className="mock-bar" style={bar("2%")} />
          <b>&lt; 1 %</b>
        </li>
      </ol>
    </div>
  );
}

function InteractionMock({ t }: { t: Messages }) {
  return (
    <div className="mock mock-pairs" aria-hidden="true">
      <div className="mock-pair">
        <span>Fluconazole + Warfarin</span>
        <span className="sev sev-major">{t.severity.Major}</span>
      </div>
      <div className="mock-pair">
        <span>Fluconazole + Citalopram</span>
        <span className="sev sev-major">{t.severity.Major}</span>
      </div>
      <div className="mock-pair">
        <span>{t.intro.mockUnlisted}</span>
        <span className="sev sev-none">{t.intro.mockNoKnown}</span>
      </div>
      <p className="mock-note">{t.intro.mockPairsNote}</p>
    </div>
  );
}

/** A real exchange with the agent, in French on purpose: it answers in French or English. */
function ChatMock({ t }: { t: Messages }) {
  return (
    <div className="mock mock-chat" aria-hidden="true">
      <p className="bubble bubble-q">La warfarine interagit-elle avec le fluconazole ?</p>
      <p className="bubble bubble-a">
        DDInter 2.0 classe cette interaction comme majeure <sup>[1]</sup>. Le fluconazole augmente
        le temps de prothrombine chez les patients sous warfarine <sup>[2]</sup>.
      </p>
      <div className="mock-cites">
        <span>[1] DDInter 2.0</span>
        <span>[2] {t.intro.mockLabel}</span>
      </div>
    </div>
  );
}

/** The public start page: what Tujya is, shown before anyone signs in. */
export default function Intro() {
  const t = useT();
  const [scrolled, setScrolled] = useState(false);
  const progress = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const onScroll = () => {
      setScrolled(window.scrollY > 24);
      const range = document.documentElement.scrollHeight - window.innerHeight;
      progress.current?.style.setProperty(
        "--progress",
        String(range > 0 ? Math.min(1, window.scrollY / range) : 0),
      );
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="lp">
      <header className={scrolled ? "lp-nav is-scrolled" : "lp-nav"}>
        <div className="lp-inner lp-nav-inner">
          <Link to="/" className="lp-brand" aria-label={t.intro.homeLink(APP_NAME)}>
            <Logo height={54} tone="dark" />
          </Link>
          <nav className="lp-links" aria-label={t.intro.sections}>
            <a href="#how">{t.intro.linkHow}</a>
            <a href="#features">{t.intro.linkFeatures}</a>
            <a href="#safety">{t.intro.linkSafety}</a>
            <a href="#sources">{t.intro.linkData}</a>
          </nav>
          <div className="lp-nav-actions">
            <LanguageMenu className="lang-menu-glass" />
            <Link className="btn btn-glass" to="/login">
              {t.common.signIn}
            </Link>
            <Link className="btn btn-glow" to="/signup">
              {t.intro.getStarted}
              <Icon name="arrow" size={16} />
            </Link>
          </div>
        </div>
        <span className="lp-progress" ref={progress} aria-hidden="true" />
      </header>

      <main>
        <section className="lp-hero" onPointerMove={parallax}>
          <div className="lp-hero-bg" aria-hidden="true">
            <span className="aurora aurora-1" />
            <span className="aurora aurora-2" />
            <span className="aurora aurora-3" />
            <span className="lp-grid-lines" />
            <span className="lp-beam" />
          </div>
          <span className="lp-cursor" aria-hidden="true" />
          <Scene3D variant="hero" className="lp-scene" />
          <FloatCards />
          <div className="lp-inner lp-hero-inner">
            <div className="lp-hero-copy">
              <p className="lp-chip">
                <span className="lp-chip-dot" />
                {t.intro.chip}
              </p>
              <h1 className="lp-title">
                <span className="line">
                  <span>{t.intro.title1}</span>
                </span>
                <span className="line">
                  <span className="text-gradient shimmer">{t.intro.title2}</span>
                </span>
              </h1>
              <p className="lp-lead">{t.intro.lead(APP_NAME)}</p>
              <div className="lp-cta">
                <Link className="btn btn-glow btn-lg" to="/signup">
                  {t.intro.startScanning}
                  <Icon name="arrow" />
                </Link>
                <a className="btn btn-glass btn-lg" href="#how">
                  {t.intro.seeHow}
                </a>
              </div>
              <p className="lp-disclaimer">
                <Icon name="shield" size={15} />
                {DISCLAIMER}
              </p>
            </div>
          </div>
          <a className="lp-scroll" href="#how" aria-label={t.intro.scrollToHow}>
            <span />
          </a>
        </section>

        <section className="lp-stats" aria-label={t.intro.statsLabel(APP_NAME)}>
          <Reveal stagger className="lp-inner lp-stats-grid">
            <div className="lp-stat">
              <strong>
                <CountUp value={FACTS.pills} duration={1200} />
              </strong>
              <span>{t.intro.statPills}</span>
            </div>
            <div className="lp-stat">
              <strong>
                <CountUp value={FACTS.ingredients} duration={1200} />
              </strong>
              <span>{t.intro.statIngredients}</span>
            </div>
            <div className="lp-stat">
              <strong>
                <CountUp value={FACTS.interactions} duration={1600} />
              </strong>
              <span>{t.intro.statInteractions}</span>
            </div>
            <div className="lp-stat">
              <strong>
                <CountUp value={FACTS.passages} duration={1600} />
              </strong>
              <span>{t.intro.statPassages}</span>
            </div>
          </Reveal>
        </section>

        <section id="how" className="lp-section">
          <div className="lp-inner">
            <Reveal className="lp-head">
              <p className="lp-eyebrow">{t.intro.howEyebrow}</p>
              <h2>{t.intro.howTitle}</h2>
            </Reveal>
            <Reveal stagger className="lp-steps">
              {t.intro.steps.map((step, index) => (
                <article className="lp-step glass spot tilt" key={index} {...TILT}>
                  <span className="lp-step-num">0{index + 1}</span>
                  <span className="lp-step-icon">
                    <Icon name={STEP_ICONS[index]} size={24} />
                  </span>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </article>
              ))}
            </Reveal>
          </div>
        </section>

        <section id="features" className="lp-section">
          <div className="lp-inner">
            <Reveal className="lp-head">
              <p className="lp-eyebrow">{t.intro.featuresEyebrow}</p>
              <h2>{t.intro.featuresTitle}</h2>
              <p className="lp-sub">{t.intro.featuresSub}</p>
            </Reveal>
            <Reveal stagger className="lp-bento">
              <article className="bento bento-wide glass spot tilt" {...TILT}>
                <div className="bento-copy">
                  <span className="bento-icon">
                    <Icon name="scan" size={22} />
                  </span>
                  <h3>{t.intro.seeTitle}</h3>
                  <p>{t.intro.seeText}</p>
                </div>
                <ScanMock t={t} />
              </article>
              <article className="bento glass spot tilt" {...TILT}>
                <div className="bento-copy">
                  <span className="bento-icon">
                    <Icon name="shield" size={22} />
                  </span>
                  <h3>{t.intro.traceTitle}</h3>
                  <p>{t.intro.traceText}</p>
                </div>
                <InteractionMock t={t} />
              </article>
              <article className="bento glass spot tilt" {...TILT}>
                <div className="bento-copy">
                  <span className="bento-icon">
                    <Icon name="chat" size={22} />
                  </span>
                  <h3>{t.intro.answersTitle}</h3>
                  <p>{t.intro.answersText}</p>
                </div>
                <ChatMock t={t} />
              </article>
              <article className="bento glass spot tilt" {...TILT}>
                <div className="bento-copy">
                  <span className="bento-icon">
                    <Icon name="lock" size={22} />
                  </span>
                  <h3>{t.intro.privateTitle}</h3>
                  <p>{t.intro.privateText}</p>
                </div>
                <ul className="mock mock-local" aria-label={t.intro.localLabel}>
                  {t.intro.local.map((item) => (
                    <li key={item}>
                      <span className="mock-led" /> {item}
                    </li>
                  ))}
                </ul>
              </article>
              <article className="bento glass spot tilt" {...TILT}>
                <div className="bento-copy">
                  <span className="bento-icon">
                    <Icon name="bolt" size={22} />
                  </span>
                  <h3>{t.intro.fastTitle}</h3>
                  <p>{t.intro.fastText}</p>
                </div>
                <div className="mock mock-speed" aria-hidden="true">
                  <div className="mock-speed-row">
                    <span>{t.intro.speedScan}</span>
                    <span className="mock-speed-bar" style={bar("22%")} />
                    <b>50–220 ms</b>
                  </div>
                  <div className="mock-speed-row">
                    <span>{t.intro.speedPlan}</span>
                    <span className="mock-speed-bar" style={bar("6%")} />
                    <b>{t.intro.speedPlanValue}</b>
                  </div>
                  <div className="mock-speed-row">
                    <span>{t.intro.speedAgain}</span>
                    <span className="mock-speed-bar" style={bar("3%")} />
                    <b>{t.intro.speedAgainValue}</b>
                  </div>
                </div>
              </article>
            </Reveal>
          </div>
        </section>

        <section id="safety" className="lp-section">
          <div className="lp-inner lp-safety">
            <Reveal className="lp-safety-intro">
              <p className="lp-eyebrow">{t.intro.safetyEyebrow}</p>
              <h2>{t.intro.safetyTitle}</h2>
              <p className="lp-sub">{t.intro.safetySub}</p>
            </Reveal>
            <Reveal stagger className="lp-rules">
              {t.intro.rules.map((rule, index) => (
                <div className="lp-rule spot tilt" key={index} {...TILT}>
                  <span className="lp-rule-icon">
                    <Icon name={RULE_ICONS[index]} size={20} />
                  </span>
                  <div>
                    <h3>{rule.title}</h3>
                    <p>{rule.text}</p>
                  </div>
                </div>
              ))}
            </Reveal>
          </div>
        </section>

        <section className="lp-stack" aria-label={t.intro.stackTitle}>
          <p className="lp-eyebrow lp-stack-title">{t.intro.stackTitle}</p>
          <div className="marquee">
            <div className="marquee-track">
              {[...t.intro.stack, ...t.intro.stack].map((item, index) => (
                <span
                  className="marquee-item"
                  key={index}
                  aria-hidden={index >= t.intro.stack.length}
                >
                  <Icon name="spark" size={14} />
                  {item}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section id="sources" className="lp-section">
          <div className="lp-inner">
            <Reveal className="lp-head">
              <p className="lp-eyebrow">{t.intro.dataEyebrow}</p>
              <h2>{t.intro.dataTitle}</h2>
              <p className="lp-sub">{t.intro.dataSub}</p>
            </Reveal>
            <Reveal stagger className="lp-sources">
              {SOURCES.map((source, index) => (
                <div className="lp-source glass spot tilt" key={source.name} {...TILT}>
                  <span className="lp-source-icon">
                    <Icon name="database" size={18} />
                  </span>
                  <strong>{source.name}</strong>
                  <span>{t.intro.sourceGives[index]}</span>
                  <em>{source.licence ?? t.intro.nlmTerms}</em>
                </div>
              ))}
            </Reveal>
          </div>
        </section>

        <section className="lp-section lp-final-wrap">
          <Reveal className="lp-inner">
            <div className="lp-final">
              <span className="aurora aurora-1" aria-hidden="true" />
              <span className="aurora aurora-2" aria-hidden="true" />
              <LogoMark size={92} className="emblem-float" />
              <h2>{t.intro.finalTitle}</h2>
              <p>{t.intro.finalText}</p>
              <div className="lp-cta lp-cta-center">
                <Link className="btn btn-glow btn-lg" to="/signup">
                  {t.intro.createAccount}
                  <Icon name="arrow" />
                </Link>
                <Link className="btn btn-glass btn-lg" to="/login">
                  {t.common.signIn}
                </Link>
              </div>
            </div>
          </Reveal>
        </section>
      </main>

      <SiteFooter
        landing
        groups={[
          {
            title: t.footer.explore,
            links: [
              { href: "#how", label: t.intro.linkHow },
              { href: "#features", label: t.intro.linkFeatures },
              { href: "#safety", label: t.intro.linkSafety },
              { href: "#sources", label: t.intro.linkData },
            ],
          },
          {
            title: t.footer.account,
            links: [
              { to: "/login", label: t.common.signIn },
              { to: "/signup", label: t.intro.createAccount },
            ],
          },
        ]}
      />
    </div>
  );
}
