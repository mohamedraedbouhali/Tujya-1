import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { api, type ActivityAction, type UsageDay } from "../../api";
import { Alert, formatNumber, StatTile, TableSkeleton } from "../../components";
import { useQuery } from "../../hooks";
import { getLang, useT } from "../../i18n";
import { Icon } from "../../icons";

const PERIODS = [7, 30, 90];

// Chart layout, in CSS pixels.
const HEIGHT = 220;
const PAD = { top: 12, right: 12, bottom: 26, left: 40 };
const BAR_MAX = 24; // columns never fill their slot
const GAP = 2; // surface gap between touching marks

interface Series {
  key: ActivityAction;
  label: string;
  color: string; // a CSS variable, set for light and dark mode in styles.css
}

/** The width of an element, kept up to date. */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** Clean axis ticks for counts: steps of 1, 2 or 5 times a power of ten, whole numbers. */
function ticksFor(max: number): number[] {
  const rough = Math.max(1, max) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? power * 10);
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  return ticks;
}

function shortDate(iso: string, long = false): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(getLang(), {
    day: "numeric",
    month: "short",
    weekday: long ? "short" : undefined,
  });
}

/** Which days get a label under the axis: about six, evenly spread, the last one always. */
function labelledDays(count: number): Set<number> {
  const step = Math.max(1, Math.ceil(count / 6));
  const shown = new Set<number>();
  for (let i = 0; i < count; i += step) shown.add(i);
  const last = count - 1;
  for (const i of shown) if (i !== last && last - i < step * 0.6) shown.delete(i);
  shown.add(last);
  return shown;
}

/** A column whose top corners are rounded (the data end) and whose base is square. */
function topRounded(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h}Z`;
}

/** Hover, focus and arrow keys pick a day; the readout follows it. */
function useActiveDay(count: number) {
  const [active, setActive] = useState<number | null>(null);
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    setActive((current) => {
      const at = current ?? count - 1;
      if (event.key === "Home") return 0;
      if (event.key === "End") return count - 1;
      return Math.min(count - 1, Math.max(0, at + (event.key === "ArrowLeft" ? -1 : 1)));
    });
  };
  return {
    active,
    setActive,
    focusProps: {
      tabIndex: 0,
      onKeyDown,
      onFocus: () => setActive((current) => current ?? count - 1),
      onBlur: () => setActive(null),
    },
  };
}

function Tooltip({
  x,
  width,
  date,
  rows,
}: {
  x: number;
  width: number;
  date: string;
  rows: { label: string; value: number; color: string; line?: boolean }[];
}) {
  // Kept inside the chart: right of the day, or left of it near the right edge.
  const left = x > width - 200 ? Math.max(0, x - 202) : x + 12;
  return (
    <div className="viz-tooltip" style={{ left }} aria-live="polite">
      <span className="viz-tooltip-date">{shortDate(date, true)}</span>
      {rows.map((row) => (
        <span key={row.label} className="viz-tooltip-row">
          <strong>{formatNumber(row.value)}</strong>
          <i className="viz-key-line" style={{ background: row.color }} />
          {row.label}
        </span>
      ))}
    </div>
  );
}

function Axis({ ticks, top, plotH, width }: { ticks: number[]; top: number; plotH: number; width: number }) {
  return (
    <g className="viz-grid" aria-hidden="true">
      {ticks.map((tick) => {
        const y = PAD.top + plotH - (tick / top) * plotH;
        return (
          <g key={tick}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y} y2={y} />
            <text x={PAD.left - 8} y={y} dy="0.32em" textAnchor="end">
              {formatNumber(tick)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function DayLabels({ days, band }: { days: UsageDay[]; band: number }) {
  const shown = labelledDays(days.length);
  return (
    <g className="viz-xlabels" aria-hidden="true">
      {days.map((day, i) =>
        shown.has(i) ? (
          <text key={day.date} x={PAD.left + band * (i + 0.5)} y={HEIGHT - 6} textAnchor="middle">
            {shortDate(day.date)}
          </text>
        ) : null,
      )}
    </g>
  );
}

/** Stacked columns, one per day: scans, checks and questions. */
function StackedColumns({ days, series, label }: { days: UsageDay[]; series: Series[]; label: string }) {
  const box = useRef<HTMLDivElement>(null);
  const width = useWidth(box);
  const { active, setActive, focusProps } = useActiveDay(days.length);
  const totals = days.map((day) => series.reduce((sum, s) => sum + (day.counts[s.key] ?? 0), 0));
  const ticks = ticksFor(Math.max(0, ...totals));
  const top = ticks[ticks.length - 1];
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const band = days.length ? plotW / days.length : 0;
  const barW = Math.max(1, Math.min(BAR_MAX, band - GAP));
  const baseline = PAD.top + plotH;

  return (
    <div className="viz-frame" ref={box} {...focusProps} role="group" aria-label={label}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={label} onPointerLeave={() => setActive(null)}>
          <Axis ticks={ticks} top={top} plotH={plotH} width={width} />
          {active !== null && (
            <rect className="viz-hover-band" x={PAD.left + band * active} y={PAD.top} width={band} height={plotH} />
          )}
          {days.map((day, i) => {
            const x = PAD.left + band * i + (band - barW) / 2;
            let y = baseline;
            const parts = series
              .map((s) => ({ s, value: day.counts[s.key] ?? 0 }))
              .filter((part) => part.value > 0);
            return (
              <g key={day.date}>
                {parts.map((part, k) => {
                  const h = (part.value / top) * plotH;
                  y -= h;
                  // The 2px gap sits under every segment that rests on another one.
                  const drawn = Math.max(1, h - (k > 0 ? GAP : 0));
                  const last = k === parts.length - 1;
                  return last ? (
                    <path key={part.s.key} d={topRounded(x, y, barW, drawn)} fill={part.s.color} />
                  ) : (
                    <rect key={part.s.key} x={x} y={y} width={barW} height={drawn} fill={part.s.color} />
                  );
                })}
              </g>
            );
          })}
          {/* Hit areas: the whole day's slot, much bigger than a thin column. */}
          {days.map((day, i) => (
            <rect
              key={day.date}
              className="viz-hit"
              x={PAD.left + band * i}
              y={PAD.top}
              width={band}
              height={plotH}
              onPointerEnter={() => setActive(i)}
            />
          ))}
          <line className="viz-baseline" x1={PAD.left} x2={width - PAD.right} y1={baseline} y2={baseline} />
          <DayLabels days={days} band={band} />
        </svg>
      )}
      {active !== null && days[active] && (
        <Tooltip
          x={PAD.left + band * (active + 0.5)}
          width={width}
          date={days[active].date}
          rows={series.map((s) => ({ label: s.label, value: days[active].counts[s.key] ?? 0, color: s.color }))}
        />
      )}
    </div>
  );
}

/** One line: accounts active each day, with a crosshair and the last value at its end. */
function DailyLine({ days, label, name }: { days: UsageDay[]; label: string; name: string }) {
  const box = useRef<HTMLDivElement>(null);
  const width = useWidth(box);
  const { active, setActive, focusProps } = useActiveDay(days.length);
  const values = days.map((day) => day.active_users);
  const ticks = ticksFor(Math.max(0, ...values));
  const top = ticks[ticks.length - 1];
  const plotW = Math.max(0, width - PAD.left - PAD.right - 24); // room for the end label
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const band = days.length ? plotW / days.length : 0;
  const baseline = PAD.top + plotH;
  const point = (i: number) => [PAD.left + band * (i + 0.5), baseline - (values[i] / top) * plotH] as const;
  const line = values.map((_, i) => `${i ? "L" : "M"}${point(i).join(",")}`).join("");
  const last = values.length - 1;
  const color = "var(--viz-ink)";

  return (
    <div className="viz-frame" ref={box} {...focusProps} role="group" aria-label={label}>
      {width > 0 && days.length > 0 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={label}
          onPointerMove={(event) => {
            const x = event.clientX - event.currentTarget.getBoundingClientRect().left - PAD.left;
            setActive(Math.min(last, Math.max(0, Math.floor(x / band))));
          }}
          onPointerLeave={() => setActive(null)}
        >
          <Axis ticks={ticks} top={top} plotH={plotH} width={width - 24} />
          <path
            className="viz-area"
            d={`${line}L${point(last)[0]},${baseline}L${point(0)[0]},${baseline}Z`}
          />
          <path className="viz-line" d={line} />
          {active !== null && (
            <>
              <line className="viz-crosshair" x1={point(active)[0]} x2={point(active)[0]} y1={PAD.top} y2={baseline} />
              <circle className="viz-dot" cx={point(active)[0]} cy={point(active)[1]} r={4} />
            </>
          )}
          <circle className="viz-dot" cx={point(last)[0]} cy={point(last)[1]} r={4} />
          <text className="viz-end-label" x={point(last)[0] + 9} y={point(last)[1]} dy="0.32em">
            {formatNumber(values[last])}
          </text>
          <line className="viz-baseline" x1={PAD.left} x2={width - PAD.right - 24} y1={baseline} y2={baseline} />
          <DayLabels days={days} band={band} />
        </svg>
      )}
      {active !== null && days[active] && (
        <Tooltip
          x={point(active)[0]}
          width={width}
          date={days[active].date}
          rows={[{ label: name, value: values[active], color }]}
        />
      )}
    </div>
  );
}

/** Administrators' usage report: counts per day, and CSV downloads (D83). */
export default function Usage() {
  const t = useT();
  const [days, setDays] = useState(30);
  const usage = useQuery((signal) => api.admin.usage(days, signal), [days]);
  const data = usage.data;
  const total = (action: ActivityAction) => data?.totals[action] ?? 0;

  const series: Series[] = [
    { key: "scan", label: t.usage.seriesScans, color: "var(--viz-1)" },
    { key: "interactions", label: t.usage.seriesChecks, color: "var(--viz-2)" },
    { key: "chat", label: t.usage.seriesQuestions, color: "var(--viz-3)" },
  ];
  const quiet = data !== null && series.every((s) => total(s.key) === 0) && data.active_users === 0;

  return (
    <>
      <header className="page-header">
        <div className="page-title">
          <span className="page-icon">
            <Icon name="file" size={24} />
          </span>
          <div>
            <h1>{t.usage.title}</h1>
            <p className="muted">{t.usage.subtitle}</p>
          </div>
        </div>
      </header>

      {/* One filter row, above everything it scopes. */}
      <div className="segmented usage-period" role="radiogroup" aria-label={t.usage.period}>
        {PERIODS.map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={days === n}
            className={days === n ? "segment segment-on" : "segment"}
            onClick={() => setDays(n)}
          >
            {t.usage.lastDays(n)}
          </button>
        ))}
      </div>

      {usage.error && <Alert>{usage.error}</Alert>}
      {!data && usage.loading && <TableSkeleton rows={6} />}

      {data && (
        <div className={usage.loading ? "usage-body is-refreshing" : "usage-body"}>
          <section className="stat-grid stat-grid-3" aria-label={t.usage.title}>
            <StatTile icon="scan" label={t.usage.tileScans} value={total("scan")} note={t.usage.inPeriod} />
            <StatTile icon="shield" label={t.usage.tileChecks} value={total("interactions")} note={t.usage.inPeriod} />
            <StatTile icon="chat" label={t.usage.tileQuestions} value={total("chat")} note={t.usage.inPeriod} />
            <StatTile icon="users" label={t.usage.tileActive} value={data.active_users} note={t.usage.inPeriod} />
            <StatTile icon="plus" label={t.usage.tileNew} value={data.new_accounts} note={t.usage.inPeriod} />
            <StatTile icon="file" label={t.usage.tileReports} value={data.reports_saved} note={t.usage.sharedNow(data.shared_now)} />
          </section>

          {quiet && <Alert kind="info">{t.usage.empty}</Alert>}

          <section className="card viz">
            <div className="viz-head">
              <h2>{t.usage.chartTitle}</h2>
              <ul className="viz-legend">
                {series.map((s) => (
                  <li key={s.key}>
                    <i className="viz-key-box" style={{ background: s.color }} />
                    {s.label}
                  </li>
                ))}
              </ul>
            </div>
            <StackedColumns days={data.days} series={series} label={t.usage.chartLabel(days)} />
            <details className="viz-table">
              <summary>{t.usage.showTable}</summary>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t.usage.colDay}</th>
                      {series.map((s) => (
                        <th key={s.key}>{s.label}</th>
                      ))}
                      <th>{t.usage.tileActive}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.days].reverse().map((day) => (
                      <tr key={day.date}>
                        <td>{shortDate(day.date, true)}</td>
                        {series.map((s) => (
                          <td key={s.key}>{formatNumber(day.counts[s.key] ?? 0)}</td>
                        ))}
                        <td>{formatNumber(day.active_users)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </section>

          <section className="card viz">
            <div className="viz-head">
              <h2>{t.usage.activeTitle}</h2>
            </div>
            <DailyLine days={data.days} label={t.usage.activeLabel(days)} name={t.usage.tileActive} />
          </section>
        </div>
      )}

      <section className="card usage-export">
        <div>
          <h2>
            <Icon name="download" size={18} /> {t.usage.exportTitle}
          </h2>
          <p className="muted">{t.usage.exportText}</p>
        </div>
        <div className="usage-export-links">
          <a className="btn btn-secondary" href={api.admin.usersCsvUrl} download>
            <Icon name="users" size={16} />
            {t.usage.exportUsers}
          </a>
          <a className="btn btn-secondary" href={api.admin.activityCsvUrl({ days })} download>
            <Icon name="activity" size={16} />
            {t.usage.exportActivity(days)}
          </a>
        </div>
      </section>
    </>
  );
}
