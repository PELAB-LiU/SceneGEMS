import hashlib

import pytest

from scenegems_tool.persistence.canonical_json import canonical_json, canonical_json_sha256


def test_key_order_and_whitespace_do_not_matter():
    assert canonical_json({"b": 1, "a": [1, 2, {"d": None, "c": "x"}]}) == '{"a":[1,2,{"c":"x","d":null}],"b":1}'
    assert canonical_json_sha256({"b": 1, "a": 2}) == canonical_json_sha256({"a": 2, "b": 1})


def test_unicode_is_kept_and_the_hash_is_its_utf8_sha256():
    assert canonical_json({"name": "Göteborg"}) == '{"name":"Göteborg"}'
    assert canonical_json_sha256({"name": "Göteborg"}) == hashlib.sha256('{"name":"Göteborg"}'.encode("utf-8")).hexdigest()


def test_not_a_number_is_refused():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
