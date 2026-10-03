"""Maps gaze features to the monitor being looked at.

A distance-weighted k-nearest-neighbours classifier over standardised features.
Calibration samples from several points on each monitor form irregular clusters,
which k-NN handles well with no training step. Samples far from everything seen
during calibration (looking at the keyboard, a phone, away) yield no prediction.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT_VERSION = 1


@dataclass
class GazeModel:
    monitor_keys: list[str]
    layout: str
    mean: np.ndarray
    std: np.ndarray
    samples: np.ndarray  # standardised, shape (n, d)
    labels: np.ndarray  # monitor index per sample, shape (n,)
    novelty_threshold: float
    k: int = 7

    @property
    def n_monitors(self) -> int:
        return len(self.monitor_keys)

    @classmethod
    def fit(
        cls,
        features: Sequence[Sequence[float]],
        labels: Sequence[int],
        monitor_keys: list[str],
        layout: str,
        k: int = 7,
        novelty_scale: float = 3.0,
    ) -> GazeModel:
        x = np.asarray(features, dtype=np.float64)
        y = np.asarray(labels, dtype=np.int64)
        if x.ndim != 2 or len(x) != len(y) or len(x) == 0:
            raise ValueError("features must be a non-empty 2D array matching labels")
        missing = set(range(len(monitor_keys))) - set(y.tolist())
        if missing:
            raise ValueError(f"no calibration samples for monitors {sorted(missing)}")

        mean = x.mean(axis=0)
        std = x.std(axis=0)
        std[std < 1e-6] = 1.0
        z = (x - mean) / std
        k = max(1, min(k, len(z) - 1))

        # Typical spread of the data: distance from each sample to its k nearest others.
        dists = np.linalg.norm(z[:, None, :] - z[None, :, :], axis=2)
        np.fill_diagonal(dists, np.inf)
        knn = np.sort(dists, axis=1)[:, :k].mean(axis=1)
        threshold = float(np.percentile(knn, 95) * novelty_scale)

        return cls(monitor_keys, layout, mean, std, z, y, max(threshold, 1e-6), k)

    def predict_proba(self, feature: Sequence[float]) -> np.ndarray | None:
        """Per-monitor probabilities, or None if the gaze matches no monitor."""
        z = (np.asarray(feature, dtype=np.float64) - self.mean) / self.std
        dists = np.linalg.norm(self.samples - z, axis=1)
        k = min(self.k, len(dists))
        nearest = np.argpartition(dists, k - 1)[:k]
        near_d = dists[nearest]
        if near_d.mean() > self.novelty_threshold:
            return None
        weights = 1.0 / (near_d + 1e-6)
        votes = np.bincount(self.labels[nearest], weights=weights, minlength=self.n_monitors)
        return votes / votes.sum()

    def save(self, path: Path) -> None:
        data = {
            "version": FORMAT_VERSION,
            "monitor_keys": self.monitor_keys,
            "layout": self.layout,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "samples": np.round(self.samples, 5).tolist(),
            "labels": self.labels.tolist(),
            "novelty_threshold": self.novelty_threshold,
            "k": self.k,
        }
        path.write_text(json.dumps(data))

    @classmethod
    def load(cls, path: Path) -> GazeModel:
        data = json.loads(path.read_text())
        if data.get("version") != FORMAT_VERSION:
            raise ValueError("calibration was made by an incompatible version; recalibrate")
        return cls(
            monitor_keys=data["monitor_keys"],
            layout=data["layout"],
            mean=np.asarray(data["mean"]),
            std=np.asarray(data["std"]),
            samples=np.asarray(data["samples"]),
            labels=np.asarray(data["labels"], dtype=np.int64),
            novelty_threshold=float(data["novelty_threshold"]),
            k=int(data["k"]),
        )
