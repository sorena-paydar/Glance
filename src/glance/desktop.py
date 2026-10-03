"""Put Glance on the desktop and in the app launcher.

* macOS: ``~/Applications/Glance.app`` (Launchpad, Spotlight) plus a link on the
  Desktop. The app runs in the menu bar with no terminal and guides first-time
  setup with native dialogs. macOS asks for permissions for "Glance" itself.
* Windows: Desktop and Start menu shortcuts.
* Linux: a desktop entry in the app launcher and on the Desktop.
"""

from __future__ import annotations

import hashlib
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


def macos_info_plist_overrides() -> dict:
    """Keys set on top of the Info.plist that osacompile generates."""
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleIconFile": "applet",
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


def macos_launcher_script(exe: Path, log: Path) -> str:
    """AppleScript for the app: start Glance in the background, then quit.

    A compiled applet is a real app that checks in with macOS (a shell script as
    the bundle executable never does, so macOS reports it as "not open anymore").
    Glance keeps running in the menu bar, and macOS attributes its permission
    requests to this app.
    """
    command = (
        '"export GLANCE_APP_BUNDLE=" & quoted form of (POSIX path of (path to me)) & '
        f'"; nohup " & quoted form of "{exe}" & " app >> " & quoted form of "{log}" & '
        '" 2>&1 < /dev/null &"'
    )
    # The short delay lets macOS finish registering the launch before the applet
    # quits; otherwise `open` reports error -600.
    return f"on run\n\tdo shell script {command}\n\tdelay 1\nend run\n"


def _install_macos(exe: Path) -> list[Path]:
    app = _macos_app_path()
    script = macos_launcher_script(exe, log_path())
    icns = _icns_bytes() if _icon_available() else b""
    overrides = macos_info_plist_overrides()
    stamp = hashlib.sha256(
        script.encode() + icns + plistlib.dumps(overrides, sort_keys=True)
    ).hexdigest()
    stamp_file = app / "Contents" / "Resources" / "glance-build.txt"

    # Rebuild only when something changed: every rebuild gets a new ad-hoc
    # signature, and macOS would forget the permissions granted to Glance.
    if not (stamp_file.exists() and stamp_file.read_text() == stamp):
        _build_applet(app, script, overrides, icns)
        stamp_file.write_text(stamp)
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


def _build_applet(app: Path, script: str, overrides: dict, icns: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        built = Path(tmp) / f"{APP_NAME}.app"
        subprocess.run(["osacompile", "-o", str(built), "-e", script], check=True)
        info_path = built / "Contents" / "Info.plist"
        info = plistlib.loads(info_path.read_bytes())
        info.update(overrides)
        info.pop("CFBundleIconName", None)  # use our .icns, not the asset catalog
        info_path.write_bytes(plistlib.dumps(info))
        resources = built / "Contents" / "Resources"
        (resources / "Assets.car").unlink(missing_ok=True)
        if icns:
            (resources / "applet.icns").write_bytes(icns)
        if app.exists():
            shutil.rmtree(app)
        app.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(built), str(app))


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
