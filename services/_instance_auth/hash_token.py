"""Mint and/or hash a Lightning client bearer token for the lightning_clients table.

Usage (run from the repo root):

    # Generate a fresh token and print its hash + a ready-to-edit INSERT:
    poetry run python services/_instance_auth/hash_token.py

    # Hash a token you already have:
    poetry run python services/_instance_auth/hash_token.py <token>

The plaintext token goes into the Lightning instance config as
`Authorization: Bearer <token>`. Only the SHA-256 hash is stored in the DB. The
hash here must match the one Apollo computes in platform/src/middleware/auth.ts
(sha256 over the UTF-8 bytes, lowercase hex) -- it does.
"""

import hashlib
import secrets
import sys


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def main() -> None:
    if len(sys.argv) > 1:
        token = sys.argv[1]
        generated = False
    else:
        token = secrets.token_urlsafe(32)
        generated = True

    digest = hash_token(token)

    lines = []
    if generated:
        lines.append("Generated a new client token.\n")
        lines.append(f"  token (give to the Lightning instance): {token}")
    lines.append(f"  auth_token_hash (store in the DB):       {digest}\n")
    lines.append("Example INSERT (set name and the client's Anthropic key):\n")
    lines.append(
        "  INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)\n"
        f"  VALUES ('my-lightning-instance', '{digest}', 'sk-ant-...');",
    )

    print("\n".join(lines))  # noqa: T201


if __name__ == "__main__":
    main()
