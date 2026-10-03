"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict

from glance import __version__
from glance.config import Settings, calibration_path, settings_path
from glance.displays import get_monitors, monitor_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="glance", description="Move your cursor to the monitor you are looking at."
    )
    parser.add_argument("--version", action="version", version=f"glance {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="guided setup: permissions, camera and calibration")
    sub.add_parser("app", help="start as a desktop app (dialogs instead of the terminal)")
    desktop = sub.add_parser("desktop", help="add Glance to the desktop and app launcher")
    desktop.add_argument("--remove", action="store_true", help="remove the desktop app")
    sub.add_parser("monitors", help="list detected monitors")
    calibrate = sub.add_parser("calibrate", help="calibrate gaze for your monitors")
    calibrate.add_argument("--camera", type=int, help="camera index (default from settings)")
    run = sub.add_parser("run", help="start moving the cursor with your gaze")
    run.add_argument("--camera", type=int, help="camera index (default from settings)")
    run.add_argument("--tray", action="store_true", help="show a menu bar / tray icon")
    preview = sub.add_parser("preview", help="show the camera with live predictions")
    preview.add_argument("--camera", type=int, help="camera index (default from settings)")
    config = sub.add_parser("config", help="show settings and where they are stored")
    config.add_argument("--reset", action="store_true", help="restore default settings")

    args = parser.parse_args(argv)
    if args.command is None:  # plain `glance`: set up the first time, then just run
        args.command = "start"
        args.tray = True
    settings = Settings.load()
    if getattr(args, "camera", None) is not None:
        settings.camera_index = args.camera

    commands = {
        "start": cmd_start,
        "app": cmd_app,
        "desktop": cmd_desktop,
        "setup": cmd_setup,
        "monitors": cmd_monitors,
        "calibrate": cmd_calibrate,
        "run": cmd_run,
        "preview": cmd_preview,
        "config": cmd_config,
    }
    try:
        return commands[args.command](args, settings)
    except KeyboardInterrupt:
        return 130


def cmd_start(args, settings: Settings, ui=None) -> int:
    """Set up when needed, then run with the tray icon."""
    from glance.classifier import GazeModel
    from glance.displays import layout_key
    from glance.setup import ensure_permissions, run_setup
    from glance.ui import ConsoleUI

    ui = ui or ConsoleUI()
    needs_setup = not calibration_path().exists()
    if not needs_setup:
        try:
            needs_setup = GazeModel.load(calibration_path()).layout != layout_key(get_monitors())
        except (ValueError, KeyError):
            needs_setup = True
        if needs_setup:
            ui.say("Your monitors or Glance changed since the last calibration; let's recalibrate.")
    if needs_setup:
        if not run_setup(settings, ui):
            return 1
    elif not ensure_permissions(ui):
        return 1
    return cmd_run(args, settings)


def cmd_app(args, settings: Settings) -> int:
    from glance.config import log_path
    from glance.instance import already_running
    from glance.ui import create_ui

    ui = create_ui(gui=True)
    if already_running():
        ui.notify("Glance is already running. Find it in the menu bar.")
        return 0
    args.tray = True
    code = cmd_start(args, settings, ui)
    if code not in (0, 130) and calibration_path().exists():
        ui.alert(f"Glance stopped because of a problem. Details are in {log_path()}.")
    return code


def cmd_setup(args, settings: Settings) -> int:
    from glance.setup import run_setup

    return 0 if run_setup(settings) else 1


def cmd_desktop(args, settings: Settings) -> int:
    from glance.desktop import install_desktop_app, remove_desktop_app

    if args.remove:
        for path in remove_desktop_app():
            print(f"Removed {path}")
        return 0
    for path in install_desktop_app():
        print(f"Added {path}")
    return 0


def cmd_monitors(args, settings: Settings) -> int:
    from pynput.mouse import Controller

    monitors = get_monitors()
    cursor = monitor_at(monitors, *Controller().position)
    for i, m in enumerate(monitors):
        marker = "  <- cursor" if i == cursor else ""
        print(f"[{i}] {m.label()} at ({m.x}, {m.y}){marker}")
    return 0


def cmd_config(args, settings: Settings) -> int:
    if args.reset or not settings_path().exists():
        settings = Settings() if args.reset else settings
        settings.save()
    print(f"Settings:    {settings_path()}")
    print(f"Calibration: {calibration_path()}")
    print(json.dumps(asdict(settings), indent=2))
    return 0


def cmd_calibrate(args, settings: Settings) -> int:
    from glance.calibration import CalibrationError, run_calibration
    from glance.gaze import CameraError, GazeTracker
    from glance.overlay import create_overlay

    monitors = get_monitors()
    print(f"Found {len(monitors)} monitor(s):")
    for i, m in enumerate(monitors):
        print(f"  [{i}] {m.label()}")
    print("\nSit as you normally do. Follow the red dot with your eyes.\n")

    tracker = GazeTracker(settings.camera_index)
    try:
        tracker.start()
    except CameraError as exc:
        return _fail(str(exc))
    try:
        if not _wait_for_face(tracker):
            return _fail("no face detected; check the camera and lighting")
        report = run_calibration(tracker, monitors, create_overlay())
    except CalibrationError as exc:
        return _fail(str(exc))
    finally:
        tracker.stop()

    report.model.save(calibration_path())
    from glance.setup import print_report

    print("\nCalibration saved. Estimated accuracy:")
    print_report(monitors, report)
    if min(report.accuracy_per_monitor) < 0.8:
        print(
            "\nSome monitors are hard to tell apart. Turning your head slightly towards "
            "each monitor during calibration and use helps a lot."
        )
    print("\nStart Glance with: glance run")
    return 0


def cmd_run(args, settings: Settings) -> int:
    from glance.app import GlanceApp, LayoutChangedError
    from glance.gaze import CameraError
    from glance.permissions import (
        MACOS_PERMISSION_HELP,
        accessibility_trusted,
        input_monitoring_granted,
    )

    model = _load_model()
    if model is None:
        return 1
    if accessibility_trusted() is False:
        print(MACOS_PERMISSION_HELP, file=sys.stderr)
        return _fail("Accessibility permission is required to move the cursor")
    if input_monitoring_granted() is False:
        print(MACOS_PERMISSION_HELP, file=sys.stderr)
        return _fail("Input Monitoring is required so manual input always wins over gaze")

    try:
        app = GlanceApp(settings, model, get_monitors())
        app.start()
    except (LayoutChangedError, CameraError) as exc:
        return _fail(str(exc))

    print(f"Glance is running. Pause/resume: {settings.hotkey}. Quit: Ctrl+C.")
    try:
        if args.tray and _tray_available():
            from glance.tray import run_with_tray

            print("Glance is in your menu bar / system tray.")
            run_with_tray(app)
        else:
            app.run()
    finally:
        app.stop()
    return 0


def cmd_preview(args, settings: Settings) -> int:
    import cv2

    from glance.gaze import CameraError, GazeTracker

    monitors = get_monitors()
    model = _load_model(required=False)
    tracker = GazeTracker(settings.camera_index, keep_frames=True)
    try:
        tracker.start()
    except CameraError as exc:
        return _fail(str(exc))
    print("Press q in the preview window to quit.")
    try:
        while True:
            sample = tracker.latest()
            if sample is not None and sample.frame is not None:
                frame = cv2.flip(sample.frame, 1)
                for i, line in enumerate(_describe(sample, model, monitors)):
                    cv2.putText(
                        frame,
                        line,
                        (12, 28 + 26 * i),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (80, 255, 80),
                        2,
                        cv2.LINE_AA,
                    )
                cv2.imshow("Glance preview", frame)
            if cv2.waitKey(15) & 0xFF in (ord("q"), 27):
                break
    finally:
        tracker.stop()
        cv2.destroyAllWindows()
    return 0


def _describe(sample, model, monitors) -> list[str]:
    if sample.features is None:
        return ["No face detected"]
    yaw, pitch = sample.features[0], sample.features[1]
    lines = [f"Head yaw {yaw:+.0f} deg, pitch {pitch:+.0f} deg"]
    if model is None:
        return [*lines, "Not calibrated: run `glance calibrate`"]
    probs = model.predict_proba(sample.features)
    if probs is None:
        return [*lines, "Looking away from all monitors"]
    for i, (m, p) in enumerate(zip(monitors, probs, strict=True)):
        marker = ">" if i == int(probs.argmax()) else " "
        lines.append(f"{marker} {m.name or f'Monitor {i}'}: {p:.0%}")
    return lines


def _tray_available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except ImportError:
        return False
    return True


def _wait_for_face(tracker, timeout: float = 8.0) -> bool:
    print("Looking for your face...")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        sample = tracker.latest()
        if sample is not None and sample.features is not None:
            return True
        time.sleep(0.05)
    return False


def _load_model(required: bool = True):
    from glance.classifier import GazeModel

    path = calibration_path()
    if not path.exists():
        if required:
            _fail("not calibrated yet; run `glance calibrate` first")
        return None
    try:
        return GazeModel.load(path)
    except (ValueError, KeyError) as exc:
        _fail(f"cannot read calibration ({exc}); run `glance calibrate` again")
        return None


def _fail(message: str) -> int:
    print(f"glance: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
