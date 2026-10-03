import { extractFeatures, GazeModel, SwitchEngine } from "./glance-core.js";

const VISION = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const COUNTDOWN_S = 3;
const SAMPLE_MS = 3000;
const MIN_SAMPLES = 20;

const $ = (id) => document.getElementById(id);
const els = {
  setup: $("setup"), count: $("count"), start: $("start"), status: $("status"),
  stage: $("stage"), monitors: $("monitors"), video: $("video"), face: $("face"),
  calPanel: $("calibrate-panel"), calTitle: $("cal-title"), calText: $("cal-text"),
  calBtn: $("cal-btn"), livePanel: $("live-panel"), engine: $("engine"), log: $("log"),
  recalBtn: $("recal-btn"),
};

const state = {
  landmarker: null,
  features: null, // latest feature vector or null
  monitorCount: 3,
  model: null,
  engine: new SwitchEngine(),
  cursor: 0, // monitor index holding the simulated cursor
  lastManual: -Infinity,
  calibrating: false,
  calIndex: 0,
  calData: { features: [], labels: [] },
  monitorEls: [],
};

// -- audio cues: you can't see this page while looking at another monitor -------

let audio;
function beep(freq = 880, ms = 120, when = 0) {
  audio ??= new AudioContext();
  const t = audio.currentTime + when;
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.25, t + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
  osc.connect(gain).connect(audio.destination);
  osc.start(t);
  osc.stop(t + ms / 1000 + 0.02);
}

// -- setup ---------------------------------------------------------------------

function setStatus(text, isError = false) {
  els.status.textContent = text;
  els.status.classList.toggle("error", isError);
}

async function start() {
  els.start.disabled = true;
  state.monitorCount = Number(els.count.value);
  try {
    setStatus("Asking for camera access...");
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
    els.video.srcObject = stream;
    await els.video.play();

    setStatus("Loading face model (about 4 MB)...");
    const { FaceLandmarker, FilesetResolver } = await import(`${VISION}/vision_bundle.mjs`);
    const fileset = await FilesetResolver.forVisionTasks(`${VISION}/wasm`);
    state.landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFaceBlendshapes: true,
      outputFacialTransformationMatrixes: true,
    });
  } catch (err) {
    console.error(err);
    const denied = err?.name === "NotAllowedError";
    setStatus(
      denied ? "Camera access was blocked. Allow it in your browser and try again."
             : `Could not start: ${err?.message ?? err}`,
      true,
    );
    els.start.disabled = false;
    return;
  }

  els.setup.hidden = true;
  els.stage.hidden = false;
  buildMonitors();
  showCalibrationStep();
  requestAnimationFrame(loop);
}

function buildMonitors() {
  els.monitors.replaceChildren();
  state.monitorEls = [];
  for (let i = 0; i < state.monitorCount; i++) {
    const el = document.createElement("button");
    el.className = "monitor";
    el.type = "button";
    el.setAttribute("aria-label", `Monitor ${i + 1}: move the cursor here by hand`);
    el.innerHTML = `
      <span class="name">Monitor ${i + 1}</span>
      <span class="cursor"></span>
      <span><span class="pct">–</span><span class="bar"><span></span></span></span>`;
    el.addEventListener("click", () => manualMove(i));
    els.monitors.append(el);
    state.monitorEls.push(el);
  }
  renderCursor();
}

// -- calibration ----------------------------------------------------------------

function showCalibrationStep() {
  const i = state.calIndex;
  els.calTitle.textContent = `Calibrate monitor ${i + 1} of ${state.monitorCount}`;
  els.calText.innerHTML =
    `Press <kbd>Space</kbd> or the button. After ${COUNTDOWN_S} short beeps, look at ` +
    `<strong>monitor ${i + 1}</strong> and let your eyes wander across it until the double beep.`;
  els.calBtn.textContent = `Calibrate monitor ${i + 1}`;
  els.calBtn.disabled = false;
  state.monitorEls.forEach((el, n) => el.classList.toggle("calibrating", n === i));
}

async function calibrateCurrent() {
  if (state.calibrating) return;
  state.calibrating = true;
  els.calBtn.disabled = true;
  const i = state.calIndex;

  for (let s = COUNTDOWN_S; s > 0; s--) {
    els.calBtn.textContent = `Look at monitor ${i + 1} in ${s}...`;
    beep(660, 90);
    await sleep(1000);
  }
  beep(990, 220);
  els.calBtn.textContent = "Recording... keep looking";

  const samples = [];
  const end = performance.now() + SAMPLE_MS;
  let lastFeatures = null;
  while (performance.now() < end) {
    await nextFrame();
    if (state.features && state.features !== lastFeatures) {
      samples.push(state.features);
      lastFeatures = state.features;
    }
  }
  beep(990, 110);
  beep(990, 110, 0.18);
  state.calibrating = false;

  if (samples.length < MIN_SAMPLES) {
    els.calText.textContent =
      "Your face wasn't visible enough. Face the camera with even lighting and try again.";
    els.calBtn.textContent = `Retry monitor ${i + 1}`;
    els.calBtn.disabled = false;
    return;
  }

  state.calData.features.push(...samples);
  state.calData.labels.push(...samples.map(() => i));
  state.monitorEls[i].classList.remove("calibrating");
  state.monitorEls[i].classList.add("done");
  state.calIndex++;

  if (state.calIndex < state.monitorCount) {
    showCalibrationStep();
  } else {
    finishCalibration();
  }
}

function finishCalibration() {
  state.model = new GazeModel({ ...state.calData, nMonitors: state.monitorCount });
  state.engine.reset();
  els.calPanel.hidden = true;
  els.livePanel.hidden = false;
  state.monitorEls.forEach((el) => el.classList.remove("done", "calibrating"));
  log("Calibrated. Look around your monitors.");
}

function recalibrate() {
  state.model = null;
  state.calIndex = 0;
  state.calData = { features: [], labels: [] };
  els.livePanel.hidden = true;
  els.calPanel.hidden = false;
  showCalibrationStep();
}

// -- live -----------------------------------------------------------------------

function manualMove(i) {
  state.cursor = i;
  state.lastManual = performance.now();
  renderCursor();
  if (state.model) log(`Moved by hand to monitor ${i + 1}`);
}

function renderCursor() {
  state.monitorEls.forEach((el, i) => el.classList.toggle("has-cursor", i === state.cursor));
}

function log(text) {
  const li = document.createElement("li");
  const t = new Date().toLocaleTimeString([], { hour12: false });
  li.textContent = `${t}  ${text}`;
  els.log.prepend(li);
  while (els.log.children.length > 30) els.log.lastChild.remove();
}

let lastVideoTime = -1;
function loop() {
  const now = performance.now();
  if (els.video.readyState >= 2 && els.video.currentTime !== lastVideoTime) {
    lastVideoTime = els.video.currentTime;
    const result = state.landmarker.detectForVideo(els.video, now);
    state.features = extractFeatures(result);
    els.face.textContent = state.features ? "Face detected" : "No face";
    els.face.classList.toggle("ok", Boolean(state.features));

    if (state.model) {
      const probs = state.features ? state.model.predict(state.features) : null;
      const target = state.engine.update(now, probs, state.cursor, state.lastManual);
      if (target !== null) {
        state.cursor = target;
        renderCursor();
        log(`Cursor jumped to monitor ${target + 1}`);
      }
      renderProbabilities();
      els.engine.textContent = state.engine.explain(now, state.cursor, state.lastManual);
    }
  }
  requestAnimationFrame(loop);
}

function renderProbabilities() {
  const smoothed = state.engine.smoothed;
  const gazed = state.engine.gazed;
  state.monitorEls.forEach((el, i) => {
    const p = smoothed ? smoothed[i] : 0;
    el.querySelector(".bar span").style.width = `${Math.round(p * 100)}%`;
    el.querySelector(".pct").textContent = smoothed ? `${Math.round(p * 100)}%` : "–";
    el.classList.toggle("gazed", i === gazed);
  });
}

// -- helpers & wiring ---------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nextFrame = () => new Promise((r) => requestAnimationFrame(r));

els.start.addEventListener("click", start);
els.calBtn.addEventListener("click", calibrateCurrent);
els.recalBtn.addEventListener("click", recalibrate);

// Any mouse movement in the page is manual input, just like in the desktop app.
window.addEventListener("pointermove", () => { state.lastManual = performance.now(); });

window.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || els.stage.hidden || els.calPanel.hidden) return;
  e.preventDefault();
  if (!els.calBtn.disabled) calibrateCurrent();
});
