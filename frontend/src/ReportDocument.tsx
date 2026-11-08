import { Fragment, type ReactNode } from "react";
import type {
  ChatExcerpt,
  InteractionPair,
  ReportBody,
  Severity,
  Source,
} from "./api";
import { APP_NAME, DISCLAIMER } from "./brand";
import { Badge, Logo } from "./components";
import { formatDate, useT } from "./i18n";
import { Icon } from "./icons";

export const SEVERITY_TONE: Record<Severity, string> = {
  Major: "danger",
  Moderate: "warn",
  Minor: "info",
  Unknown: "neutral",
};

/** A report's reference, for lab notebooks and records: TJY-2026-0001. */
export function reportReference(report: {
  id: number;
  created_at: string;
}): string {
  return `TJY-${new Date(report.created_at).getFullYear()}-${String(report.id).padStart(4, "0")}`;
}

/** The active ingredients of a report's products, each once, sorted. */
export function ingredientsOf(report: ReportBody): string[] {
  return [
    ...new Set(report.pills.flatMap((pill) => pill.active_ingredients)),
  ].sort();
}

/**
 * The title: the one the author gave, or else what was analysed ("Interaction analysis:
 * fluconazole, warfarin"), or for questions only, the date.
 */
export function useReportTitle(): (report: {
  title: string;
  created_at: string;
  ingredients: string[];
}) => string {
  const t = useT();
  return (report) => {
    if (report.title) return report.title;
    if (report.ingredients.length === 0)
      return t.reports.untitled(formatDate(report.created_at));
    const shown = report.ingredients.slice(0, 4).join(", ");
    const more = report.ingredients.length - 4;
    return t.report.autoTitle(more > 0 ? `${shown} +${more}` : shown);
  };
}

// Short names of the databases, for the report header.
const DATA_NAMES: Record<string, string> = {
  ddinter: "DDInter 2.0",
  rxnav: "RxNorm",
  c3pi: "NLM C3PI",
};

/** The answer's lines, each [n] as a superscript; the disclaimer line is shown once, below. */
function Answer({ text }: { text: string }) {
  const lines = text
    .split("\n")
    .filter((line) => line.trim() && line.trim() !== DISCLAIMER);
  return (
    <>
      {lines.map((line, index) => {
        const parts: ReactNode[] = [];
        let last = 0;
        for (const match of line.matchAll(/\[(\d+)\]/g)) {
          parts.push(line.slice(last, match.index));
          parts.push(<sup key={match.index}>[{match[1]}]</sup>);
          last = (match.index ?? 0) + match[0].length;
        }
        parts.push(line.slice(last));
        return (
          <p key={index}>
            {parts.map((part, i) => (
              <Fragment key={i}>{part}</Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}

function Pair({ pair }: { pair: InteractionPair }) {
  const t = useT();
  const tone = pair.highest_severity
    ? SEVERITY_TONE[pair.highest_severity]
    : "none";
  return (
    <div className={`rdoc-pair rdoc-pair-${tone}`}>
      <div className="rdoc-pair-head">
        <strong>
          {pair.item_a.label} <span className="muted">+</span>{" "}
          {pair.item_b.label}
        </strong>
        {pair.highest_severity && (
          <Badge tone={SEVERITY_TONE[pair.highest_severity]}>
            {t.severity[pair.highest_severity]}
          </Badge>
        )}
      </div>
      {pair.message && <p className="rdoc-note">{pair.message}</p>}
      {pair.interactions.length > 0 && (
        <ul>
          {pair.interactions.map((found) => (
            <li key={`${found.ingredient_a}-${found.ingredient_b}`}>
              <strong>
                {found.ingredient_a} + {found.ingredient_b}
              </strong>
              :{" "}
              {found.severity === "Unknown"
                ? t.severity.unknownLong
                : t.severity[found.severity]}
              . {found.description}
            </li>
          ))}
        </ul>
      )}
      {pair.shared_ingredients.length > 0 && (
        <p className="rdoc-note">
          <Icon name="alert" size={14} />{" "}
          {t.scan.sameIngredient(pair.shared_ingredients.join(", "))}
        </p>
      )}
    </div>
  );
}

function ChatAnswer({ item, index }: { item: ChatExcerpt; index: number }) {
  return (
    <div className="rdoc-qa">
      <p className="rdoc-question">
        <span className="rdoc-qa-n">{index + 1}</span>
        {item.question}
      </p>
      <div className="rdoc-answer">
        <Answer text={item.answer} />
      </div>
      {item.citations.length > 0 && (
        <ol className="rdoc-cites">
          {item.citations.map((cite) => (
            <li key={cite.n} value={cite.n}>
              <a href={cite.url} target="_blank" rel="noreferrer">
                {cite.title}
              </a>
              <span className="rdoc-url">{cite.url}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <ul className="rdoc-sources">
      {sources.map((source) => (
        <li key={source.name}>
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.title}
          </a>{" "}
          <span className="muted">({source.license})</span>
          {source.citation && (
            <span className="rdoc-url">{source.citation}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * A report as a sheet of paper: white in both themes, so it reads and prints the same.
 * `owner` adds the hints only the author needs (such as how to add a signature).
 */
export function ReportDocument({
  report,
  owner = false,
}: {
  report: ReportBody;
  owner?: boolean;
}) {
  const t = useT();
  const titleOf = useReportTitle();
  const title = titleOf({ ...report, ingredients: ingredientsOf(report) });
  const made = formatDate(report.created_at, true);
  const interactions = report.interactions;
  const data = (interactions?.sources ?? []).map(
    (source) => DATA_NAMES[source.name] ?? source.title,
  );
  // Sections are numbered in the order they appear; the optional ones take no number.
  const sections = [
    report.pills.length > 0 && "products",
    "interactions",
    report.chat.length > 0 && "chat",
    interactions && interactions.sources.length > 0 && "sources",
  ].filter((key): key is string => typeof key === "string");
  const numbered = (key: string, heading: string) =>
    `${sections.indexOf(key) + 1}. ${heading}`;

  return (
    <article className="rdoc" aria-label={title}>
      <header className="rdoc-head">
        <Logo height={44} tone="light" />
        <div className="rdoc-head-text">
          <p className="rdoc-eyebrow">{t.report.heading}</p>
          <h1>{title}</h1>
        </div>
        <dl className="rdoc-meta">
          <div>
            <dt>{t.report.metaReference}</dt>
            <dd className="rdoc-ref">{reportReference(report)}</dd>
          </div>
          <div>
            <dt>{t.report.metaDate}</dt>
            <dd>{made}</dd>
          </div>
          <div>
            <dt>{t.report.metaPreparedBy}</dt>
            <dd>{report.author}</dd>
          </div>
          {data.length > 0 && (
            <div>
              <dt>{t.report.metaData}</dt>
              <dd>{data.join(" · ")}</dd>
            </div>
          )}
        </dl>
      </header>

      {report.pills.length > 0 && (
        <section className="rdoc-section">
          <h2>{numbered("products", t.report.medicinesTitle)}</h2>
          {/* Scrolls on its own on a narrow phone rather than widening the page. */}
          <div className="rdoc-table-wrap">
            <table className="rdoc-table">
              <thead>
                <tr>
                  <th>{t.report.colMedicine}</th>
                  <th>{t.report.colIngredients}</th>
                  <th>{t.report.colClass}</th>
                </tr>
              </thead>
              <tbody>
                {report.pills.map((pill) => (
                  <tr key={pill.class_id}>
                    <td>
                      <strong>{pill.name}</strong>
                      {pill.generic_name && (
                        <span className="rdoc-sub">{pill.generic_name}</span>
                      )}
                    </td>
                    <td>
                      {pill.active_ingredients.length ? (
                        pill.active_ingredients.join(", ")
                      ) : (
                        <span className="muted">{t.report.noIngredient}</span>
                      )}
                    </td>
                    <td>{pill.class_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="rdoc-section">
        <h2>{numbered("interactions", t.report.interactionsTitle)}</h2>
        {interactions ? (
          <div className="rdoc-pairs">
            {interactions.pairs.map((pair) => (
              <Pair
                key={`${pair.item_a.label}|${pair.item_b.label}`}
                pair={pair}
              />
            ))}
          </div>
        ) : (
          <p className="muted">{t.report.onlyAnswers}</p>
        )}
      </section>

      {report.chat.length > 0 && (
        <section className="rdoc-section">
          <h2>{numbered("chat", t.report.chatTitle)}</h2>
          {report.chat.map((item, index) => (
            <ChatAnswer key={index} item={item} index={index} />
          ))}
        </section>
      )}

      {interactions && interactions.sources.length > 0 && (
        <section className="rdoc-section">
          <h2>{numbered("sources", t.report.sourcesTitle)}</h2>
          <Sources sources={interactions.sources} />
        </section>
      )}

      <footer className="rdoc-foot">
        <div className="rdoc-signature">
          <span className="rdoc-label">{t.report.signatureTitle}</span>
          {report.signature ? (
            <img
              src={report.signature}
              alt={t.profile.signatureAlt(report.author)}
            />
          ) : (
            <span className="rdoc-sign-space" aria-hidden="true" />
          )}
          <span className="rdoc-sign-name">{report.author}</span>
          <span className="rdoc-sub">{made}</span>
          {owner && !report.signature && (
            <p className="rdoc-hint no-print">{t.report.noSignature}</p>
          )}
        </div>
        <p className="rdoc-colophon">
          {t.report.snapshot} {t.report.generatedBy(APP_NAME)}.
          {/* Small print, not a banner, but still on the paper word for word (D53). */}
          <span className="rdoc-fineprint" lang="fr">
            {report.disclaimer}
          </span>
        </p>
      </footer>
    </article>
  );
}
