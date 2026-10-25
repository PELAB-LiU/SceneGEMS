from scenegems_tool.cluster.fingerprints.comparison import FingerprintMismatch, find_mismatches, images_to_rebuild


def test_matching_fingerprints_have_no_mismatch():
    assert find_mismatches({"a:latest": "1", "b:latest": "2"}, {"a:latest": "1"}) == []


def test_different_fingerprint_is_reported_with_both_values():
    assert find_mismatches({"a:latest": "old"}, {"a:latest": "new"}) == [FingerprintMismatch("a:latest", "new", "old")]


def test_missing_image_is_reported_as_missing():
    (mismatch,) = find_mismatches({}, {"a:latest": "1"})
    assert mismatch.missing and mismatch.actual is None


def test_images_not_required_are_ignored():
    assert find_mismatches({"extra:latest": "x"}, {}) == []


def test_images_to_rebuild_lists_missing_and_stale_images_sorted():
    actual = {"a:latest": "1", "b:latest": "old"}
    expected = {"c:latest": "3", "b:latest": "2", "a:latest": "1"}
    assert images_to_rebuild(actual, expected) == ["b:latest", "c:latest"]
