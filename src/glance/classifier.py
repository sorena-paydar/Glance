"""Maps gaze features to the monitor being looked at.

A distance-weighted k-nearest-neighbours classifier over standardised features.
Calibration samples from several points on each monitor form irregular clusters,
which k-NN handles well with no training step. Samples far from everything seen
during calibration (looking at the keyboard, a phone, away) yield no prediction.

Within each monitor, a ridge regression maps the same features to where on the
screen you are looking, so the cursor can land near your gaze point.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT_VERSION = 2
READABLE_VERSIONS = (1, 2)
RIDGE_ALPHAS = (0.3, 3.0, 30.0, 300.0)


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
    # Per monitor: (d + 1, 2) weights mapping standardised features to a relative
    # (x, y) position on that monitor. None for calibrations without targets.
    point_weights: list[np.ndarray] | None = None
    # Per monitor: expected gaze point error (leave-one-target-out), in points.
    point_error: list[float] | None = None

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
        groups: Sequence[int] | None = None,
        k: int = 7,
        novelty_scale: float = 1.5,
        targets: Sequence[tuple[float, float]] | None = None,
        monitor_sizes: Sequence[tuple[float, float]] | None = None,
    ) -> GazeModel:
        """Fit the model.

        ``groups`` identifies the calibration target each sample was taken at. When
        given, the novelty threshold is derived from the gaps between targets on the
        same monitor, so gaze anywhere between targets still counts as that monitor.

        ``targets`` gives the relative (x, y) position of each sample's target on its
        monitor; with ``groups`` it enables gaze point prediction. ``monitor_sizes``
        (width, height) express the reported point error in screen points.
        """
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

        dists = np.linalg.norm(z[:, None, :] - z[None, :, :], axis=2)
        np.fill_diagonal(dists, np.inf)
        if groups is not None:
            # Distance from each sample to the nearest sample of another target on
            # the same monitor: the size of the gaps inside a monitor's region.
            g = np.asarray(groups)
            unrelated = (y[:, None] != y[None, :]) | (g[:, None] == g[None, :])
            gaps = np.where(unrelated, np.inf, dists).min(axis=1)
            spread = gaps[np.isfinite(gaps)]
        else:
            spread = np.array([])
        if spread.size == 0:
            spread = dists.min(axis=1)
        threshold = float(np.percentile(spread, 95) * novelty_scale)

        model = cls(monitor_keys, layout, mean, std, z, y, max(threshold, 1e-6), k)
        if targets is not None and groups is not None:
            t = np.asarray(targets, dtype=np.float64)
            g = np.asarray(groups)
            sizes = monitor_sizes or [(1.0, 1.0)] * len(monitor_keys)
            model.point_weights, model.point_error = [], []
            for m in range(len(monitor_keys)):
                on = y == m
                weights, error = _fit_points(z[on], t[on], g[on], np.asarray(sizes[m]))
                model.point_weights.append(weights)
                model.point_error.append(error)
        return model

    def predict_proba(self, feature: Sequence[float]) -> np.ndarray | None:
        """Per-monitor probabilities, or None if the gaze matches no monitor."""
        z = (np.asarray(feature, dtype=np.float64) - self.mean) / self.std
        dists = np.linalg.norm(self.samples - z, axis=1)
        k = min(self.k, len(dists))
        nearest = np.argpartition(dists, k - 1)[:k]
        near_d = dists[nearest]
        if near_d.min() > self.novelty_threshold:
            return None
        weights = 1.0 / (near_d + 1e-6)
        votes = np.bincount(self.labels[nearest], weights=weights, minlength=self.n_monitors)
        return votes / votes.sum()

    def predict_point(self, feature: Sequence[float], monitor: int) -> tuple[float, float] | None:
        """Relative (x, y) position on ``monitor`` being looked at, clipped to 0..1."""
        if not self.point_weights:
            return None
        z = (np.asarray(feature, dtype=np.float64) - self.mean) / self.std
        x, y = np.clip(np.append(z, 1.0) @ self.point_weights[monitor], 0.0, 1.0)
        return float(x), float(y)

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
            "point_weights": (
                [w.tolist() for w in self.point_weights] if self.point_weights else None
            ),
            "point_error": self.point_error,
        }
        path.write_text(json.dumps(data))

    @classmethod
    def load(cls, path: Path) -> GazeModel:
        data = json.loads(path.read_text())
        if data.get("version") not in READABLE_VERSIONS:
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
            point_weights=(
                [np.asarray(w) for w in data["point_weights"]]
                if data.get("point_weights")
                else None
            ),
            point_error=data.get("point_error"),
        )


def _ridge(z: np.ndarray, t: np.ndarray, alpha: float) -> np.ndarray:
    x = np.hstack([z, np.ones((len(z), 1))])
    penalty = alpha * np.eye(x.shape[1])
    penalty[-1, -1] = 0.0  # don't shrink the intercept
    return np.linalg.solve(x.T @ x + penalty, x.T @ t)


def _fit_points(
    z: np.ndarray, t: np.ndarray, g: np.ndarray, size: np.ndarray
) -> tuple[np.ndarray, float]:
    """Ridge weights for one monitor, with alpha chosen by leave-one-target-out error.

    Returns the weights and the mean error of the best alpha, scaled by ``size``.
    """
    best_alpha, best_error = RIDGE_ALPHAS[0], float("inf")
    groups = np.unique(g)
    if len(groups) >= 3:
        for alpha in RIDGE_ALPHAS:
            errors = []
            for group in groups:
                held = g == group
                weights = _ridge(z[~held], t[~held], alpha)
                predicted = np.clip(np.hstack([z[held], np.ones((held.sum(), 1))]) @ weights, 0, 1)
                errors.append(np.linalg.norm((predicted - t[held]) * size, axis=1))
            error = float(np.concatenate(errors).mean())
            if error < best_error:
                best_alpha, best_error = alpha, error
    return _ridge(z, t, best_alpha), best_error
