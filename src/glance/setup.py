"""Guided first-run setup: monitors, permissions, camera and calibration."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

from glance.config import Settings, calibration_path
from glance.displays import Monitor, get_monitors

TERMINALS = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "ghostty": "Ghostty",
    "WarpTerminal": "Warp",
    "vscode": "Visual Studio Code",
    "WezTerm": "WezTerm",
}
PERMISSION_WAIT_SECONDS = 180
GOOD_ACCURACY = 0.8


def terminal_name() -> str:
    program = os.environ.get("TERM_PROGRAM", "")
    return TERMINALS.get(program, program or "your terminal app")


def run_setup(settings: Settings) -> bool:
    """Walk a new user through setup. Returns True when Glance is ready to run."""
    print("\nWelcome to Glance!")
    print("Glance moves your cursor to the monitor you are looking at. Let's set it up.")

    _step(1, "Monitors")
    monitors = get_monitors()
    for i, m in enumerate(monitors):
        print(f"  [{i}] {m.label()}")
    if len(monitors) < 2:
        print("\nGlance needs at least two monitors. Connect another one and run `glance` again.")
        return False
    print(f"  Found {len(monitors)} monitors.")

    _step(2, "Permissions")
    if sys.platform == "darwin":
        if not _macos_permissions():
            return False
    else:
        print("  Nothing to grant on this platform.")

    _step(3, "Camera")
    tracker = _start_camera(settings)
    if tracker is None:
        return False
    try:
        if not _wait_for_face(tracker):
            return False

        _step(4, "Calibration")
        if not _calibrate(tracker, monitors):
            return False
    finally:
        tracker.stop()

    print("\nAll set! From now on, just run `glance` to start it.")
    print(f"Pause or resume at any time with {settings.hotkey.replace('<', '').replace('>', '')}.")
    return True


def _step(number: int, title: str) -> None:
    print(f"\n[{number}/4] {title}")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ""


def _wait_until(check: Callable[[], bool | None], message: str) -> bool:
    print(f"  {message} (Ctrl+C to stop)")
    end = time.monotonic() + PERMISSION_WAIT_SECONDS
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(1)
    return False


def _macos_permissions() -> bool:
    from glance.permissions import (
        accessibility_trusted,
        input_monitoring_granted,
        open_privacy_settings,
        request_accessibility,
        request_input_monitoring,
    )

    app = terminal_name()

    if accessibility_trusted():
        print("  Accessibility: granted")
    else:
        print("  Glance needs Accessibility to move the cursor.")
        print(f"  In the window that opens, switch on '{app}'.")
        request_accessibility()
        open_privacy_settings("accessibility")
        if not _wait_until(accessibility_trusted, "Waiting for Accessibility..."):
            print(f"\n  Still not granted. Quit {app} completely (Cmd+Q), reopen it and run")
            print("  `glance` again.")
            return False
        print("  Accessibility: granted")

    if input_monitoring_granted():
        print("  Input Monitoring: granted")
    else:
        print("  Glance needs Input Monitoring to notice your trackpad, mouse and keyboard,")
        print("  so it never moves the cursor while you are using them.")
        print(f"  In the window that opens, switch on '{app}'.")
        request_input_monitoring()
        open_privacy_settings("input_monitoring")
        _wait_until(input_monitoring_granted, "Waiting for Input Monitoring...")
        # macOS only applies Input Monitoring to apps started after it was granted.
        print(f"\n  Almost there: quit {app} completely (Cmd+Q), reopen it and run `glance`")
        print("  again to continue setup.")
        return False

    print("  Camera: macOS will ask for access in the next step if needed.")
    return True


def _start_camera(settings: Settings):
    from glance.gaze import CameraError, GazeTracker

    print("  Starting the camera (the face model is downloaded the first time)...")
    for _ in range(3):
        tracker = GazeTracker(settings.camera_index)
        try:
            tracker.start()
            print("  Camera: working")
            return tracker
        except CameraError:
            tracker.stop()
            print(f"  Could not open camera {settings.camera_index}.")
            if sys.platform == "darwin":
                from glance.permissions import open_privacy_settings

                print(f"  Allow camera access for '{terminal_name()}' if macOS asks,")
                print("  or switch it on in the System Settings window that opens.")
                open_privacy_settings("camera")
            if _ask("  Press Enter to try again, or type q to quit: ") == "q":
                return None
    print("\n  The camera still doesn't open. If you changed camera permissions, quit and")
    print("  reopen your terminal. Another camera can be chosen with `glance config`.")
    return None


def _wait_for_face(tracker, timeout: float = 15.0) -> bool:
    print("  Looking for your face...")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        sample = tracker.latest()
        if sample is not None and sample.features is not None:
            print("  I can see you.")
            return True
        time.sleep(0.05)
    print("  I can't see your face. Make sure the camera points at you and your face is")
    print("  well lit, then run `glance` again.")
    return False


def print_report(monitors: list[Monitor], report) -> None:
    print("\n  Monitor                                          recognised   cursor lands within")
    rows = zip(monitors, report.accuracy_per_monitor, report.point_error_per_monitor, strict=True)
    for m, accuracy, error in rows:
        print(f"    {m.label():46s} {accuracy:8.0%}   ~{error:.0f} pt of your gaze")


def _calibrate(tracker, monitors: list[Monitor]) -> bool:
    from glance.calibration import CalibrationError, run_calibration
    from glance.overlay import create_overlay

    print("  A red dot will appear on each monitor in turn. Look at it until it moves.")
    print("  Sit as you normally do; turning your head towards each monitor is fine.")
    while True:
        _ask("  Press Enter to start (takes about 16 seconds per monitor)...")
        try:
            report = run_calibration(tracker, monitors, create_overlay(), log=lambda _: None)
        except CalibrationError as exc:
            print(f"  Calibration failed: {exc}")
            if _ask("  Try again? [Y/n] ") in ("n", "no"):
                return False
            continue

        print_report(monitors, report)
        if min(report.accuracy_per_monitor) >= GOOD_ACCURACY:
            report.model.save(calibration_path())
            return True

        print("\n  Some monitors are hard to tell apart. Turning your head a little towards")
        print("  each monitor while looking at the dots usually helps.")
        answer = _ask("  Try again? [Y/n] (n keeps this calibration) ")
        if answer in ("n", "no"):
            report.model.save(calibration_path())
            return True
