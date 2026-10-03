// Browser port of Glance's core: gaze features, k-NN model and switch engine.
// Mirrors src/glance/gaze.py, classifier.py and engine.py.

export const EYE_BLENDSHAPES = [
  "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeLookDownLeft",
  "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeLookDownRight",
];

// Face mesh indices: [outer corner, inner corner, iris centre].
const RIGHT_EYE = [33, 133, 468];
const LEFT_EYE = [263, 362, 473];

/** Row-major 3x4 view of a MediaPipe 4x4 matrix, whatever its storage order. */
function matrixRows(data) {
  // The translation's z (head distance, tens of cm) is by far the largest entry;
  // it sits at index 14 when column-major and 11 when row-major.
  const columnMajor = Math.abs(data[14]) > Math.abs(data[11]);
  const at = (r, c) => (columnMajor ? data[c * 4 + r] : data[r * 4 + c]);
  return { at };
}

export function headPose(data) {
  const { at } = matrixRows(data);
  const deg = 180 / Math.PI;
  const yaw = Math.asin(Math.max(-1, Math.min(1, -at(2, 0)))) * deg;
  const pitch = Math.atan2(at(2, 1), at(2, 2)) * deg;
  const roll = Math.atan2(at(1, 0), at(0, 0)) * deg;
  return { yaw, pitch, roll, x: at(0, 3), y: at(1, 3), z: at(2, 3) };
}

function irisOffset(points, [outerI, innerI, irisI]) {
  const outer = points[outerI], inner = points[innerI], iris = points[irisI];
  const ax = outer.x - inner.x, ay = outer.y - inner.y;
  const widthSq = ax * ax + ay * ay || 1e-9;
  const rx = iris.x - inner.x, ry = iris.y - inner.y;
  return [(rx * ax + ry * ay) / widthSq, (ax * ry - ay * rx) / widthSq];
}

/** Feature vector from a FaceLandmarkerResult, or null when no face is visible. */
export function extractFeatures(result) {
  const points = result.faceLandmarks?.[0];
  const matrix = result.facialTransformationMatrixes?.[0];
  const shapes = result.faceBlendshapes?.[0];
  if (!points || points.length <= 473 || !matrix || !shapes) return null;
  const pose = headPose(matrix.data);
  const scores = Object.fromEntries(shapes.categories.map((c) => [c.categoryName, c.score]));
  return [
    pose.yaw, pose.pitch, pose.roll, pose.x, pose.y, pose.z,
    ...irisOffset(points, RIGHT_EYE),
    ...irisOffset(points, LEFT_EYE),
    ...EYE_BLENDSHAPES.map((name) => scores[name] ?? 0),
  ];
}

const dist = (a, b) => {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += (a[i] - b[i]) ** 2;
  return Math.sqrt(s);
};

/**
 * Distance-weighted k-NN over standardised features, with a novelty threshold so
 * gaze that matches no monitor yields null.
 *
 * `groups` marks samples taken in one go; neighbours from the same group are
 * near-duplicates, so the threshold is sized from distances to other groups'
 * samples of the same monitor (or, with one group per monitor, to samples at
 * least `gap` frames apart).
 */
export class GazeModel {
  constructor({ features, labels, nMonitors, k = 7, noveltyScale = 2.5, gap = 8 }) {
    const n = features.length, d = features[0].length;
    this.mean = Array.from({ length: d }, (_, j) => features.reduce((s, f) => s + f[j], 0) / n);
    this.std = Array.from({ length: d }, (_, j) => {
      const v = features.reduce((s, f) => s + (f[j] - this.mean[j]) ** 2, 0) / n;
      return Math.sqrt(v) < 1e-6 ? 1 : Math.sqrt(v);
    });
    this.samples = features.map((f) => this.standardise(f));
    this.labels = labels;
    this.nMonitors = nMonitors;
    this.k = Math.max(1, Math.min(k, n - 1));

    const spread = [];
    for (let i = 0; i < n; i++) {
      let best = Infinity;
      for (let j = 0; j < n; j++) {
        if (labels[j] !== labels[i] || Math.abs(i - j) < gap) continue;
        best = Math.min(best, dist(this.samples[i], this.samples[j]));
      }
      if (Number.isFinite(best)) spread.push(best);
    }
    spread.sort((a, b) => a - b);
    const p95 = spread.length ? spread[Math.floor(0.95 * (spread.length - 1))] : 1;
    this.threshold = Math.max(p95 * noveltyScale, 1e-6);
  }

  standardise(f) {
    return f.map((v, j) => (v - this.mean[j]) / this.std[j]);
  }

  /** Per-monitor probabilities, or null if the gaze matches no monitor. */
  predict(feature) {
    const z = this.standardise(feature);
    const nearest = this.samples
      .map((s, i) => [dist(s, z), this.labels[i]])
      .sort((a, b) => a[0] - b[0])
      .slice(0, this.k);
    if (nearest[0][0] > this.threshold) return null;
    const votes = new Array(this.nMonitors).fill(0);
    for (const [d, label] of nearest) votes[label] += 1 / (d + 1e-6);
    const total = votes.reduce((a, b) => a + b, 0);
    return votes.map((v) => v / total);
  }
}

export const DEFAULTS = {
  manualGraceMs: 800,
  dwellMs: 350,
  minConfidence: 0.6,
  switchMargin: 0.2,
  smoothing: 0.35,
  cooldownMs: 600,
  respectManualChoice: true,
};

/** Decides when the cursor should jump. Manual input always wins over gaze. */
export class SwitchEngine {
  constructor(settings = {}) {
    this.cfg = { ...DEFAULTS, ...settings };
    this.reset();
  }

  reset() {
    this.smoothed = null;
    this.candidate = null;
    this.candidateSince = 0;
    this.cooldownUntil = 0;
    this.suppressed = null;
  }

  get gazed() {
    if (!this.smoothed) return null;
    let top = 0;
    this.smoothed.forEach((p, i) => { if (p > this.smoothed[top]) top = i; });
    return this.smoothed[top] >= this.cfg.minConfidence ? top : null;
  }

  /** Times in ms. Returns the monitor to jump to, or null. */
  update(now, probabilities, cursorMonitor, lastManual, pointerBusy = false) {
    const cfg = this.cfg;
    if (!probabilities) {
      this.smoothed = null;
      this.candidate = null;
      return null;
    }
    const a = cfg.smoothing;
    this.smoothed = this.smoothed && this.smoothed.length === probabilities.length
      ? probabilities.map((p, i) => a * p + (1 - a) * this.smoothed[i])
      : [...probabilities];
    const gazed = this.gazed;

    if (pointerBusy || now - lastManual < cfg.manualGraceMs) {
      this.candidate = null;
      if (cfg.respectManualChoice) this.suppressed = gazed;
      return null;
    }
    if (this.suppressed !== null && gazed !== this.suppressed) this.suppressed = null;
    if (gazed === null || gazed === cursorMonitor || gazed === this.suppressed) {
      this.candidate = null;
      return null;
    }
    if (cursorMonitor !== null &&
        this.smoothed[gazed] - this.smoothed[cursorMonitor] < cfg.switchMargin) {
      this.candidate = null;
      return null;
    }
    if (now < this.cooldownUntil) return null;
    if (this.candidate !== gazed) {
      this.candidate = gazed;
      this.candidateSince = now;
      return null;
    }
    if (now - this.candidateSince < cfg.dwellMs) return null;
    this.candidate = null;
    this.cooldownUntil = now + cfg.cooldownMs;
    return gazed;
  }

  /** Why the engine is (not) acting, for display. */
  explain(now, cursorMonitor, lastManual) {
    if (!this.smoothed) return "No face detected";
    if (now - lastManual < this.cfg.manualGraceMs) return "Manual input: gaze ignored";
    const gazed = this.gazed;
    if (gazed === null) return "Not sure where you are looking";
    if (gazed === this.suppressed) return "Respecting your manual choice";
    if (gazed === cursorMonitor) return "Looking at the cursor's monitor";
    if (this.candidate === gazed) return "Dwelling...";
    return "Gaze moved";
  }
}
