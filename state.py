import json
import os
from pathlib import Path
from loguru import logger
from config import settings

STATE_PATH = Path("state") / "state.json"
GCS_BLOB_NAME = "state.json"


def load_state() -> dict:
    if settings.gcs_bucket_name:
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(settings.gcs_bucket_name)
            blob = bucket.blob(GCS_BLOB_NAME)
            if blob.exists():
                data = blob.download_as_text(encoding="utf-8")
                return json.loads(data)
            logger.info("GCS blob state.json does not exist yet; returning empty state.")
            return {}
        except Exception as e:
            logger.error(f"Failed to load state from GCS bucket {settings.gcs_bucket_name}: {e}")
            return {}

    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    if settings.gcs_bucket_name:
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(settings.gcs_bucket_name)
            blob = bucket.blob(GCS_BLOB_NAME)
            blob.upload_from_string(
                json.dumps(state, indent=2),
                content_type="application/json",
            )
            logger.info(f"Saved state to GCS bucket {settings.gcs_bucket_name}")
            return
        except Exception as e:
            logger.error(f"Failed to save state to GCS bucket {settings.gcs_bucket_name}: {e}")
            return

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)
