"""Platform permission checks and requests (macOS privacy settings)."""

from __future__ import annotations

import ctypes
import subprocess
import sys

_APP_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_IOKIT = "/System/Library/Frameworks/IOKit.framework/IOKit"
_LISTEN_EVENT = 1  # kIOHIDRequestTypeListenEvent
_ACCESS_GRANTED = 0  # kIOHIDAccessTypeGranted

SETTINGS_PANES = {
    "accessibility": "Privacy_Accessibility",
    "input_monitoring": "Privacy_ListenEvent",
    "camera": "Privacy_Camera",
}


def _load(path: str):
    if sys.platform != "darwin":
        return None
    try:
        return ctypes.cdll.LoadLibrary(path)
    except OSError:
        return None


def accessibility_trusted() -> bool | None:
    """Whether this process may control input (macOS Accessibility).

    Returns None on platforms where this does not apply.
    """
    services = _load(_APP_SERVICES)
    if services is None:
        return None
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(services.AXIsProcessTrusted())


def request_accessibility() -> bool | None:
    """Check Accessibility trust, showing the system prompt if not yet granted."""
    services = _load(_APP_SERVICES)
    if services is None:
        return None
    import objc
    from Foundation import NSDictionary

    options = NSDictionary.dictionaryWithDictionary_({"AXTrustedCheckOptionPrompt": True})
    services.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
    services.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
    return bool(services.AXIsProcessTrustedWithOptions(objc.pyobjc_id(options)))


def input_monitoring_granted() -> bool | None:
    """Whether this process may observe keyboard and pointer events (macOS)."""
    iokit = _load(_IOKIT)
    if iokit is None:
        return None
    iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
    iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
    return iokit.IOHIDCheckAccess(_LISTEN_EVENT) == _ACCESS_GRANTED


def request_input_monitoring() -> bool | None:
    """Ask for Input Monitoring, showing the system prompt the first time."""
    iokit = _load(_IOKIT)
    if iokit is None:
        return None
    iokit.IOHIDRequestAccess.restype = ctypes.c_bool
    iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
    return bool(iokit.IOHIDRequestAccess(_LISTEN_EVENT))


def open_privacy_settings(permission: str) -> None:
    """Open System Settings at the privacy pane for ``permission`` (macOS only)."""
    if sys.platform != "darwin":
        return
    pane = SETTINGS_PANES[permission]
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane}"
    subprocess.run(["open", url], check=False)


MACOS_PERMISSION_HELP = """\
Glance needs these macOS permissions for the app that runs it (your terminal,
e.g. Terminal, iTerm or Ghostty):
  - Camera:            System Settings > Privacy & Security > Camera
  - Accessibility:     System Settings > Privacy & Security > Accessibility
  - Input Monitoring:  System Settings > Privacy & Security > Input Monitoring
Restart the terminal after granting them, or run `glance setup` for guidance."""
