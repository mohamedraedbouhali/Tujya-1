import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { useT } from "./i18n";
import { Icon } from "./icons";

const depth = (value: number) => ({ "--depth": value }) as CSSProperties;

/**
 * Glass cards floating over the 3D scene: what a scan, a check and an answer look like.
 * The examples are the project's own (docs/INFRA.md smoke test, DDInter 2.0). They drift
 * with the pointer (see `parallax`) and are hidden from screen readers: decoration only.
 */
export function FloatCards({ variant = "hero" }: { variant?: "hero" | "auth" }) {
  const t = useT();
  return (
    <div className={`float-cards float-cards-${variant}`} aria-hidden="true">
      <div className="float-card fc-1" style={depth(1.3)}>
        <div className="float-inner">
          <span className="fc-icon fc-blue">
            <Icon name="scan" size={16} />
          </span>
          <span className="fc-text">
            <small>{t.floatCards.topMatch}</small>
            <strong>Fluconazole 100 mg</strong>
            <span className="fc-bar">
              <span />
            </span>
          </span>
          <b className="fc-value">99.6 %</b>
        </div>
      </div>
      <div className="float-card fc-2" style={depth(0.8)}>
        <div className="float-inner">
          <span className="fc-icon fc-red">
            <Icon name="alert" size={16} />
          </span>
          <span className="fc-text">
            <small>DDInter 2.0</small>
            <strong>Fluconazole + Warfarin</strong>
          </span>
          <span className="sev sev-major">{t.severity.Major}</span>
        </div>
      </div>
      {variant === "hero" && (
        <div className="float-card fc-3" style={depth(1.6)}>
          <div className="float-inner">
            <span className="fc-icon fc-green">
              <Icon name="chat" size={16} />
            </span>
            <span className="fc-text">
              <small>{t.floatCards.answer}</small>
              <strong>{t.floatCards.everyCited}</strong>
            </span>
            <span className="fc-cites">
              <span>[1]</span>
              <span>[2]</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/** Pointer position over an element as CSS variables: --px / --py in -1..1 (parallax), and
 * --cx / --cy in pixels (a glow that follows the cursor). */
export function parallax(event: ReactPointerEvent<HTMLElement>) {
  const box = event.currentTarget.getBoundingClientRect();
  const x = (event.clientX - box.left) / box.width;
  const y = (event.clientY - box.top) / box.height;
  const style = event.currentTarget.style;
  style.setProperty("--px", (x * 2 - 1).toFixed(3));
  style.setProperty("--py", (y * 2 - 1).toFixed(3));
  style.setProperty("--cx", `${Math.round(event.clientX - box.left)}px`);
  style.setProperty("--cy", `${Math.round(event.clientY - box.top)}px`);
}

/** Cards that tilt towards the pointer and light up under it (.tilt and .spot in the CSS). */
export function tilt(event: ReactPointerEvent<HTMLElement>) {
  const card = event.currentTarget;
  const box = card.getBoundingClientRect();
  const x = (event.clientX - box.left) / box.width - 0.5;
  const y = (event.clientY - box.top) / box.height - 0.5;
  card.style.setProperty("--ry", `${(x * 9).toFixed(2)}deg`);
  card.style.setProperty("--rx", `${(-y * 9).toFixed(2)}deg`);
  card.style.setProperty("--mx", `${Math.round(event.clientX - box.left)}px`);
  card.style.setProperty("--my", `${Math.round(event.clientY - box.top)}px`);
}

export function untilt(event: ReactPointerEvent<HTMLElement>) {
  event.currentTarget.style.setProperty("--rx", "0deg");
  event.currentTarget.style.setProperty("--ry", "0deg");
}
