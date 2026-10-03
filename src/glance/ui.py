"""How setup talks to the user: a terminal, or native dialogs for the desktop app."""

from __future__ import annotations

import os
import subprocess
import sys

TERMINALS = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "ghostty": "Ghostty",
    "WarpTerminal": "Warp",
    "vscode": "Visual Studio Code",
    "WezTerm": "WezTerm",
}


def terminal_name() -> str:
    program = os.environ.get("TERM_PROGRAM", "")
    return TERMINALS.get(program, program or "your terminal app")


class ConsoleUI:
    """Setup in a terminal: printed text and Enter to continue."""

    @property
    def app_name(self) -> str:
        """The app macOS grants permissions to: whatever terminal runs Glance."""
        return terminal_name()

    def step(self, number: int, title: str) -> None:
        print(f"\n[{number}/4] {title}")

    def say(self, text: str) -> None:
        print(text)

    def notify(self, text: str) -> None:
        print(f"  {text}")

    def alert(self, text: str) -> None:
        print(f"\n{text}")

    def confirm(self, text: str, ok: str = "Continue", cancel: str = "Quit") -> bool:
        print(f"\n{text}")
        try:
            answer = input(f"  Press Enter to {ok.lower()}, or type q to {cancel.lower()}: ")
        except EOFError:
            return False
        return answer.strip().lower() not in ("q", "quit", "n", "no")

    def restart(self) -> bool:
        """Restart so new permissions apply. False: the user has to do it."""
        print(f"\n  Quit {self.app_name} completely (Cmd+Q), reopen it and run `glance` again.")
        return False


class DialogUI(ConsoleUI):
    """Setup from the desktop app: native macOS dialogs and notifications."""

    @property
    def app_name(self) -> str:
        return "Glance"

    def step(self, number: int, title: str) -> None:
        print(f"[{number}/4] {title}", flush=True)  # goes to the log file

    def say(self, text: str) -> None:
        print(text, flush=True)

    def notify(self, text: str) -> None:
        print(text, flush=True)
        _osascript('display notification (item 1 of argv) with title "Glance"', text)

    def alert(self, text: str) -> None:
        _osascript(
            'display dialog (item 1 of argv) with title "Glance" buttons {"OK"} '
            'default button "OK" with icon note',
            text,
        )

    def confirm(self, text: str, ok: str = "Continue", cancel: str = "Quit") -> bool:
        result = _osascript(
            'display dialog (item 1 of argv) with title "Glance" '
            "buttons {(item 3 of argv), (item 2 of argv)} default button (item 2 of argv) "
            "with icon note",
            text,
            ok,
            cancel,
        )
        return result.strip() == f"button returned:{ok}"

    def restart(self) -> bool:
        bundle = os.environ.get("GLANCE_APP_BUNDLE")
        if not bundle:
            return super().restart()
        self.alert("Glance will now restart so the new permission takes effect.")
        subprocess.Popen(["/bin/sh", "-c", f'sleep 2; open -n "{bundle}"'], start_new_session=True)
        return True


def _osascript(body: str, *args: str) -> str:
    script = ["-e", "on run argv", "-e", body, "-e", "end run"]
    result = subprocess.run(
        ["osascript", *script, *args], capture_output=True, text=True, check=False
    )
    return result.stdout


def create_ui(gui: bool):
    return DialogUI() if gui and sys.platform == "darwin" else ConsoleUI()
