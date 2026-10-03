"""Full-screen calibration targets drawn on a chosen monitor.

macOS uses native AppKit windows so targets land on the exact screen; other
platforms use OpenCV windows. Both must be driven from the main thread by
calling ``pump()`` regularly.
"""

from __future__ import annotations

import sys

from glance.displays import Monitor


class Overlay:
    def show(self, monitor: Monitor, rel_x: float, rel_y: float, text: str, progress: float) -> None:
        """Draw a target at a relative position (0..1) on the monitor.

        ``progress`` (0..1) shrinks the target as sampling of that point completes.
        """
        raise NotImplementedError

    def pump(self, seconds: float = 0.0) -> None:
        """Process window events for up to ``seconds``."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def create_overlay() -> Overlay:
    if sys.platform == "darwin":
        return _AppKitOverlay()
    return _OpenCVOverlay()


TARGET_RADIUS = 28
MIN_RADIUS = 8


class _AppKitOverlay(Overlay):
    def __init__(self) -> None:
        import AppKit

        self._appkit = AppKit
        self._app = AppKit.NSApplication.sharedApplication()
        self._app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        self._window = None
        self._view = None
        self._monitor: Monitor | None = None

    def _screen_for(self, monitor: Monitor):
        for screen in self._appkit.NSScreen.screens():
            number = screen.deviceDescription().get("NSScreenNumber")
            if number is not None and int(number) == monitor.native_id:
                return screen
        return self._appkit.NSScreen.mainScreen()

    def _ensure_window(self, monitor: Monitor) -> None:
        if self._monitor == monitor and self._window is not None:
            return
        appkit = self._appkit
        if self._window is not None:
            self._window.orderOut_(None)
        frame = self._screen_for(monitor).frame()
        window = appkit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, appkit.NSWindowStyleMaskBorderless, appkit.NSBackingStoreBuffered, False
        )
        window.setFrame_display_(frame, True)
        window.setLevel_(appkit.NSScreenSaverWindowLevel)
        window.setOpaque_(False)
        window.setBackgroundColor_(appkit.NSColor.clearColor())
        window.setIgnoresMouseEvents_(True)
        window.setReleasedWhenClosed_(False)
        view = _target_view_class().alloc().initWithFrame_(((0, 0), frame.size))
        window.setContentView_(view)
        window.orderFrontRegardless()
        self._window, self._view, self._monitor = window, view, monitor

    def show(self, monitor, rel_x, rel_y, text, progress):
        self._ensure_window(monitor)
        self._view.target = (rel_x, rel_y, text, progress)
        self._view.setNeedsDisplay_(True)

    def pump(self, seconds=0.0):
        appkit = self._appkit
        deadline = appkit.NSDate.dateWithTimeIntervalSinceNow_(seconds)
        while True:
            event = self._app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                appkit.NSEventMaskAny, deadline, appkit.NSDefaultRunLoopMode, True
            )
            if event is None:
                break
            self._app.sendEvent_(event)
        self._app.updateWindows()

    def close(self):
        if self._window is not None:
            self._window.orderOut_(None)
            self._window = None
        self.pump(0)


_VIEW_CLASS = None


def _target_view_class():
    """Create the NSView subclass lazily: Objective-C classes can only be defined once."""
    global _VIEW_CLASS
    if _VIEW_CLASS is not None:
        return _VIEW_CLASS

    import AppKit

    class GlanceTargetView(AppKit.NSView):
        target = (0.5, 0.5, "", 0.0)

        def drawRect_(self, rect):
            bounds = self.bounds()
            w, h = bounds.size.width, bounds.size.height
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.05, 0.85).set()
            AppKit.NSRectFill(bounds)

            rel_x, rel_y, text, progress = self.target
            x, y = w * rel_x, h * (1 - rel_y)  # AppKit's y axis points up
            radius = TARGET_RADIUS - (TARGET_RADIUS - MIN_RADIUS) * progress
            AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.27, 0.23, 1.0).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                ((x - radius, y - radius), (2 * radius, 2 * radius))
            ).fill()
            AppKit.NSColor.whiteColor().set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(((x - 3, y - 3), (6, 6))).fill()

            if text:
                attrs = {
                    AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(22),
                    AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
                }
                label = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
                size = label.size()
                label.drawAtPoint_(((w - size.width) / 2, h * 0.5 - 60 if rel_y < 0.5 else h * 0.5 + 40))

    _VIEW_CLASS = GlanceTargetView
    return _VIEW_CLASS


class _OpenCVOverlay(Overlay):
    WINDOW = "Glance calibration"

    def __init__(self) -> None:
        import cv2

        self._cv2 = cv2
        self._monitor: Monitor | None = None

    def show(self, monitor, rel_x, rel_y, text, progress):
        import numpy as np

        cv2 = self._cv2
        if self._monitor != monitor:
            cv2.destroyAllWindows()
            cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
            cv2.moveWindow(self.WINDOW, monitor.x, monitor.y)
            cv2.setWindowProperty(self.WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            self._monitor = monitor

        w, h = monitor.width, monitor.height
        canvas = np.full((h, w, 3), 15, dtype=np.uint8)
        center = (int(w * rel_x), int(h * rel_y))
        radius = int(TARGET_RADIUS - (TARGET_RADIUS - MIN_RADIUS) * progress)
        cv2.circle(canvas, center, radius, (58, 69, 255), -1, cv2.LINE_AA)
        cv2.circle(canvas, center, 3, (255, 255, 255), -1, cv2.LINE_AA)
        if text:
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, _), _ = cv2.getTextSize(text, font, 0.9, 2)
            ty = h // 2 - 60 if rel_y > 0.5 else h // 2 + 60
            cv2.putText(canvas, text, ((w - tw) // 2, ty), font, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(self.WINDOW, canvas)

    def pump(self, seconds=0.0):
        self._cv2.waitKey(max(1, int(seconds * 1000)))

    def close(self):
        self._cv2.destroyAllWindows()
        self._cv2.waitKey(1)
