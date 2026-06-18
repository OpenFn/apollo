import pytest
from _instance_auth.hash_token import hash_token

# Pinned hash shared with platform/test/auth.unit.test.ts. If the Python and TS
# hashers ever disagree, every client silently fails to authenticate.
KNOWN_TOKEN = "openfn-apollo-test-token"
KNOWN_HASH = "58bf5a6b4e6fb8c6236c07cecad297478b484a7213d2b6e3ff92b309f9d41273"


@pytest.mark.unit
def test_hash_token_matches_pinned_cross_language_hash() -> None:
    assert hash_token(KNOWN_TOKEN) == KNOWN_HASH
