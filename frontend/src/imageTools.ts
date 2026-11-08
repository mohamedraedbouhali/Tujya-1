// Prepare photos and signatures in the browser before upload: turned upright (phone photos
// carry their rotation as metadata), cropped or shrunk, and small. The server checks and
// re-encodes them again; this only keeps uploads fast.

import { messages } from "./i18n";

async function loadImage(file: Blob): Promise<ImageBitmap> {
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error(messages().errors.unreadableImage);
  }
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob ? resolve(blob) : reject(new Error(messages().errors.imageNotPrepared)),
      type,
      quality,
    );
  });
}

function context(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error(messages().errors.noImageSupport);
  return ctx;
}

/** The centre square of a photo, at most `size` pixels wide, as a JPEG. */
export async function squarePhoto(file: Blob, size = 512): Promise<Blob> {
  const bitmap = await loadImage(file);
  const side = Math.min(bitmap.width, bitmap.height);
  const out = Math.min(size, side);
  const canvas = document.createElement("canvas");
  canvas.width = out;
  canvas.height = out;
  const ctx = context(canvas);
  ctx.fillStyle = "#ffffff"; // a transparent PNG becomes white, not black, in a JPEG
  ctx.fillRect(0, 0, out, out);
  ctx.imageSmoothingQuality = "high";
  const left = (bitmap.width - side) / 2;
  const top = (bitmap.height - side) / 2;
  ctx.drawImage(bitmap, left, top, side, side, 0, 0, out, out);
  bitmap.close();
  return canvasToBlob(canvas, "image/jpeg", 0.9);
}

/** An uploaded picture of a signature, shrunk to fit 1200 x 400, as a PNG. */
export async function signatureFromFile(file: Blob): Promise<Blob> {
  const bitmap = await loadImage(file);
  const scale = Math.min(1, 1200 / bitmap.width, 400 / bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = context(canvas);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvasToBlob(canvas, "image/png");
}

/** The drawn part of a transparent canvas plus a margin, as a PNG; null if it is empty. */
export async function trimmedPng(source: HTMLCanvasElement, margin = 12): Promise<Blob | null> {
  const { width, height } = source;
  const pixels = context(source).getImageData(0, 0, width, height).data;
  let top = height;
  let left = width;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (pixels[(y * width + x) * 4 + 3] === 0) continue;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
    }
  }
  if (right < 0) return null;
  left = Math.max(0, left - margin);
  top = Math.max(0, top - margin);
  right = Math.min(width - 1, right + margin);
  bottom = Math.min(height - 1, bottom + margin);

  const canvas = document.createElement("canvas");
  canvas.width = right - left + 1;
  canvas.height = bottom - top + 1;
  context(canvas).drawImage(
    source,
    left,
    top,
    canvas.width,
    canvas.height,
    0,
    0,
    canvas.width,
    canvas.height,
  );
  return canvasToBlob(canvas, "image/png");
}
