# Glance

Move your cursor to the monitor you are looking at.

With several monitors, you look at another screen but the cursor is still on the
old one, so you have to drag it across before you can do anything. Glance watches
your face through the webcam, works out which monitor you are looking at, and
jumps the cursor there.

**Manual control always wins.** Glance never fights your trackpad or mouse:

- No jumps while you move, click, drag or scroll, and for a short grace period after.
- No jumps while you type (configurable).
- If you move the cursor to one monitor while looking at another, Glance respects
  your choice and waits until your gaze moves somewhere new.
- Brief glances are ignored: your gaze has to rest on a monitor before the cursor jumps.

Works on macOS, Windows and Linux with any webcam. No eye-tracking hardware needed.

## How it works

1. **Gaze features.** [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)
   tracks your face in the webcam image. Each frame becomes a feature vector: head
   rotation and position, where each iris sits inside the eye, and eye-direction
   blendshapes.
2. **Calibration.** You look at five targets on each monitor. A k-nearest-neighbours
   model learns which features belong to which monitor, and recognises when you are
   looking at none of them (keyboard, phone, away).
3. **Switching.** A decision engine smooths the predictions and applies dwell,
   confidence and cooldown rules, plus the manual-input guard above. When it decides
   to switch, the cursor returns to where you last left it on that monitor (or its
   centre).

A webcam can tell *which monitor* you are looking at reliably, but not the exact
pixel, so Glance moves the cursor between monitors rather than tracking your gaze
point.

## Install

**macOS / Linux**

```sh
curl -fsSL https://sorena-paydar.github.io/Glance/install.sh | sh
```

**Windows** (PowerShell)

```powershell
irm https://sorena-paydar.github.io/Glance/install.ps1 | iex
```

The installer sets up [uv](https://docs.astral.sh/uv/) if you don't have it (uv
fetches Python by itself), installs the `glance` command and starts guided setup.

## First run

Setup takes about a minute and walks you through:

1. **Monitors**: Glance lists the monitors it found (you need at least two).
2. **Permissions** (macOS): it opens the right System Settings pages. Switch on your
   terminal app (Terminal, iTerm, Warp...) for **Accessibility** (to move the cursor)
   and **Input Monitoring** (to notice your trackpad, mouse and keyboard). macOS then
   asks you to reopen the terminal; run `glance` again to continue.
3. **Camera**: allow camera access when macOS asks.
4. **Calibration**: a red dot appears on each monitor in turn; look at it until it
   moves.

Glance then starts in your menu bar.

## Everyday use

```sh
glance
```

That's it. Pause and resume with **Ctrl+Alt+G**, or from the menu bar icon. If you
rearrange your monitors, Glance notices and recalibrates.

**Tips for good accuracy**

- Sit as you normally do during calibration.
- Turning your head slightly towards a monitor helps much more than moving only
  your eyes, especially with monitors that are close together.
- Even, frontal lighting works best. Avoid a bright window behind you.

**Other commands**

```sh
glance setup       # run guided setup again
glance calibrate   # recalibrate only
glance preview     # camera view with live predictions, for troubleshooting
glance monitors    # list detected monitors
glance config      # show settings and where they are stored
```

**Uninstall**: `uv tool uninstall glance`

## Settings

`uv run glance config` shows the settings file location and current values. Edit
the JSON to tune behaviour:

| Setting | Default | Meaning |
| --- | --- | --- |
| `camera_index` | `0` | Which webcam to use |
| `manual_grace_ms` | `800` | Gaze is ignored this long after any pointer activity |
| `dwell_ms` | `350` | How long gaze must rest on a monitor before the cursor jumps |
| `min_confidence` | `0.6` | Minimum smoothed probability for the gazed monitor |
| `switch_margin` | `0.2` | How much the gazed monitor must beat the cursor's monitor |
| `smoothing` | `0.35` | Prediction smoothing, 0 to 1 (higher reacts faster) |
| `cooldown_ms` | `600` | Minimum time between two jumps |
| `respect_manual_choice` | `true` | Don't undo a manual move until your gaze changes |
| `pause_while_typing` | `true` | Treat typing as manual activity |
| `remember_position` | `true` | Return to the last position on a monitor instead of its centre |
| `hotkey` | `<ctrl>+<alt>+g` | Pause/resume hotkey ([pynput syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)) |

## Development

```sh
git clone https://github.com/sorena-paydar/Glance.git && cd Glance
uv sync --extra tray
uv run glance            # run from source
uv run pytest
node --test tests/js/glance-core.test.mjs
uvx ruff check src tests && uvx ruff format --check src tests
```

| Module | Responsibility |
| --- | --- |
| `gaze.py` | Webcam capture and gaze feature extraction |
| `classifier.py` | Gaze features to monitor probabilities |
| `calibration.py`, `overlay.py` | Calibration targets and model fitting |
| `engine.py` | When to jump (pure logic, fully unit-tested) |
| `pointer.py` | Moving the cursor and detecting manual input |
| `displays.py` | Monitor layout |
| `app.py`, `cli.py`, `setup.py`, `tray.py` | Runtime loop, guided setup and user interfaces |
| `docs/` | Website, live demo (`glance-core.js`) and installers |

## License

[MIT](LICENSE)
