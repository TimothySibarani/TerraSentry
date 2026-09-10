from terrasentry_integrations.cache import geometry_hash


def _polygon(coords: list[list[list[float]]]) -> dict:
    return {"type": "Polygon", "coordinates": coords}


def test_hash_is_stable_across_key_order() -> None:
    first = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]}
    second = {"coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]], "type": "Polygon"}
    assert geometry_hash(first) == geometry_hash(second)


def test_hash_ignores_float_noise_below_six_decimals() -> None:
    base = _polygon([[[101.0, 0.0], [101.0000004, 0.0], [101.0, 0.01], [101.0, 0.0]]])
    noisy = _polygon([[[101.0, 0.0], [101.00000049, 0.0], [101.0, 0.01], [101.0, 0.0]]])
    assert geometry_hash(base) == geometry_hash(noisy)


def test_hash_changes_for_different_geometry() -> None:
    first = _polygon([[[101.0, 0.0], [101.01, 0.0], [101.01, 0.01], [101.0, 0.0]]])
    second = _polygon([[[101.0, 0.0], [101.02, 0.0], [101.02, 0.01], [101.0, 0.0]]])
    assert geometry_hash(first) != geometry_hash(second)
