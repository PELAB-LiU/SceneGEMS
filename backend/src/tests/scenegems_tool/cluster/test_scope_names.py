import pytest

from scenegems_tool.cluster.scope_names import InvalidScopeName, ensure_scope_name, is_scope_name, slug_from_name


@pytest.mark.parametrize("value", ["a", "lab-master", "node-1-a1b2c3", "0", "a" * 63])
def test_valid_scope_names(value):
    assert is_scope_name(value)
    assert ensure_scope_name(value, "node id") == value


@pytest.mark.parametrize("value", ["", "-a", "a-", "A", "a_b", "a.b", "a/b", "+", "#", "$SYS", "a" * 64, None, 3])
def test_invalid_scope_names(value):
    assert not is_scope_name(value)


def test_error_names_what_was_wrong():
    with pytest.raises(InvalidScopeName, match="node id 'a/b'"):
        ensure_scope_name("a/b", "node id")


@pytest.mark.parametrize("name,slug", [("Lab PC 1", "lab-pc-1"), ("  GPU / box #2 ", "gpu-box-2"), ("!!!", "node"), ("", "node")])
def test_slug_from_name(name, slug):
    assert slug_from_name(name) == slug


def test_slug_is_bounded_and_never_ends_with_a_hyphen():
    slug = slug_from_name("ab-" * 30)
    assert len(slug) <= 40 and not slug.endswith("-")
