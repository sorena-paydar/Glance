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
2. **Calibration.** You look at a 3x3 grid of targets on each monitor. A
   k-nearest-neighbours model learns which features belong to which monitor (and
   recognises when you are looking at none of them: keyboard, phone, away), and a
   per-monitor regression learns *where* on the monitor you are looking.
3. **Moving the cursor.** A decision engine smooths the predictions and applies
   dwell, confidence and cooldown rules, plus the manual-input guard above. When it
   decides to switch, the cursor glides smoothly to where you are looking on the new
   monitor.

## Accuracy

A webcam reliably tells **which monitor** you are looking at. **Where** on the
monitor is approximate, usually off by a few centimetres, so the cursor lands near
what you look at and you fine-tune with the trackpad. Pixel-exact eye tracking needs
infrared hardware. Calibration measures and shows the expected error for each of
your monitors.

To get the most out of it:

- **Recalibrate** after moving your seat, monitors or camera, and in very different
  lighting. Calibration is personal: it learns *your* face in *your* setup.
- **Camera placement:** centred above or below the monitors you use most, facing
  you, at roughly eye height. A laptop camera works; an external webcam on top of the
  middle monitor usually works better.
- **Light your face** evenly from the front. Avoid a bright window behind you and
  strong reflections in glasses.
- **Sit at your usual distance** (50-80 cm) during calibration and use.
- **Turn your head a little** towards what you look at, during calibration and use:
  head direction is measured far more precisely than eye direction.
- **Keep your eyes on each dot** until it moves during calibration.

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

On macOS the installer puts **Glance** in your Applications folder and on your
Desktop, and opens it. Setup takes about two minutes:

1. **Monitors**: Glance checks that you have at least two.
2. **Permissions**: it opens the right System Settings pages; switch on **Glance**
   for **Accessibility** (to move the cursor) and **Input Monitoring** (to notice
   your trackpad, mouse and keyboard). Glance restarts itself to apply them.
3. **Camera**: allow camera access when macOS asks.
4. **Calibration**: a red dot appears on each monitor in turn; look at it until it
   moves.

Glance then runs in your menu bar. On Windows and Linux, setup runs in the terminal
and Glance is added to the Desktop and Start menu / app launcher.

## Everyday use

Double-click **Glance** on your Desktop (or in Launchpad / the Start menu), or run:

```sh
glance
```

Pause and resume with **Ctrl+Alt+G**, or from the menu bar icon. If you rearrange
your monitors, Glance notices and recalibrates.

**Other commands**

```sh
glance setup       # run guided setup again
glance calibrate   # recalibrate only
glance preview     # camera view with live predictions, for troubleshooting
glance monitors    # list detected monitors
glance config      # show settings and where they are stored
glance desktop     # (re)create the desktop app and shortcuts
```

**Uninstall**: `glance desktop --remove && uv tool uninstall glance`

## Settings

`glance config` shows the settings file location and current values. Edit
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
| `glide_ms` | `200` | Duration of the smooth cursor glide (0 jumps instantly) |
| `jump_to` | `"gaze"` | Where the cursor lands on a new monitor: `"gaze"`, `"last"` (where you left it) or `"center"` |
| `follow_within_monitor` | `false` | Also move the cursor within a monitor when you look far away from it |
| `follow_distance` | `0.3` | How far gaze must be from the cursor for that, as a fraction of the monitor diagonal |
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
| `pointer.py`, `motion.py` | Moving and gliding the cursor, detecting manual input |
| `displays.py` | Monitor layout |
| `app.py`, `cli.py`, `setup.py`, `ui.py`, `tray.py` | Runtime loop, guided setup and user interfaces |
| `desktop.py` | Desktop app (macOS) and shortcuts (Windows, Linux) |
| `docs/` | Website, live demo (`glance-core.js`) and installers |

## License

[MIT](LICENSE)
