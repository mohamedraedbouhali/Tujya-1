// The 3D scene behind the landing page, the sign-in page and the home banner (three.js).
//
// What it shows is what Tujya does: glossy capsules and tablets in the logo's colours orbit
// a big capsule; a detection box, a scan line and scan waves play the vision step; glowing
// links with pulses travelling between pills play the interaction check; every few seconds
// the big capsule opens and releases its active ingredient as a burst of particles; and a
// small molecule stands for that ingredient. Everything is built from code: no model or
// texture is downloaded. On the landing page the scene also turns as the page scrolls.
//
// Cost control: the canvas renders only while it is on screen and the tab is visible, the
// pixel ratio is capped at 2, and a visitor who prefers reduced motion gets one still frame.
// destroy() frees every GPU resource.

import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export type SceneVariant = "hero" | "compact";

export interface SceneOptions {
  variant: SceneVariant;
  reducedMotion: boolean;
}

export interface SceneHandle {
  destroy(): void;
}

const PALETTE = {
  navy: "#0e3a63",
  blue: "#1d6fae",
  sky: "#5fb0e6",
  teal: "#2fa3a8",
  green: "#87ba55",
  lime: "#b9de8a",
  white: "#f3f6f9",
  cream: "#f6efd9",
  amber: "#f2b544",
};

const CYCLE = 8; // seconds between two openings of the big capsule

// ---------------------------------------------------------------- geometry

/** Half of a two-piece capsule as a lathe profile: cylinder from the seam, then a dome. */
function capsuleHalf(radius: number, length: number, flip: boolean): THREE.LatheGeometry {
  const points: THREE.Vector2[] = [new THREE.Vector2(radius, 0)];
  const half = length / 2;
  points.push(new THREE.Vector2(radius, half));
  const steps = 14;
  for (let i = 1; i <= steps; i += 1) {
    const angle = (i / steps) * (Math.PI / 2);
    points.push(new THREE.Vector2(Math.cos(angle) * radius, half + Math.sin(angle) * radius));
  }
  points[points.length - 1].x = 0.0001;
  if (flip) points.forEach((p) => (p.y = -p.y));
  if (flip) points.reverse(); // keep the faces pointing outwards
  return new THREE.LatheGeometry(points, 48);
}

/** A round tablet with a domed face and rounded edge, as a lathe profile. */
function tabletGeometry(radius: number, thickness: number): THREE.LatheGeometry {
  const points: THREE.Vector2[] = [];
  const edge = thickness * 0.5;
  const dome = thickness * 0.22;
  const steps = 10;
  for (let i = 0; i <= steps; i += 1) {
    const x = (i / steps) * (radius - edge);
    points.push(new THREE.Vector2(x, edge + dome * (1 - (x / (radius - edge)) ** 2)));
  }
  for (let i = 1; i < steps; i += 1) {
    const angle = Math.PI / 2 - (i / steps) * Math.PI;
    points.push(new THREE.Vector2(radius - edge + Math.cos(angle) * edge, Math.sin(angle) * edge));
  }
  for (let i = steps; i >= 0; i -= 1) {
    const x = (i / steps) * (radius - edge);
    points.push(new THREE.Vector2(x, -edge - dome * (1 - (x / (radius - edge)) ** 2)));
  }
  points[0].x = 0.0001;
  points[points.length - 1].x = 0.0001;
  return new THREE.LatheGeometry(points.reverse(), 56);
}

function glossy(color: string): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color,
    roughness: 0.22,
    metalness: 0,
    clearcoat: 1,
    clearcoatRoughness: 0.12,
  });
}

function chalky(color: string): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color,
    roughness: 0.62,
    metalness: 0,
    clearcoat: 0.35,
    clearcoatRoughness: 0.4,
    sheen: 0.4,
  });
}

interface Capsule {
  group: THREE.Group;
  upper: THREE.Mesh;
  lower: THREE.Mesh;
  rest: number; // the halves' resting offset from the seam
}

function capsule(radius: number, length: number, top: string, bottom: string): Capsule {
  const group = new THREE.Group();
  const rest = length * 0.06; // the cap slides over the body, like a real capsule
  const upper = new THREE.Mesh(capsuleHalf(radius * 1.035, length, false), glossy(top));
  upper.position.y = -rest;
  const lower = new THREE.Mesh(capsuleHalf(radius, length, true), glossy(bottom));
  lower.position.y = rest;
  group.add(upper, lower);
  return { group, upper, lower, rest };
}

function tablet(radius: number, color: string): THREE.Group {
  const group = new THREE.Group();
  const body = new THREE.Mesh(tabletGeometry(radius, radius * 0.42), chalky(color));
  const score = new THREE.Mesh(
    new THREE.BoxGeometry(radius * 1.5, radius * 0.03, radius * 0.06),
    new THREE.MeshStandardMaterial({ color: "#c9d2db", roughness: 0.8 }),
  );
  score.position.y = radius * 0.3;
  group.add(body, score);
  return group;
}

function molecule(): THREE.Group {
  const group = new THREE.Group();
  const atom = new THREE.SphereGeometry(0.14, 24, 16);
  const atoms = [glossy(PALETTE.white), glossy(PALETTE.teal), glossy(PALETTE.green)];
  const bond = new THREE.MeshStandardMaterial({ color: "#9fb4c7", roughness: 0.4 });
  const ring: THREE.Vector3[] = [];
  for (let i = 0; i < 6; i += 1) {
    const angle = (i / 6) * Math.PI * 2;
    ring.push(new THREE.Vector3(Math.cos(angle) * 0.6, Math.sin(angle) * 0.6, 0));
  }
  const side = [0, 2, 4].map((i) => ring[i].clone().multiplyScalar(1.85));
  [...ring, ...side].forEach((position, index) => {
    const mesh = new THREE.Mesh(atom, atoms[index < 6 ? index % 2 : 2]);
    mesh.position.copy(position);
    if (index >= 6) mesh.scale.setScalar(1.15);
    group.add(mesh);
  });
  const link = (a: THREE.Vector3, b: THREE.Vector3) => {
    const cylinder = new THREE.Mesh(
      new THREE.CylinderGeometry(0.035, 0.035, a.distanceTo(b), 10),
      bond,
    );
    cylinder.position.copy(a).add(b).multiplyScalar(0.5);
    cylinder.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    group.add(cylinder);
  };
  ring.forEach((point, i) => link(point, ring[(i + 1) % 6]));
  [0, 2, 4].forEach((i, k) => link(ring[i], side[k]));
  return group;
}

/** A soft round dot, drawn once on a small canvas, for particles, pulses and glows. */
function dotTexture(): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d");
  if (context) {
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.35, "rgba(255,255,255,0.55)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** A horizontal glowing bar that fades at both ends: the scan line. */
function scanTexture(): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 16;
  const context = canvas.getContext("2d");
  if (context) {
    const across = context.createLinearGradient(0, 0, 256, 0);
    across.addColorStop(0, "rgba(120,220,215,0)");
    across.addColorStop(0.5, "rgba(170,240,235,1)");
    across.addColorStop(1, "rgba(120,220,215,0)");
    context.fillStyle = across;
    context.fillRect(0, 0, 256, 16);
    const fade = context.createLinearGradient(0, 0, 0, 16);
    fade.addColorStop(0, "rgba(0,0,0,1)");
    fade.addColorStop(0.5, "rgba(0,0,0,0)");
    fade.addColorStop(1, "rgba(0,0,0,1)");
    context.globalCompositeOperation = "destination-out";
    context.fillStyle = fade;
    context.fillRect(0, 0, 256, 16);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** The label of the detection box ("pill detected"), drawn on a canvas. */
function labelTexture(text: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 112;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "rgba(47,163,168,0.92)";
    context.beginPath();
    context.roundRect(4, 4, 504, 104, 30);
    context.fill();
    context.fillStyle = "#ffffff";
    context.font = "600 52px 'Inter Variable', 'Segoe UI', sans-serif";
    context.textBaseline = "middle";
    context.fillText(text, 36, 58);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

/** Four L-shaped corners around a w x h box: the detector's bounding box. */
function bracketGeometry(w: number, h: number, arm: number): THREE.BufferGeometry {
  const x = w / 2;
  const y = h / 2;
  const corners = [
    [-x, y - arm, -x, y, -x + arm, y],
    [x - arm, y, x, y, x, y - arm],
    [x, -y + arm, x, -y, x - arm, -y],
    [-x + arm, -y, -x, -y, -x, -y + arm],
  ];
  const positions: number[] = [];
  for (const [ax, ay, bx, by, cx, cy] of corners) {
    positions.push(ax, ay, 0, bx, by, 0, bx, by, 0, cx, cy, 0);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

// ---------------------------------------------------------------- scene

interface Floater {
  object: THREE.Object3D;
  base: THREE.Vector3;
  spin: THREE.Vector3;
  bob: number;
  phase: number;
  delay: number;
  scale: number;
  /** Small pills circle the big capsule; the capsule and the molecule stay put. */
  orbit?: { angle: number; radius: number; speed: number };
}

const easeOutBack = (t: number) => 1 + 2.5 * (t - 1) ** 3 + 1.5 * (t - 1) ** 2;
const smooth = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
};

export function createPillScene(canvas: HTMLCanvasElement, options: SceneOptions): SceneHandle {
  const host = canvas.parentElement ?? canvas;
  const compact = options.variant === "compact";
  const motion = options.reducedMotion ? 0 : 1;

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, 0.04).texture;
  scene.environment = environment;

  const cameraZ = compact ? 11 : 15;
  const camera = new THREE.PerspectiveCamera(compact ? 38 : 34, 1, 0.1, 100);
  camera.position.set(0, 0, cameraZ);

  // Light: a cool key, a green rim and a blue fill, so the gloss picks up the brand colours.
  scene.add(new THREE.HemisphereLight("#dfefff", "#0b2236", 0.7));
  const key = new THREE.DirectionalLight("#ffffff", 1.6);
  key.position.set(4, 6, 8);
  const rim = new THREE.PointLight(PALETTE.green, 40, 30);
  rim.position.set(-6, -3, 4);
  const fill = new THREE.PointLight(PALETTE.sky, 50, 30);
  fill.position.set(6, 2, -2);
  scene.add(key, rim, fill);

  const world = new THREE.Group();
  scene.add(world);
  const dot = dotTexture();

  // ------------------------------------------------ the big capsule and its vision overlay

  const hero = new THREE.Group();
  world.add(hero);
  const big = capsule(0.82, 2.5, PALETTE.blue, PALETTE.green);
  big.group.rotation.z = -0.55;
  hero.add(big.group);

  // What comes out when the capsule opens: a glow at the seam and a burst of particles.
  const core = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: dot,
      color: PALETTE.lime,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  core.scale.setScalar(1.6);
  big.group.add(core);
  const burstCount = compact ? 50 : 95;
  const burstDirections: THREE.Vector3[] = [];
  const burstPositions = new Float32Array(burstCount * 3);
  const burstGeometry = new THREE.BufferGeometry();
  burstGeometry.setAttribute("position", new THREE.BufferAttribute(burstPositions, 3));
  const burst = new THREE.Points(
    burstGeometry,
    new THREE.PointsMaterial({
      map: dot,
      color: PALETTE.lime,
      size: 0.24,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  big.group.add(burst);

  const teal = new THREE.Color(PALETTE.teal);
  const boxW = 3.1;
  const boxH = 3.6;
  const brackets = new THREE.LineSegments(
    bracketGeometry(boxW, boxH, 0.55),
    new THREE.LineBasicMaterial({ color: teal, transparent: true, opacity: 0.95 }),
  );
  brackets.position.z = 1.2;
  hero.add(brackets);

  const label = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: labelTexture("pill detected"),
      transparent: true,
      depthWrite: false,
    }),
  );
  label.scale.set(1.75, 0.38, 1);
  label.position.set(-boxW / 2 + 0.88, boxH / 2 + 0.36, 1.2);
  hero.add(label);

  const scan = new THREE.Mesh(
    new THREE.PlaneGeometry(boxW * 1.05, 0.14),
    new THREE.MeshBasicMaterial({
      map: scanTexture(),
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  scan.position.z = 1.25;
  hero.add(scan);

  const ringMaterial = new THREE.MeshBasicMaterial({
    color: PALETTE.sky,
    transparent: true,
    opacity: 0.55,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const rings = [2.35, 2.75].map((radius, index) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.012, 8, 220), ringMaterial);
    ring.rotation.set(1.15 + index * 0.35, 0.2 - index * 0.5, 0);
    hero.add(ring);
    return ring;
  });

  // Scan waves: flat rings that grow from the capsule and fade, one after the other.
  const waves = [0, 0.5].map((offset) => {
    const wave = new THREE.Mesh(
      new THREE.RingGeometry(0.97, 1, 128),
      new THREE.MeshBasicMaterial({
        color: PALETTE.teal,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    wave.position.z = -0.4;
    hero.add(wave);
    return { wave, offset };
  });

  // ------------------------------------------------ the pills around it

  const floaters: Floater[] = [
    {
      object: hero,
      base: new THREE.Vector3(),
      spin: new THREE.Vector3(),
      bob: 0.12,
      phase: 0,
      delay: 0,
      scale: 1,
    },
  ];
  const kinds = compact
    ? [
        { kind: "capsule", a: PALETTE.white, b: PALETTE.blue },
        { kind: "tablet", a: PALETTE.white },
        { kind: "capsule", a: PALETTE.green, b: PALETTE.white },
        { kind: "tablet", a: PALETTE.cream },
        { kind: "capsule", a: PALETTE.amber, b: PALETTE.white },
      ]
    : [
        { kind: "capsule", a: PALETTE.white, b: PALETTE.blue },
        { kind: "tablet", a: PALETTE.white },
        { kind: "capsule", a: PALETTE.green, b: PALETTE.white },
        { kind: "tablet", a: PALETTE.cream },
        { kind: "capsule", a: PALETTE.amber, b: PALETTE.white },
        { kind: "tablet", a: "#dbeefa" },
        { kind: "capsule", a: PALETTE.navy, b: PALETTE.sky },
        { kind: "tablet", a: PALETTE.white },
        { kind: "capsule", a: PALETTE.teal, b: PALETTE.white },
        { kind: "tablet", a: PALETTE.lime },
      ];
  let seed = 7; // the same layout on every visit
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  kinds.forEach((spec, index) => {
    const object =
      spec.kind === "capsule"
        ? capsule(0.26 + random() * 0.08, 0.75 + random() * 0.25, spec.a, spec.b ?? PALETTE.white)
            .group
        : tablet(0.36 + random() * 0.1, spec.a);
    const angle = (index / kinds.length) * Math.PI * 2 + random() * 0.4;
    const radius = (compact ? 2.9 : 3.6) + random() * (compact ? 0.6 : 1.4);
    object.rotation.set(random() * 3, random() * 3, random() * 3);
    world.add(object);
    floaters.push({
      object,
      base: new THREE.Vector3(0, 0, -0.6 - random() * 2.4),
      spin: new THREE.Vector3(random() * 0.5 - 0.25, random() * 0.6 - 0.3, random() * 0.4 - 0.2),
      bob: 0.12 + random() * 0.18,
      phase: random() * Math.PI * 2,
      delay: 0.25 + index * 0.07,
      scale: 1,
      orbit: { angle, radius, speed: 0.045 + random() * 0.03 },
    });
  });

  // The molecule (the active ingredient), top right, clear of the headline.
  if (!compact) {
    const mol = molecule();
    world.add(mol);
    floaters.push({
      object: mol,
      base: new THREE.Vector3(2.9, 2.75, -2.2),
      spin: new THREE.Vector3(0.15, 0.25, 0.05),
      bob: 0.2,
      phase: 1.3,
      delay: 0.9,
      scale: 0.9,
    });
  }

  // Interaction links between pills (indices into `floaters`: 0 is the big capsule).
  const pairs: [number, number][] = compact
    ? [
        [0, 1],
        [0, 3],
        [2, 4],
        [0, 5],
      ]
    : [
        [0, 1],
        [0, 3],
        [0, 6],
        [2, 4],
        [5, 7],
        [8, 9],
        [0, 9],
        [3, 5],
      ];
  const linkPositions = new Float32Array(pairs.length * 6);
  const linkGeometry = new THREE.BufferGeometry();
  linkGeometry.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
  const links = new THREE.LineSegments(
    linkGeometry,
    new THREE.LineBasicMaterial({
      color: PALETTE.teal,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  world.add(links);

  const pulsePositions = new Float32Array(pairs.length * 3);
  const pulseGeometry = new THREE.BufferGeometry();
  pulseGeometry.setAttribute("position", new THREE.BufferAttribute(pulsePositions, 3));
  const pulses = new THREE.Points(
    pulseGeometry,
    new THREE.PointsMaterial({
      map: dot,
      color: PALETTE.lime,
      size: compact ? 0.32 : 0.36,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  world.add(pulses);

  // Particles far behind.
  const count = compact ? 220 : 520;
  const particlePositions = new Float32Array(count * 3);
  const particleColors = new Float32Array(count * 3);
  const tones = [
    new THREE.Color(PALETTE.sky),
    new THREE.Color(PALETTE.green),
    new THREE.Color("#ffffff"),
  ];
  for (let i = 0; i < count; i += 1) {
    const r = 6 + random() * 9;
    const theta = random() * Math.PI * 2;
    const phi = Math.acos(2 * random() - 1);
    particlePositions.set(
      [
        r * Math.sin(phi) * Math.cos(theta),
        r * Math.cos(phi) * 0.7,
        -Math.abs(r * Math.sin(phi) * Math.sin(theta)) - 2,
      ],
      i * 3,
    );
    const tone = tones[i % 3];
    particleColors.set([tone.r, tone.g, tone.b], i * 3);
  }
  const particleGeometry = new THREE.BufferGeometry();
  particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
  particleGeometry.setAttribute("color", new THREE.BufferAttribute(particleColors, 3));
  const particles = new THREE.Points(
    particleGeometry,
    new THREE.PointsMaterial({
      map: dot,
      size: 0.11,
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  scene.add(particles);

  // ------------------------------------------------ layout and input

  let leftSqueeze = 1; // wide hero: pills on the text side keep closer to the capsule
  let worldY = 0;
  const layout = () => {
    const rect = host.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const wide = camera.aspect > 1.15;
    leftSqueeze = !compact && wide ? 0.34 : 1;
    world.position.x = compact ? 0 : wide ? 3.4 : 0;
    worldY = compact ? 0 : wide ? 0 : 0.2;
    const fit = compact
      ? Math.min(1, camera.aspect / 0.95)
      : wide
        ? 1
        : Math.min(1, camera.aspect / 0.8);
    world.scale.setScalar(Math.max(0.62, fit));
  };
  layout();

  const pointer = { x: 0, y: 0 };
  const onPointer = (event: PointerEvent) => {
    pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (event.clientY / window.innerHeight) * 2 - 1;
  };
  let scrolled = 0; // 0 at the top of the page, 1 one screen further down
  const onScroll = () => {
    scrolled = Math.min(1, Math.max(0, window.scrollY / window.innerHeight));
  };
  if (motion) {
    window.addEventListener("pointermove", onPointer, { passive: true });
    if (!compact) window.addEventListener("scroll", onScroll, { passive: true });
  }

  // ------------------------------------------------ animation

  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const started = performance.now();

  const update = (seconds: number) => {
    const t = motion ? seconds : 4; // reduced motion: one settled frame

    floaters.forEach((floater, index) => {
      const grow = Math.min(1, Math.max(0, (t - floater.delay) / 0.9));
      floater.object.scale.setScalar(floater.scale * (grow <= 0 ? 0.0001 : easeOutBack(grow)));
      if (floater.orbit) {
        const angle = floater.orbit.angle + t * floater.orbit.speed * motion;
        floater.base.x = Math.cos(angle) * floater.orbit.radius;
        floater.base.y = Math.sin(angle) * floater.orbit.radius * 0.78;
      }
      floater.object.position.set(
        floater.base.x < 0 ? floater.base.x * leftSqueeze : floater.base.x,
        floater.base.y + Math.sin(t * 0.9 + floater.phase) * floater.bob * motion,
        floater.base.z,
      );
      if (index > 0) {
        floater.object.rotation.x += floater.spin.x * 0.01 * motion;
        floater.object.rotation.y += floater.spin.y * 0.01 * motion;
        floater.object.rotation.z += floater.spin.z * 0.01 * motion;
      }
    });

    // The big capsule turns, and every CYCLE seconds opens to release its ingredient.
    big.group.rotation.y = t * 0.35;
    big.group.rotation.x = Math.sin(t * 0.4) * 0.12;
    const phase = motion ? ((t + 3) % CYCLE) / CYCLE : 0;
    const open = smooth(0.6, 0.68, phase) * (1 - smooth(0.8, 0.9, phase));
    big.upper.position.y = -big.rest + open * 0.5;
    big.lower.position.y = big.rest - open * 0.5;
    (core.material as THREE.SpriteMaterial).opacity = open;
    core.scale.setScalar(1.2 + open * 1.6);
    const age = (phase - 0.63) * CYCLE; // seconds since the burst began
    const burstMaterial = burst.material as THREE.PointsMaterial;
    if (age >= 0 && age < 2) {
      if (burstDirections.length === 0) {
        for (let i = 0; i < burstCount; i += 1) {
          burstDirections.push(
            new THREE.Vector3(random() - 0.5, random() - 0.5, random() - 0.5)
              .normalize()
              .multiplyScalar(0.8 + random() * 1.4),
          );
        }
      }
      const reach = 1 - (1 - age / 2) ** 3;
      burstDirections.forEach((direction, i) => {
        burstPositions.set(
          [direction.x * reach * 1.6, direction.y * reach * 1.6, direction.z * reach * 1.6],
          i * 3,
        );
      });
      burstGeometry.attributes.position.needsUpdate = true;
      burstMaterial.opacity = (1 - age / 2) * 0.95;
    } else {
      burstMaterial.opacity = 0;
      burstDirections.length = 0; // new directions for the next burst
    }

    rings[0].rotation.z = t * 0.25;
    rings[1].rotation.z = -t * 0.18;
    waves.forEach(({ wave, offset }) => {
      const p = motion ? (t / 3.2 + offset) % 1 : 0;
      wave.scale.setScalar(1.4 + p * 2.6);
      (wave.material as THREE.MeshBasicMaterial).opacity = (1 - p) * 0.35 * motion;
    });
    scan.position.y = Math.sin(t * 1.4) * (boxH / 2 - 0.25);
    (scan.material as THREE.MeshBasicMaterial).opacity = 0.6 + 0.4 * Math.abs(Math.cos(t * 1.4));
    const breathe = 1 + Math.sin(t * 2.2) * 0.018;
    brackets.scale.set(breathe, breathe, 1);
    const reveal = Math.min(1, Math.max(0, (t - 0.6) / 0.6));
    (brackets.material as THREE.LineBasicMaterial).opacity = 0.95 * reveal;
    (label.material as THREE.SpriteMaterial).opacity = reveal;

    pairs.forEach(([i, j], index) => {
      floaters[i].object.getWorldPosition(a);
      floaters[j].object.getWorldPosition(b);
      world.worldToLocal(a);
      world.worldToLocal(b);
      linkPositions.set([a.x, a.y, a.z, b.x, b.y, b.z], index * 6);
      const along = (t * 0.32 + index * 0.37) % 1;
      pulsePositions.set(
        [a.x + (b.x - a.x) * along, a.y + (b.y - a.y) * along, a.z + (b.z - a.z) * along],
        index * 3,
      );
    });
    linkGeometry.attributes.position.needsUpdate = true;
    pulseGeometry.attributes.position.needsUpdate = true;
    (links.material as THREE.LineBasicMaterial).opacity =
      (0.22 + 0.12 * Math.sin(t * 1.7) + open * 0.25) * reveal;

    particles.rotation.y = t * 0.02;
    world.rotation.y =
      Math.sin(t * 0.15) * 0.12 + pointer.x * 0.18 * motion + scrolled * 0.9;
    world.rotation.x = pointer.y * 0.1 * motion - scrolled * 0.15;
    world.position.y = worldY + scrolled * 1.6;
    camera.position.x += (pointer.x * 0.6 * motion - camera.position.x) * 0.05;
    camera.position.y += (-pointer.y * 0.4 * motion - camera.position.y) * 0.05;
    camera.position.z = cameraZ + scrolled * 2.2;
    camera.lookAt(world.position.x * 0.35, 0, 0);
  };

  let frame = 0;
  let running = false;
  let onScreen = true;
  const loop = () => {
    frame = requestAnimationFrame(loop);
    update((performance.now() - started) / 1000);
    renderer.render(scene, camera);
  };
  const start = () => {
    if (running || !motion || !onScreen || document.hidden) return;
    running = true;
    frame = requestAnimationFrame(loop);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(frame);
  };
  const renderOnce = () => {
    update((performance.now() - started) / 1000);
    renderer.render(scene, camera);
  };

  const resizeObserver = new ResizeObserver(() => {
    layout();
    if (!running) renderOnce();
  });
  resizeObserver.observe(host);
  const visibility = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    if (onScreen) start();
    else stop();
  });
  visibility.observe(host);
  const onVisibility = () => (document.hidden ? stop() : start());
  document.addEventListener("visibilitychange", onVisibility);

  renderOnce();
  start();

  return {
    destroy() {
      stop();
      resizeObserver.disconnect();
      visibility.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("scroll", onScroll);
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        for (const item of Array.isArray(material) ? material : material ? [material] : []) {
          (item as THREE.MeshBasicMaterial).map?.dispose();
          item.dispose();
        }
      });
      dot.dispose();
      environment.dispose();
      room.dispose();
      pmrem.dispose();
      renderer.dispose();
    },
  };
}
