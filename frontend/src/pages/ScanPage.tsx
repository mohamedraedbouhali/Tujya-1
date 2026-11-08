import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  errorMessage,
  excerptOf,
  type ChatResult,
  type DemoImage,
  type InteractionPair,
  type InteractionsResult,
  type PillCandidate,
  type SavedPill,
  type ScannedPill,
  type ScanResult,
  type Severity,
  type Source,
} from "../api";
import { Alert, Badge, Modal, Spinner, staggerIndex, TextField } from "../components";
import { useDebounced, useQuery } from "../hooks";
import { formatPercent, messages, useT, type Messages } from "../i18n";
import { Icon, type IconName } from "../icons";
import ChatPanel from "./ChatPanel";

// Safety texts are shown exactly as the project rules write them (CLAUDE.md, D53).
const DISCLAIMER = "Information uniquement, consultez un pharmacien ou un médecin.";
const ACCEPTED_TYPES = "image/jpeg,image/png,image/webp";
const MAX_BYTES = 10 * 1024 * 1024;
const LIVE_PAUSE_MS = 400; // between two live frames, after the previous answer arrived

type Mode = "upload" | "webcam" | "demo";

const MODES: { mode: Mode; icon: IconName }[] = [
  { mode: "upload", icon: "upload" },
  { mode: "webcam", icon: "camera" },
  { mode: "demo", icon: "image" },
];

function modeLabel(t: Messages, mode: Mode): string {
  if (mode === "upload") return t.scan.modeUpload;
  return mode === "webcam" ? t.scan.modeWebcam : t.scan.modeDemo;
}

interface Photo {
  url: string; // object URL of exactly what was sent to the scan
  name: string;
}

function percent(value: number): string {
  return formatPercent(value);
}

function Disclaimer({ text = DISCLAIMER }: { text?: string }) {
  return (
    <p className="disclaimer">
      <Icon name="shield" size={16} />
      {text}
    </p>
  );
}

function SourceList({ sources }: { sources: Source[] }) {
  const t = useT();
  if (sources.length === 0) return null;
  return (
    <div className="cited-sources">
      <h4>{t.common.sources}</h4>
      <ul>
        {sources.map((source) => (
          <li key={source.name}>
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.title}
            </a>{" "}
            <span className="muted">({source.license})</span>
            {source.citation && <span className="cell-sub">{source.citation}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The photo with one numbered box per detected pill, drawn in an SVG on top of it. */
function Overlay({
  alt,
  pills,
  live = false,
}: {
  alt: string;
  pills: ScannedPill[];
  live?: boolean;
}) {
  return (
    <svg className={live ? "scan-overlay scan-overlay-live" : "scan-overlay"} aria-hidden={live}>
      {!live && <title>{alt}</title>}
      {pills.map((pill, index) => {
        const box = pill.box_normalized;
        const top = pill.candidates[0];
        const tone = pill.needs_confirmation ? "warn" : "ok";
        return (
          <g key={index} className={`scan-box scan-box-${tone}`}>
            <rect
              x={`${box.x1 * 100}%`}
              y={`${box.y1 * 100}%`}
              width={`${(box.x2 - box.x1) * 100}%`}
              height={`${(box.y2 - box.y1) * 100}%`}
              rx="6"
            />
            <text x={`${box.x1 * 100}%`} y={`${box.y1 * 100}%`} dx="4" dy="-8">
              {index + 1}. {top ? `${top.name} ${percent(top.probability)}` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function UploadPanel({ onImage }: { onImage: (file: Blob, name: string) => void }) {
  const t = useT();
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const take = (file: File | undefined) => {
    if (!file) return;
    if (!ACCEPTED_TYPES.split(",").includes(file.type)) {
      setProblem(t.scan.invalidType);
      return;
    }
    if (file.size > MAX_BYTES) {
      setProblem(t.scan.tooLarge);
      return;
    }
    setProblem(null);
    onImage(file, file.name);
  };

  const drop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    take(event.dataTransfer.files[0]);
  };

  return (
    <>
      {problem && <Alert>{problem}</Alert>}
      <label
        className={dragging ? "dropzone dropzone-active" : "dropzone"}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <Icon name="upload" size={28} />
        <strong>{t.scan.dropTitle}</strong>
        <span className="muted">{t.scan.dropHint}</span>
        <input
          type="file"
          accept={ACCEPTED_TYPES}
          className="sr-only"
          data-testid="scan-file"
          onChange={(event) => {
            take(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </label>
    </>
  );
}

function grabFrame(video: HTMLVideoElement, maxWidth: number): Promise<Blob> {
  const scale = Math.min(1, maxWidth / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error(messages().errors.cameraImage))),
      "image/jpeg",
      0.9,
    ),
  );
}

/** Live camera: preview with boxes refreshed about once a second, and a capture button. */
function WebcamPanel({ onImage }: { onImage: (file: Blob, name: string) => void }) {
  const t = useT();
  const video = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [preview, setPreview] = useState<ScanResult | null>(null);

  const start = async () => {
    setProblem(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setProblem(t.scan.noCamera);
      return;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 } },
        audio: false,
      });
      setStream(media);
    } catch (failure) {
      setProblem(t.scan.cameraUnavailable(errorMessage(failure)));
    }
  };

  // Attach the stream to the <video>, and stop the camera when leaving the panel.
  useEffect(() => {
    if (video.current && stream) video.current.srcObject = stream;
    return () => stream?.getTracks().forEach((track) => track.stop());
  }, [stream]);

  // Live predictions: one frame at a time, the next only after the previous answer.
  useEffect(() => {
    if (!stream || !live) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      const element = video.current;
      if (controller.signal.aborted) return;
      if (element && element.videoWidth > 0) {
        try {
          const frame = await grabFrame(element, 960);
          const result = await api.scan(frame, "live.jpg", controller.signal, true);
          if (!controller.signal.aborted) setPreview(result);
        } catch (failure) {
          if (controller.signal.aborted) return;
          setProblem(errorMessage(failure));
          setLive(false);
          return;
        }
      }
      timer = window.setTimeout(tick, LIVE_PAUSE_MS);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [stream, live]);

  const capture = async () => {
    if (!video.current) return;
    try {
      onImage(await grabFrame(video.current, 1920), "webcam.jpg");
    } catch (failure) {
      setProblem(errorMessage(failure));
    }
  };

  return (
    <>
      {problem && <Alert>{problem}</Alert>}
      {!stream ? (
        <div className="dropzone">
          <Icon name="camera" size={28} />
          <strong>{t.scan.useCamera}</strong>
          <span className="muted">{t.scan.cameraHint}</span>
          <button type="button" className="btn btn-primary" onClick={start}>
            {t.scan.startCamera}
          </button>
        </div>
      ) : (
        <div className="webcam">
          <div className="scan-stage">
            <video ref={video} autoPlay playsInline muted />
            {preview && <Overlay alt={t.scan.livePredictions} pills={preview.pills} live />}
          </div>
          <div className="inline-actions">
            <button type="button" className="btn btn-primary" onClick={capture}>
              <Icon name="camera" size={16} />
              {t.scan.capture}
            </button>
            <label className="check">
              <input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} />
              {t.scan.livePredictions}
            </label>
            {preview && (
              <span className="muted" aria-live="polite">
                {t.scan.liveCount(preview.pills.length, Math.round(preview.inference_ms))}
              </span>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function DemoPanel({ onImage }: { onImage: (file: Blob, name: string) => void }) {
  const t = useT();
  const gallery = useQuery((signal) => api.demoImages(signal), []);
  const [loading, setLoading] = useState<number | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const pick = async (image: DemoImage) => {
    setLoading(image.id);
    setProblem(null);
    try {
      onImage(await api.demoImage(image), `demo-${image.id}.jpg`);
    } catch (failure) {
      setProblem(errorMessage(failure));
    } finally {
      setLoading(null);
    }
  };

  if (gallery.error) return <Alert>{gallery.error}</Alert>;
  if (!gallery.data) return <Spinner label={t.scan.loadingDemos} />;
  if (gallery.data.items.length === 0) {
    return <Alert kind="info">{t.scan.noDemos}</Alert>;
  }
  return (
    <>
      {problem && <Alert>{problem}</Alert>}
      <p className="muted">
        {gallery.data.note} {t.scan.clickToIdentify}
      </p>
      <div className="gallery">
        {gallery.data.items.map((image, index) => (
          <button
            type="button"
            key={image.id}
            className="gallery-item"
            style={staggerIndex(index)}
            onClick={() => pick(image)}
            disabled={loading !== null}
            data-testid={`demo-${image.id}`}
          >
            <img src={image.thumbnail_url} alt={t.scan.demoAlt(image.id + 1)} loading="lazy" />
            <span className="gallery-caption">
              {loading === image.id
                ? t.common.loadingShort
                : t.scan.shows(image.expected_name || t.scan.classN(image.class_id))}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

/** Search the 150 classes by name, ingredient or imprint, to correct an identification. */
function PillSearch({ onPick }: { onPick: (pill: PillCandidate) => void }) {
  const t = useT();
  const [text, setText] = useState("");
  const q = useDebounced(text.trim());
  const found = useQuery(
    (signal) => (q.length >= 2 ? api.pills(q, signal) : Promise.resolve(null)),
    [q],
  );
  return (
    <div className="pill-search">
      <label className="search-box">
        <Icon name="search" />
        <input
          type="search"
          placeholder={t.scan.searchPlaceholder}
          aria-label={t.scan.searchLabel}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      {found.error && <Alert>{found.error}</Alert>}
      {found.data && (
        <ul className="search-results">
          {found.data.items.map((pill) => (
            <li key={pill.class_id}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  onPick({ ...pill, probability: Number.NaN });
                  setText("");
                }}
              >
                <span className="cell-title">{pill.name}</span>
                <span className="cell-sub">
                  {[pill.imprint && t.scan.imprint(pill.imprint), pill.color, pill.shape]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
          {found.data.items.length === 0 && <li className="muted">{t.scan.noMatch(q)}</li>}
        </ul>
      )}
    </div>
  );
}

/** One detected pill: top-5 to choose from, search for another, confirm. */
function PillChoice({
  pill,
  index,
  confirmed,
  onConfirm,
}: {
  pill: ScannedPill;
  index: number;
  confirmed: boolean;
  onConfirm: (choice: PillCandidate) => void;
}) {
  const t = useT();
  const [choice, setChoice] = useState<PillCandidate>(pill.candidates[0]);
  const [picked, setPicked] = useState<PillCandidate | null>(null);
  const options = picked ? [picked, ...pill.candidates] : pill.candidates;

  return (
    <article className={`card pill-card${pill.needs_confirmation ? " pill-card-warn" : ""}`}>
      <header className="pill-card-head">
        <span className="pill-number">{index + 1}</span>
        <div>
          <h3>{pill.candidates[0].name}</h3>
          <p className="muted">
            {t.scan.mostLikely(
              percent(pill.candidates[0].probability),
              percent(pill.detection_confidence),
            )}
          </p>
        </div>
        {pill.needs_confirmation ? (
          <Badge tone="warn">{t.scan.pleaseConfirm}</Badge>
        ) : (
          <Badge tone="active">{t.scan.highConfidence}</Badge>
        )}
      </header>
      {pill.needs_confirmation && (
        <p className="pill-note">
          <Icon name="alert" size={16} /> {t.scan.unsure}
        </p>
      )}
      <fieldset className="candidates">
        <legend className="sr-only">{t.scan.possibleFor(index + 1)}</legend>
        {options.map((candidate) => {
          const searched = Number.isNaN(candidate.probability);
          return (
            <label
              key={`${candidate.class_id}-${searched}`}
              className={choice.class_id === candidate.class_id ? "candidate candidate-on" : "candidate"}
            >
              <input
                type="radio"
                name={`pill-${index}`}
                checked={choice.class_id === candidate.class_id}
                onChange={() => setChoice(candidate)}
              />
              <span className="candidate-text">
                <span className="cell-title">{candidate.name}</span>
                <span className="cell-sub">
                  {candidate.active_ingredients.length
                    ? candidate.active_ingredients.join(" + ")
                    : t.scan.noIngredientInDb}
                </span>
              </span>
              {searched ? (
                <span className="muted">{t.scan.chosenBySearch}</span>
              ) : (
                <span className="prob" title={t.common.modelProbability}>
                  <span className="prob-bar">
                    <span style={{ width: `${candidate.probability * 100}%` }} />
                  </span>
                  {percent(candidate.probability)}
                </span>
              )}
            </label>
          );
        })}
      </fieldset>
      <PillSearch
        onPick={(candidate) => {
          setPicked(candidate);
          setChoice(candidate);
        }}
      />
      <div className="form-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={confirmed}
          onClick={() => onConfirm(choice)}
        >
          <Icon name="check" size={16} />
          {confirmed ? t.scan.added : t.scan.confirmPill}
        </button>
      </div>
    </article>
  );
}

const SEVERITY_TONE: Record<Severity, string> = {
  Major: "danger",
  Moderate: "warn",
  Minor: "info",
  Unknown: "neutral",
};

function PairCard({ pair, index }: { pair: InteractionPair; index: number }) {
  const t = useT();
  const tone = pair.highest_severity ? SEVERITY_TONE[pair.highest_severity] : "none";
  return (
    <article className={`card pair-card pair-${tone}`} style={staggerIndex(index)}>
      <header className="pair-head">
        <h3>
          {pair.item_a.label} <span className="muted">+</span> {pair.item_b.label}
        </h3>
        {pair.highest_severity && (
          <Badge tone={SEVERITY_TONE[pair.highest_severity]}>
            {t.severity[pair.highest_severity]}
          </Badge>
        )}
      </header>
      {pair.message && <p className="pair-message">{pair.message}</p>}
      {pair.interactions.length > 0 && (
        <ul className="interaction-list">
          {pair.interactions.map((found) => (
            <li key={`${found.ingredient_a}-${found.ingredient_b}`}>
              <strong>
                {found.ingredient_a} + {found.ingredient_b}
              </strong>
              : {found.severity === "Unknown" ? t.severity.unknownLong : t.severity[found.severity]}.{" "}
              {found.description}{" "}
              <a href={found.source.url} target="_blank" rel="noreferrer">
                {t.common.source(found.source.title)}
              </a>
            </li>
          ))}
        </ul>
      )}
      {pair.shared_ingredients.length > 0 && (
        <p className="pill-note">
          <Icon name="alert" size={16} />{" "}
          {t.scan.sameIngredient(pair.shared_ingredients.join(", "))}
        </p>
      )}
    </article>
  );
}

function InteractionReport({ report }: { report: InteractionsResult }) {
  const t = useT();
  const counts = report.pairs.reduce<Record<string, number>>((total, pair) => {
    const key = pair.highest_severity ?? "none";
    total[key] = (total[key] ?? 0) + 1;
    return total;
  }, {});
  return (
    <section className="report" aria-live="polite">
      <div className={`report-summary report-${report.highest_severity ? SEVERITY_TONE[report.highest_severity] : "none"}`}>
        <p className="report-message">{report.message}</p>
        <span className="badge-row">
          {(["Major", "Moderate", "Minor", "Unknown"] as Severity[]).map(
            (severity) =>
              counts[severity] && (
                <Badge key={severity} tone={SEVERITY_TONE[severity]}>
                  {t.severity.count(counts[severity], t.severity[severity])}
                </Badge>
              ),
          )}
        </span>
      </div>
      {report.pairs.map((pair, index) => (
        <PairCard key={`${pair.item_a.label}|${pair.item_b.label}`} pair={pair} index={index} />
      ))}
      <SourceList sources={report.sources} />
      <Disclaimer text={report.disclaimer} />
    </section>
  );
}

/** Save a report: the pills of "My pills", and the chat answers the user ticks. */
function SaveReportDialog({
  pills,
  answers,
  onClose,
}: {
  pills: number[];
  answers: ChatResult[];
  onClose: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(answers.map((_, i) => i)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chat = answers.filter((_, i) => chosen.has(i));
  const enough = pills.length >= 2 || chat.length > 0;

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!enough) return;
    setBusy(true);
    setError(null);
    try {
      const report = await api.my.createReport({ title, pills, chat: chat.map(excerptOf) });
      navigate(`/reports/${report.id}`);
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  };

  const toggle = (index: number) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <Modal title={t.report.createTitle} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <p className="muted">{t.report.createText}</p>
        <TextField
          label={t.report.titleLabel}
          value={title}
          maxLength={120}
          placeholder={t.report.titlePlaceholder}
          onChange={setTitle}
        />
        <fieldset className="answer-picks">
          <legend>{t.report.includeAnswers}</legend>
          {answers.length === 0 ? (
            <p className="hint">{t.report.noAnswers}</p>
          ) : (
            answers.map((answer, index) => (
              <label key={index} className="answer-pick">
                <input type="checkbox" checked={chosen.has(index)} onChange={() => toggle(index)} />
                <span>{answer.question}</span>
              </label>
            ))
          )}
        </fieldset>
        {!enough && <p className="hint">{t.report.needSomething}</p>}
        {error && <Alert>{error}</Alert>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            {t.common.cancel}
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !enough}>
            {busy && <span className="btn-spinner" aria-hidden="true" />}
            <Icon name="file" size={16} />
            {t.report.save}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function ScanPage() {
  const t = useT();
  const [mode, setMode] = useState<Mode>("upload");
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "My pills" lives in the account (D83): it is still there after a reload or sign-out.
  const [mine, setMine] = useState<SavedPill[] | null>(null);
  // Which pill of which photo was confirmed as which class, for the "Added" buttons.
  const [confirmedAs, setConfirmedAs] = useState<Map<string, number>>(() => new Map());
  const [report, setReport] = useState<InteractionsResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [answers, setAnswers] = useState<ChatResult[]>([]);
  const [saving, setSaving] = useState(false);
  const resultRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    api.my.medicines(controller.signal).then(
      (list) => setMine(list.items),
      (failure: unknown) => {
        if (controller.signal.aborted) return;
        setMine([]);
        setError(errorMessage(failure));
      },
    );
    return () => controller.abort();
  }, []);

  // Release the previous photo's memory when it is replaced or the page is left.
  useEffect(() => () => {
    if (photo) URL.revokeObjectURL(photo.url);
  }, [photo]);

  const identify = async (image: Blob, name: string) => {
    setScanning(true);
    setError(null);
    setResult(null);
    setPhoto({ url: URL.createObjectURL(image), name });
    try {
      setResult(await api.scan(image, name));
      window.setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setScanning(false);
    }
  };

  const confirm = async (choice: PillCandidate, pillIndex: number) => {
    const key = `${photo?.url}#${pillIndex}`;
    setError(null);
    try {
      const probability = Number.isNaN(choice.probability) ? null : choice.probability;
      setMine((await api.my.addMedicine(choice.class_id, probability)).items);
      setConfirmedAs((current) => new Map(current).set(key, choice.class_id));
      setReport(null);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  const remove = async (classId: number) => {
    setError(null);
    try {
      setMine((await api.my.removeMedicine(classId)).items);
      setReport(null);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  const clearAll = async () => {
    if (!window.confirm(t.scan.confirmClear)) return;
    setError(null);
    try {
      await api.my.clearMedicines();
      setMine([]);
      setReport(null);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  const isConfirmed = (key: string) => {
    const classId = confirmedAs.get(key);
    return classId !== undefined && (mine ?? []).some((item) => item.class_id === classId);
  };

  // The list keeps each product once (front and back of one pill are one medicine).
  const classIds = (mine ?? []).map((item) => item.class_id);

  const check = async () => {
    setChecking(true);
    setError(null);
    try {
      setReport(await api.interactions(classIds));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <header className="page-header">
        <div className="page-title">
          <span className="page-icon">
            <Icon name="scan" size={24} />
          </span>
          <div>
            <h1>{t.scan.title}</h1>
            <p className="muted">{t.scan.subtitle}</p>
          </div>
        </div>
      </header>

      <Disclaimer />

      <section className="card scan-input" aria-label={t.scan.photoLabel}>
        <div className="segmented" role="tablist" aria-label={t.scan.photoSource}>
          {MODES.map((item) => (
            <button
              type="button"
              role="tab"
              key={item.mode}
              aria-selected={mode === item.mode}
              className={mode === item.mode ? "segment segment-on" : "segment"}
              onClick={() => setMode(item.mode)}
            >
              <Icon name={item.icon} size={16} />
              {modeLabel(t, item.mode)}
            </button>
          ))}
        </div>
        {mode === "upload" && <UploadPanel onImage={identify} />}
        {mode === "webcam" && <WebcamPanel onImage={identify} />}
        {mode === "demo" && <DemoPanel onImage={identify} />}
      </section>

      {error && <Alert>{error}</Alert>}

      {photo && (
        <section className="scan-result" ref={resultRef} aria-label={t.scan.resultLabel} aria-busy={scanning}>
          <div className="card scan-photo">
            <div className="scan-stage">
              <img src={photo.url} alt={t.scan.photoAlt(photo.name)} />
              {result && <Overlay alt={t.scan.detectedAlt} pills={result.pills} />}
              {scanning && (
                <div className="scan-busy">
                  <Spinner label={t.scan.identifying} />
                </div>
              )}
            </div>
            {result && (
              <p className="muted scan-meta">
                {t.scan.meta(
                  result.pills.length,
                  result.image_width,
                  result.image_height,
                  Math.round(result.inference_ms),
                  percent(result.confirm_threshold),
                )}
              </p>
            )}
          </div>
          <div className="scan-pills">
            {result?.message && <Alert kind="info">{result.message}</Alert>}
            {result?.pills.map((pill, index) => (
              <PillChoice
                key={`${photo.url}-${index}`}
                pill={pill}
                index={index}
                confirmed={isConfirmed(`${photo.url}#${index}`)}
                onConfirm={(choice) => void confirm(choice, index)}
              />
            ))}
            {result && <SourceList sources={result.sources} />}
          </div>
        </section>
      )}

      <section className="card my-pills" aria-label={t.scan.myPills}>
        <header className="pill-card-head">
          <h2>{t.scan.myPills}</h2>
          <span className="muted">{mine && t.scan.myPillsCount(mine.length)}</span>
          {mine && mine.length > 0 && (
            <button type="button" className="btn btn-ghost btn-ghost-danger btn-sm" onClick={clearAll}>
              {t.scan.clearAll}
            </button>
          )}
        </header>
        {mine === null ? (
          <p className="muted chat-thinking">
            <span className="btn-spinner" aria-hidden="true" />
            {t.scan.loadingSaved}
          </p>
        ) : mine.length === 0 ? (
          <p className="muted">{t.scan.myPillsEmpty}</p>
        ) : (
          <ul className="chip-list">
            {mine.map((item) => (
              <li key={item.class_id} className="chip">
                <span>
                  <strong>{item.name}</strong>
                  <span className="cell-sub">
                    {item.active_ingredients.join(" + ") || t.scan.noIngredient}
                    {item.probability !== null
                      ? ` · ${percent(item.probability)}`
                      : ` · ${t.scan.chosenBySearch}`}
                  </span>
                </span>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={t.scan.removeItem(item.name)}
                  onClick={() => void remove(item.class_id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={classIds.length < 2 || checking}
            onClick={check}
          >
            {checking && <span className="btn-spinner" aria-hidden="true" />}
            {t.scan.checkInteractions}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={classIds.length < 2 && answers.length === 0}
            onClick={() => setSaving(true)}
          >
            <Icon name="file" size={16} />
            {t.scan.saveReport}
          </button>
        </div>
        {report && <InteractionReport report={report} />}
      </section>

      <ChatPanel
        pills={mine ?? []}
        onAnswer={(answer) =>
          // Only answers the server sealed can go in a report (D83).
          answer.signature && setAnswers((current) => [...current, answer])
        }
      />

      {saving && (
        <SaveReportDialog pills={classIds} answers={answers} onClose={() => setSaving(false)} />
      )}
    </>
  );
}
