"""Print fresh production secrets in .env format.

    uv run python scripts/gen_secrets.py >> ../.env
"""

import base64
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pem = Ed25519PrivateKey.generate().private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
print(f"SAP_MASTER_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}")
print(f'SAP_JWT_PRIVATE_KEY="{pem.decode().strip().replace(chr(10), chr(92) + "n")}"')
print(f"POSTGRES_ADMIN_PASSWORD={secrets.token_urlsafe(24)}")
print(f"SAP_DB_PASSWORD={secrets.token_urlsafe(24)}")
