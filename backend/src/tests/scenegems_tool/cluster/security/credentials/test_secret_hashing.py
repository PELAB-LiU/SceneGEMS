from scenegems_tool.cluster.security.credentials.secret_hashing import hash_secret, new_secret, token_lookup_key, verify_secret


def test_new_secrets_are_long_and_distinct():
    secrets = {new_secret() for _ in range(20)}
    assert len(secrets) == 20
    assert all(len(secret) >= 43 for secret in secrets)


def test_hash_verifies_only_the_same_secret():
    stored = hash_secret("correct horse battery staple")
    assert verify_secret("correct horse battery staple", stored)
    assert not verify_secret("correct horse battery stapl", stored)
    assert not verify_secret("", stored)


def test_hash_is_salted_and_does_not_contain_the_secret():
    first, second = hash_secret("same secret value"), hash_secret("same secret value")
    assert first != second
    assert "same secret value" not in first
    assert first.startswith("scrypt$")


def test_malformed_hashes_never_match():
    for stored in ["", "scrypt$1$2", "sha256$abc", "scrypt$x$8$1$AAAA$AAAA", hash_secret("a").replace("scrypt", "bcrypt")]:
        assert not verify_secret("a", stored)


def test_token_lookup_key_is_a_stable_sha256_hex_digest():
    assert token_lookup_key("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
