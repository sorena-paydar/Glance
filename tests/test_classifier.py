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
