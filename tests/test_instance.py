import subprocess
import sys

from glance import instance


def test_second_instance_is_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(instance, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(instance, "_lock_file", None)
    assert instance.already_running(wait=0) is False
    # Another process now sees the lock as taken.
    code = (
        "from pathlib import Path; from glance import instance; "
        f"instance.cache_dir = lambda: Path({str(tmp_path)!r}); "
        "print(instance.already_running(wait=0))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "True"
