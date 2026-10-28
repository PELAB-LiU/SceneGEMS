import pytest

from scenegems_tool.cluster.scope_names import is_scope_name


@pytest.mark.parametrize("value", ["", "-a", "a-", "A", "a_b", "a.b", "a/b", "+", "#", "$SYS", "a" * 64, None, 3])
def test_invalid_scope_names(value):
    assert not is_scope_name(value)
