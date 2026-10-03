"""Put Glance on the desktop and in the app launcher.

* macOS: ``~/Applications/Glance.app`` (Launchpad, Spotlight) plus a link on the
  Desktop. The app runs in the menu bar with no terminal and guides first-time
  setup with native dialogs. macOS asks for permissions for "Glance" itself.
* Windows: Desktop and Start menu shortcuts.
* Linux: a desktop entry in the app launcher and on the Desktop.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from glance import __version__
from glance.config import config_dir, log_path

BUNDLE_ID = "io.github.sorena-paydar.glance"
APP_NAME = "Glance"
DESCRIPTION = "Move your cursor to the monitor you are looking at"
ASSETS = Path(__file__).parent / "assets"


def glance_executable() -> Path:
    """The installed `glance` command that desktop entries should launch."""
    argv0 = Path(sys.argv[0])
    if argv0.stem == "glance" and argv0.exists():
        return argv0.resolve()
    found = shutil.which("glance")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError("cannot find the `glance` command; install Glance first")


def desktop_dir() -> Path:
    if sys.platform == "win32":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.stdout.strip():
            return Path(out.stdout.strip())
    if sys.platform.startswith("linux"):
        out = subprocess.run(
            ["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    return Path.home() / "Desktop"


def install_desktop_app() -> list[Path]:
    exe = glance_executable()
    if sys.platform == "darwin":
        return _install_macos(exe)
    if sys.platform == "win32":
        return _install_windows(exe)
    return _install_linux(exe)


def remove_desktop_app() -> list[Path]:
    removed = []
    for path in _installed_paths():
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            continue
        removed.append(path)
    return removed


def _installed_paths() -> list[Path]:
    desktop = desktop_dir()
    if sys.platform == "darwin":
        return [desktop / f"{APP_NAME}.app", _macos_app_path()]
    if sys.platform == "win32":
        start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
        return [desktop / f"{APP_NAME}.lnk", start_menu / f"{APP_NAME}.lnk"]
    applications = Path.home() / ".local/share/applications"
    return [desktop / "glance.desktop", applications / "glance.desktop"]


# -- icon ---------------------------------------------------------------------------


def render_icon(size: int):
    """The Glance app icon at ``size`` pixels, as a PIL image."""
    from PIL import Image

    with Image.open(ASSETS / "icon.png") as icon:
        return icon.convert("RGBA").resize((size, size), Image.LANCZOS)


def _icon_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


# -- macOS -----------------------------------------------------------------------


def _macos_app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def macos_info_plist() -> bytes:
    return plistlib.dumps(
        {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": APP_NAME,
            "CFBundleIconFile": APP_NAME,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "11.0",
            "LSUIElement": True,  # menu bar app: no Dock icon
            "NSHighResolutionCapable": True,
            "NSCameraUsageDescription": (
                "Glance uses the camera to see which monitor you are looking at. "
                "Video never leaves your Mac."
            ),
        }
    )


def macos_launcher(exe: Path, log: Path) -> str:
    return f"""#!/bin/sh
# Starts Glance as a desktop app. Created by `glance desktop`; recreated on reinstall.
GLANCE_APP_BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
export GLANCE_APP_BUNDLE
"{exe}" app >>"{log}" 2>&1
"""


def _write_if_changed(path: Path, data: bytes, mode: int | None = None) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mode is not None:
        path.chmod(mode)
    return True


def _install_macos(exe: Path) -> list[Path]:
    app = _macos_app_path()
    contents = app / "Contents"
    changed = _write_if_changed(contents / "Info.plist", macos_info_plist())
    changed |= _write_if_changed(
        contents / "MacOS" / APP_NAME, macos_launcher(exe, log_path()).encode(), 0o755
    )
    if _icon_available():
        changed |= _write_if_changed(contents / "Resources" / f"{APP_NAME}.icns", _icns_bytes())
    if changed:
        # A stable ad-hoc signature lets macOS remember the permissions granted to
        # Glance; it only changes when the bundle's contents do.
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], capture_output=True)
        lsregister = (
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
            "LaunchServices.framework/Support/lsregister"
        )
        subprocess.run([lsregister, "-f", str(app)], capture_output=True)

    link = desktop_dir() / f"{APP_NAME}.app"
    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(app)
    return [app, link]


def _icns_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{APP_NAME}.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            render_icon(size).save(iconset / f"icon_{size}x{size}.png")
            render_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
        target = Path(tmp) / f"{APP_NAME}.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
        return target.read_bytes()


# -- Windows ---------------------------------------------------------------------------


def _install_windows(exe: Path) -> list[Path]:
    icon = config_dir() / "glance.ico"
    if _icon_available():
        render_icon(256).save(icon, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    shortcuts = _installed_paths()
    for shortcut in shortcuts:
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($args[0]);"
            "$s.TargetPath = $args[1];"
            "$s.Description = $args[2];"
            "if (Test-Path $args[3]) { $s.IconLocation = $args[3] };"
            "$s.Save()"
        )
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                script,
                str(shortcut),
                str(exe),
                DESCRIPTION,
                str(icon),
            ],
            check=True,
        )
    return shortcuts


# -- Linux ---------------------------------------------------------------------------


def linux_desktop_entry(exe: Path, icon: Path) -> str:
    # Terminal=true: first-run setup is interactive in a terminal on Linux.
    return f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment={DESCRIPTION}
Exec="{exe}"
Icon={icon}
Terminal=true
Categories=Utility;Accessibility;
"""


def _install_linux(exe: Path) -> list[Path]:
    icon = config_dir() / "glance.png"
    if _icon_available():
        render_icon(256).save(icon)
    entry = linux_desktop_entry(exe, icon)
    paths = _installed_paths()
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry)
        path.chmod(0o755)
        # GNOME only launches desktop files marked as trusted.
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"], capture_output=True)
    return paths
