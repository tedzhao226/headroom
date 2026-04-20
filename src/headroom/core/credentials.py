import base64
import json
import os

from google.oauth2 import service_account


def get_gcp_credentials() -> service_account.Credentials:
    """Decode GCP_SA_KEY env var and return service account credentials."""
    raw = os.environ.get("GCP_SA_KEY")
    if not raw:
        raise RuntimeError("GCP_SA_KEY environment variable is not set")

    info = json.loads(base64.b64decode(raw))
    return service_account.Credentials.from_service_account_info(info)
