from pathlib import PurePosixPath as Path  # these files are for macOS and Linux

from glance.desktop import (
    BUNDLE_ID,
    linux_desktop_entry,
    macos_info_plist_overrides,
    macos_launcher_script,
)


def test_macos_plist_overrides_make_a_menu_bar_app_with_camera_reason():
    info = macos_info_plist_overrides()
    assert info["CFBundleIdentifier"] == BUNDLE_ID
    assert info["LSUIElement"] is True
    assert "camera" in info["NSCameraUsageDescription"]


def test_macos_launcher_starts_app_mode_in_background():
    script = macos_launcher_script(Path("/opt/glance/bin/glance"), Path("/tmp/glance.log"))
    assert script.startswith("on run")
    assert 'quoted form of "/opt/glance/bin/glance" & " app >> "' in script
    assert "GLANCE_APP_BUNDLE" in script
    assert script.rstrip().endswith("end run")
    assert '2>&1 < /dev/null &"' in script


def test_linux_desktop_entry():
    entry = linux_desktop_entry(Path("/home/u/.local/bin/glance"), Path("/i.png"))
    assert entry.startswith("[Desktop Entry]")
    assert 'Exec="/home/u/.local/bin/glance"' in entry
    assert "Terminal=true" in entry


def test_icons_render_from_bundled_assets():
    from glance.desktop import render_icon
    from glance.tray import _icon_image

    icon = render_icon(64)
    assert icon.size == (64, 64) and icon.mode == "RGBA"
    tray = _icon_image((65, 87, 234))
    assert tray.size == (64, 64)
    assert tray.getbbox() is not None  # not empty
