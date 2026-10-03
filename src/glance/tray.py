"""Menu bar (macOS) / system tray (Windows, Linux) icon.

Requires the ``tray`` extra: ``pip install glance[tray]``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from glance.app import GlanceApp
from glance.config import recalibrate_request_path

ACTIVE = (65, 87, 234)  # logo blue
PAUSED = (150, 150, 150)
MARK = Path(__file__).parent / "assets" / "mark.png"


def _icon_image(color: tuple[int, int, int]):
    """The Glance mark in ``color``, centred on a square transparent canvas."""
    from PIL import Image

    with Image.open(MARK) as mark:
        alpha = mark.convert("RGBA").getchannel("A")
    size = 64
    alpha.thumbnail((size, size), Image.LANCZOS)
    tinted = Image.new("RGBA", alpha.size, (*color, 255))
    tinted.putalpha(alpha)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    image.paste(tinted, ((size - alpha.width) // 2, (size - alpha.height) // 2), tinted)
    return image


def run_with_tray(app: GlanceApp) -> None:
    """Show the tray icon on the main thread and run Glance in the background."""
    import pystray

    def is_paused(item) -> bool:
        return app.paused.is_set()

    def toggle(icon, item) -> None:
        app.toggle_pause()
        icon.icon = _icon_image(PAUSED if app.paused.is_set() else ACTIVE)

    def quit_(icon, item) -> None:
        app.stopped.set()
        icon.stop()

    def recalibrate(icon, item) -> None:
        # Calibration needs the main thread, which the icon owns: restart into it.
        recalibrate_request_path().touch()
        bundle = os.environ["GLANCE_APP_BUNDLE"]
        subprocess.Popen(["/bin/sh", "-c", f'sleep 2; open -n "{bundle}"'], start_new_session=True)
        quit_(icon, item)

    in_app = sys.platform == "darwin" and "GLANCE_APP_BUNDLE" in os.environ
    icon = pystray.Icon(
        "glance",
        _icon_image(ACTIVE),
        "Glance",
        menu=pystray.Menu(
            pystray.MenuItem("Paused", toggle, checked=is_paused),
            pystray.MenuItem("Recalibrate\u2026", recalibrate, visible=in_app),
            pystray.MenuItem("Quit Glance", quit_),
        ),
    )

    def worker() -> None:
        app.run()
        icon.stop()  # the app stopped on its own, e.g. the monitor layout changed

    threading.Thread(target=worker, name="glance-app", daemon=True).start()
    if sys.platform == "darwin":
        _hide_dock_icon()
    icon.run()


def _hide_dock_icon() -> None:
    """Run as a menu bar app: no Dock icon for the Python process."""
    import AppKit

    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory
    )
