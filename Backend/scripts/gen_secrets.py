"""Print fresh production secrets in .env format.

uv run python scripts/gen_secrets.py
"""

import base64
import secrets

print(f"SAP_MASTER_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}")
print("# Password for the sap_engine role (run in the Supabase SQL editor):")
print(f"#   alter role sap_engine with password '{secrets.token_urlsafe(30)}';")
