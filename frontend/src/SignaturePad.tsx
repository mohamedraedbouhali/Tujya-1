import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useT } from "./i18n";
import { Icon } from "./icons";
import { trimmedPng } from "./imageTools";

const INK = "#0c2f4a"; // dark navy, drawn on white "paper" in both themes
const LINE_WIDTH = 2.6; // in CSS pixels

interface Point {
  x: number;
  y: number;
}

interface SignaturePadProps {
  busy: boolean;
  onSave: (image: Blob) => void;
  onCancel: () => void;
}

/** Draw a signature with a mouse, pen or finger. Saves only the drawn part, as a PNG. */
export function SignaturePad({ busy, onSave, onCancel }: SignaturePadProps) {
  const t = useT();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const last = useRef<Point | null>(null);
  const lastMid = useRef<Point | null>(null);
  const [hasInk, setHasInk] = useState(false);

  // Match the canvas to its size on screen and the screen's pixel density, for sharp lines.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const box = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * ratio);
    canvas.height = Math.round(box.height * ratio);
  }, []);

  const pen = (canvas: HTMLCanvasElement) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const scale = canvas.width / canvas.getBoundingClientRect().width;
    ctx.strokeStyle = INK;
    ctx.fillStyle = INK;
    ctx.lineWidth = LINE_WIDTH * scale;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    return ctx;
  };

  const pointOf = (event: PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = event.currentTarget;
    const box = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - box.left) * (canvas.width / box.width),
      y: (event.clientY - box.top) * (canvas.height / box.height),
    };
  };

  const start = (event: PointerEvent<HTMLCanvasElement>) => {
    if (busy || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const ctx = pen(event.currentTarget);
    if (!ctx) return;
    const point = pointOf(event);
    ctx.beginPath(); // a dot, so a single tap leaves a mark
    ctx.arc(point.x, point.y, ctx.lineWidth / 2, 0, Math.PI * 2);
    ctx.fill();
    last.current = point;
    lastMid.current = point;
    setHasInk(true);
  };

  const draw = (event: PointerEvent<HTMLCanvasElement>) => {
    const from = last.current;
    const fromMid = lastMid.current;
    if (!from || !fromMid) return;
    const ctx = pen(event.currentTarget);
    if (!ctx) return;
    const point = pointOf(event);
    const mid = { x: (from.x + point.x) / 2, y: (from.y + point.y) / 2 };
    // Curves through the midpoints: smooth lines even when the pointer moves fast.
    ctx.beginPath();
    ctx.moveTo(fromMid.x, fromMid.y);
    ctx.quadraticCurveTo(from.x, from.y, mid.x, mid.y);
    ctx.stroke();
    last.current = point;
    lastMid.current = mid;
  };

  const end = () => {
    last.current = null;
    lastMid.current = null;
  };

  const clear = () => {
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    setHasInk(false);
  };

  const save = async () => {
    if (!canvasRef.current) return;
    const image = await trimmedPng(canvasRef.current);
    if (image) onSave(image);
  };

  return (
    <div className="signature-pad">
      <div className="signature-pad-paper">
        <canvas
          ref={canvasRef}
          className="signature-pad-canvas"
          aria-label={t.signaturePad.label}
          onPointerDown={start}
          onPointerMove={draw}
          onPointerUp={end}
          onPointerCancel={end}
        />
        {!hasInk && (
          <span className="signature-pad-placeholder" aria-hidden="true">
            {t.signaturePad.placeholder}
          </span>
        )}
      </div>
      <div className="signature-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={clear} disabled={!hasInk || busy}>
          {t.signaturePad.clear}
        </button>
        <span className="signature-actions-gap" />
        <button type="button" className="btn btn-secondary btn-sm" onClick={onCancel} disabled={busy}>
          {t.common.cancel}
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={save}
          disabled={!hasInk || busy}
        >
          {busy ? <span className="btn-spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}
          {t.signaturePad.save}
        </button>
      </div>
    </div>
  );
}
