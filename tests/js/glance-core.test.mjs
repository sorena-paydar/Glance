import assert from "node:assert/strict";
import { test } from "node:test";

import { GazeModel, headPose, SwitchEngine } from "../../docs/glance-core.js";

const LOOK = (i, n = 3) => Array.from({ length: n }, (_, j) => (j === i ? 1 : 0));
const engine = (o = {}) =>
  new SwitchEngine({ smoothing: 1, dwellMs: 300, cooldownMs: 500, manualGraceMs: 800, ...o });

function feed(e, start, end, probs, cursor, lastManual = -Infinity) {
  for (let t = start; t <= end; t += 50) {
    const target = e.update(t, probs, cursor, lastManual);
    if (target !== null) return [t, target];
  }
  return null;
}

test("jumps after dwell", () => {
  const [t, target] = feed(engine(), 0, 2000, LOOK(1), 0);
  assert.equal(target, 1);
  assert.ok(t >= 300);
});

test("manual input blocks gaze", () => {
  const e = engine();
  for (let t = 0; t < 3000; t += 50) assert.equal(e.update(t, LOOK(1), 0, t), null);
});

test("respects manual choice until gaze moves", () => {
  const e = engine();
  assert.equal(feed(e, 0, 1000, LOOK(1), 0, 1000), null);
  assert.equal(feed(e, 1850, 4000, LOOK(1), 0, 1000), null);
  assert.equal(feed(e, 4050, 6000, LOOK(2), 0, 1000)[1], 2);
});

test("brief glance does not jump", () => {
  const e = engine();
  assert.equal(feed(e, 0, 200, LOOK(1), 0), null);
  assert.equal(feed(e, 250, 2000, LOOK(0), 0), null);
});

test("head pose reads both matrix orders", () => {
  // Pure translation: z = -40 cm, no rotation.
  const columnMajor = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, -40, 1];
  const rowMajor = [1, 0, 0, 2, 0, 1, 0, 3, 0, 0, 1, -40, 0, 0, 0, 1];
  for (const m of [columnMajor, rowMajor]) {
    const p = headPose(m);
    assert.deepEqual([p.x, p.y, p.z], [2, 3, -40]);
    assert.ok(Math.abs(p.yaw) < 1e-9 && Math.abs(p.pitch) < 1e-9);
  }
});

test("model separates monitors and rejects far gaze", () => {
  let seed = 1;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 6;
  const centers = [[-30, 0], [0, 10], [30, 0]];
  const features = [], labels = [];
  centers.forEach((c, label) => {
    for (let i = 0; i < 60; i++) {
      features.push([c[0] + rand(), c[1] + rand()]);
      labels.push(label);
    }
  });
  const model = new GazeModel({ features, labels, nMonitors: 3 });
  centers.forEach((c, label) => {
    const p = model.predict(c);
    assert.equal(p.indexOf(Math.max(...p)), label);
  });
  assert.equal(model.predict([0, 200]), null);
});
