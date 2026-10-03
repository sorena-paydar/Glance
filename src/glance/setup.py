"""Guided first-run setup: monitors, permissions, camera and calibration."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from glance.config import Settings, calibration_path
from glance.displays import Monitor, get_monitors
from glance.ui import ConsoleUI

PERMISSION_WAIT_SECONDS = 180
GOOD_ACCURACY = 0.8


def run_setup(settings: Settings, ui=None) -> bool:
    """Walk a new user through setup. Returns True when Glance is ready to run."""
    ui = ui or ConsoleUI()
    ui.say("\nWelcome to Glance!")
    ui.say("Glance moves your cursor to the monitor you are looking at. Let's set it up.")

    ui.step(1, "Monitors")
    monitors = get_monitors()
    for i, m in enumerate(monitors):
        ui.say(f"  [{i}] {m.label()}")
    if len(monitors) < 2:
        ui.alert("Glance needs at least two monitors. Connect another one and start Glance again.")
        return False
    ui.say(f"  Found {len(monitors)} monitors.")

    ui.step(2, "Permissions")
    if not ensure_permissions(ui):
        return False

    ui.step(3, "Camera")
    tracker = _start_camera(settings, ui)
    if tracker is None:
        return False
    try:
        if not _wait_for_face(tracker, ui):
            return False

        ui.step(4, "Calibration")
        if not _calibrate(tracker, monitors, ui):
            return False
    finally:
        tracker.stop()

    hotkey = settings.hotkey.replace("<", "").replace(">", "")
    ui.alert(
        "All set! Glance lives in your menu bar while it runs.\n\n"
        f"Pause or resume at any time with {hotkey}."
    )
    return True


def ensure_permissions(ui) -> bool:
    """Make sure macOS permissions are granted; guide the user if not."""
    if sys.platform != "darwin":
        ui.say("  Nothing to grant on this platform.")
        return True

    from glance.permissions import (
        accessibility_trusted,
        input_monitoring_granted,
        open_privacy_settings,
        request_accessibility,
        request_input_monitoring,
    )

    app = ui.app_name

    if accessibility_trusted():
        ui.say("  Accessibility: granted")
    else:
        if not ui.confirm(
            "Glance needs Accessibility permission to move the cursor.\n\n"
            f"In the System Settings window that opens, switch on “{app}”."
        ):
            return False
        request_accessibility()
        open_privacy_settings("accessibility")
        if not _wait_until(accessibility_trusted, "Waiting for Accessibility...", ui):
            ui.alert("Accessibility permission was not granted.")
            ui.restart()
            return False
        ui.notify("Accessibility: granted")

    if input_monitoring_granted():
        ui.say("  Input Monitoring: granted")
    else:
        if not ui.confirm(
            "Glance needs Input Monitoring to notice your trackpad, mouse and keyboard, "
            "so it never moves the cursor while you are using them.\n\n"
            f"In the System Settings window that opens, switch on “{app}”."
        ):
            return False
        request_input_monitoring()
        open_privacy_settings("input_monitoring")
        _wait_until(input_monitoring_granted, "Waiting for Input Monitoring...", ui)
        # macOS only applies Input Monitoring to apps started after it was granted.
        ui.restart()
        return False

    return True


def _wait_until(check: Callable[[], bool | None], message: str, ui) -> bool:
    ui.notify(message)
    end = time.monotonic() + PERMISSION_WAIT_SECONDS
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(1)
    return False


def _start_camera(settings: Settings, ui):
    from glance.gaze import CameraError, GazeTracker

    ui.say("  Starting the camera (the face model is downloaded the first time)...")
    for _ in range(3):
        tracker = GazeTracker(settings.camera_index)
        try:
            tracker.start()
            ui.say("  Camera: working")
            return tracker
        except CameraError:
            tracker.stop()
            message = f"Glance could not open camera {settings.camera_index}."
            if sys.platform == "darwin":
                from glance.permissions import open_privacy_settings

                open_privacy_settings("camera")
                message += (
                    f"\n\nAllow camera access for “{ui.app_name}” when macOS asks, "
                    "or switch it on in the System Settings window that opened."
                )
            if not ui.confirm(message, ok="Try again"):
                return None
    ui.alert(
        "The camera still doesn't open. If you just changed camera permissions, restart "
        "Glance. Another camera can be chosen with `glance config`."
    )
    return None


def _wait_for_face(tracker, ui, timeout: float = 15.0) -> bool:
    ui.say("  Looking for your face...")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        sample = tracker.latest()
        if sample is not None and sample.features is not None:
            ui.say("  I can see you.")
            return True
        time.sleep(0.05)
    ui.alert(
        "Glance can't see your face. Make sure the camera points at you and your face is "
        "well lit, then start Glance again."
    )
    return False


def format_report(monitors: list[Monitor], report) -> str:
    lines = []
    rows = zip(monitors, report.accuracy_per_monitor, report.point_error_per_monitor, strict=True)
    for m, accuracy, error in rows:
        name = m.name or m.label()
        lines.append(f"{name}: recognised {accuracy:.0%}, cursor lands ~{error:.0f} pt from gaze")
    return "\n".join(lines)


def print_report(monitors: list[Monitor], report) -> None:
    for line in format_report(monitors, report).splitlines():
        print(f"  {line}")


def _calibrate(tracker, monitors: list[Monitor], ui) -> bool:
    from glance.calibration import CalibrationError, run_calibration
    from glance.overlay import create_overlay

    message = (
        "Calibration: a red dot appears on each monitor in turn. Look at it until it "
        "moves (about 16 seconds per monitor).\n\n"
        "Sit as you normally do; turning your head towards each monitor is fine."
    )
    while True:
        if not ui.confirm(message, ok="Start"):
            return False
        try:
            report = run_calibration(tracker, monitors, create_overlay(), log=lambda _: None)
        except CalibrationError as exc:
            message = f"Calibration failed: {exc}\n\nTry again?"
            continue

        summary = format_report(monitors, report)
        if min(report.accuracy_per_monitor) >= GOOD_ACCURACY:
            report.model.save(calibration_path())
            ui.say(summary)
            return True

        retry = ui.confirm(
            f"{summary}\n\nSome monitors are hard to tell apart. Turning your head a little "
            "towards each monitor while looking at the dots usually helps.",
            ok="Try again",
            cancel="Keep this",
        )
        if not retry:
            report.model.save(calibration_path())
            return True
        message = "Ready to calibrate again?"
