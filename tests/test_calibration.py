import numpy as np

from glance.calibration import leave_one_point_out_accuracy


def test_leave_one_point_out_accuracy_separable():
    rng = np.random.default_rng(0)
    centers = {0: [-20.0, 0.0], 1: [20.0, 0.0]}
    features, labels, groups = [], [], []
    group = 0
    for label, center in centers.items():
        for offset in ([0, 0], [3, 3], [-3, 3], [3, -3], [-3, -3]):
            pts = np.asarray(center) + offset + rng.normal(0, 0.5, size=(15, 2))
            features += list(pts)
            labels += [label] * 15
            groups += [group] * 15
            group += 1
    accuracy = leave_one_point_out_accuracy(features, labels, groups, ["a", "b"])
    assert accuracy == [1.0, 1.0]
