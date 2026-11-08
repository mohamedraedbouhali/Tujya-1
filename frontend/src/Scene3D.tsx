import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "./motion";
import type { SceneVariant } from "./three/pillScene";

/**
 * The animated 3D pills (src/three/pillScene.ts). three.js is loaded only on the pages that
 * show it, as its own chunk. Without WebGL the space shows a still brand-coloured glow.
 * Purely decorative: hidden from screen readers.
 */
export function Scene3D({ variant = "hero", className = "" }: { variant?: SceneVariant; className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reducedMotion = usePrefersReducedMotion();
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let cancelled = false;
    let handle: { destroy(): void } | null = null;
    import("./three/pillScene")
      .then(({ createPillScene }) => {
        if (cancelled || !canvas.current) return;
        handle = createPillScene(canvas.current, { variant, reducedMotion });
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("failed");
      });
    return () => {
      cancelled = true;
      handle?.destroy();
    };
  }, [variant, reducedMotion]);

  return (
    <div className={`scene3d scene3d-${variant} scene3d-${state} ${className}`} aria-hidden="true">
      <span className="scene3d-glow" />
      {state !== "failed" && <canvas ref={canvas} />}
    </div>
  );
}
