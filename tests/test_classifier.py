import numpy as np
import pytest

from glance.classifier import GazeModel

CENTERS = np.array([[-20.0, 5.0, 0.2], [0.0, -10.0, 0.5], [25.0, 15.0, 0.8]])


def make_data(rng, per_class=60, noise=1.5):
    features, labels = [], []
    for label, center in enumerate(CENTERS):
        features.append(center + rng.normal(0, noise, size=(per_class, len(center))))
        labels += [label] * per_class
    return np.vstack(features), labels


@pytest.fixture
def model():
    rng = np.random.default_rng(0)
    x, y = make_data(rng)
    return GazeModel.fit(x, y, ["a", "b", "c"], layout="a|b|c")


def test_predicts_each_monitor(model):
    for label, center in enumerate(CENTERS):
        probs = model.predict_proba(center)
        assert probs is not None
        assert probs.argmax() == label
        assert probs[label] > 0.9
        assert probs.sum() == pytest.approx(1.0)


def test_far_away_gaze_is_unknown(model):
    assert model.predict_proba([200.0, -150.0, 9.0]) is None


def test_save_and_load_round_trip(model, tmp_path):
    path = tmp_path / "calibration.json"
    model.save(path)
    loaded = GazeModel.load(path)
    assert loaded.monitor_keys == model.monitor_keys
    assert loaded.layout == model.layout
    for center in CENTERS:
        np.testing.assert_allclose(
            loaded.predict_proba(center), model.predict_proba(center), atol=1e-3
        )


def test_fit_requires_samples_for_every_monitor():
    rng = np.random.default_rng(1)
    x, y = make_data(rng)
    with pytest.raises(ValueError, match="no calibration samples"):
        GazeModel.fit(x, y, ["a", "b", "c", "d"], layout="")


def test_constant_feature_does_not_break_scaling():
    x = [[1.0, 0.0], [1.1, 0.0], [5.0, 0.0], [5.1, 0.0]]
    model = GazeModel.fit(x, [0, 0, 1, 1], ["a", "b"], layout="", k=1)
    assert model.predict_proba([5.05, 0.0]).argmax() == 1


def test_gaze_between_targets_still_counts():
    rng = np.random.default_rng(2)
    features, labels, groups = [], [], []
    for label, center in enumerate(([-30.0, 0.0], [30.0, 0.0])):
        for gi, offset in enumerate(([0, 0], [8, 8], [-8, 8], [8, -8], [-8, -8])):
            features += list(np.asarray(center) + offset + rng.normal(0, 0.3, size=(20, 2)))
            labels += [label] * 20
            groups += [label * 10 + gi] * 20
    model = GazeModel.fit(features, labels, ["a", "b"], layout="", groups=groups)
    # Halfway between two targets on monitor "b": tight clusters, but still "b".
    probs = model.predict_proba([34.0, 4.0])
    assert probs is not None and probs.argmax() == 1
    # Far outside every monitor region.
    assert model.predict_proba([0.0, 80.0]) is None


def test_predicts_gaze_point_within_monitor():
    rng = np.random.default_rng(3)
    grid = [(x, y) for y in (0.1, 0.5, 0.9) for x in (0.1, 0.5, 0.9)]
    features, labels, groups, targets = [], [], [], []
    for label, offset in enumerate((-40.0, 40.0)):
        for gi, (tx, ty) in enumerate(grid):
            # Yaw tracks x, pitch tracks y; a third feature is pure noise.
            for _ in range(20):
                features.append(
                    [
                        offset + 30 * tx + rng.normal(0, 0.5),
                        20 * ty + rng.normal(0, 0.5),
                        rng.normal(0, 1),
                    ]
                )
                labels.append(label)
                groups.append(label * 100 + gi)
                targets.append((tx, ty))
    model = GazeModel.fit(
        features,
        labels,
        ["a", "b"],
        layout="",
        groups=groups,
        targets=targets,
        monitor_sizes=[(1000, 800), (1000, 800)],
    )
    x, y = model.predict_point([40 + 30 * 0.3, 20 * 0.7, 0.0], monitor=1)
    assert abs(x - 0.3) < 0.05 and abs(y - 0.7) < 0.05
    assert all(error < 60 for error in model.point_error)  # points, on a 1000x800 screen


def test_point_model_survives_save_and_load(tmp_path):
    rng = np.random.default_rng(4)
    grid = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]
    features, labels, groups, targets = [], [], [], []
    for gi, (tx, ty) in enumerate(grid):
        for _ in range(10):
            features.append([tx * 10 + rng.normal(0, 0.1), ty * 10 + rng.normal(0, 0.1)])
            labels.append(0)
            groups.append(gi)
            targets.append((tx, ty))
    model = GazeModel.fit(features, labels, ["a"], "", groups=groups, targets=targets)
    path = tmp_path / "c.json"
    model.save(path)
    loaded = GazeModel.load(path)
    assert loaded.predict_point([5, 5], 0) == pytest.approx(model.predict_point([5, 5], 0))
