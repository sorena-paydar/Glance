"""Menu bar (macOS) / system tray (Windows, Linux) icon.

Requires the ``tray`` extra: ``pip install glance[tray]``.
"""

from __future__ import annotations

import sys
import threading

from glance.app import GlanceApp

ACTIVE = (64, 156, 255, 255)
PAUSED = (150, 150, 150, 255)


def _icon_image(color: tuple[int, int, int, int]):
    from PIL import Image, ImageDraw

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 16, 60, 48), outline=color, width=5)  # eye outline
    draw.ellipse((22, 22, 42, 42), fill=color)  # iris
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

    icon = pystray.Icon(
        "glance",
        _icon_image(ACTIVE),
        "Glance",
        menu=pystray.Menu(
            pystray.MenuItem("Paused", toggle, checked=is_paused),
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
