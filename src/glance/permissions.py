"""Platform permission checks."""

from __future__ import annotations

import ctypes
import sys


def accessibility_trusted() -> bool | None:
    """Whether this process may observe and control input (macOS Accessibility).

    Returns None on platforms where this does not apply.
    """
    if sys.platform != "darwin":
        return None
    try:
        services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
    except OSError:
        return None
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(services.AXIsProcessTrusted())


MACOS_PERMISSION_HELP = """\
Glance needs these macOS permissions for the app that runs it (your terminal,
e.g. Terminal, iTerm or Ghostty):
  - Camera:            System Settings > Privacy & Security > Camera
  - Accessibility:     System Settings > Privacy & Security > Accessibility
  - Input Monitoring:  System Settings > Privacy & Security > Input Monitoring
Restart the terminal after granting them."""
