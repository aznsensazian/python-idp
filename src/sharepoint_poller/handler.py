"""Lambda handler – REST API entry point for SharePoint document ingestion.

Invoked via API Gateway POST /extract.  Accepts a JSON payload containing
SharePoint connection details, extraction instructions, and an optional
modified_since filter.  Downloads matching documents from the SharePoint
document library to the raw S3 bucket, embedding the caller-supplied
extraction instructions as S3 object metadata so the downstream processor
can use them without SSM.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from shared.sharepoint_client import SharePointClient

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

RAW_BUCKET = os.environ.get("RAW_BUCKET", "")
TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")

# Maximum size for S3 user-metadata values (2 KB).  If the instructions JSON
# exceeds this we fall back to writing a sidecar object.
_META_LIMIT = 2048


def _api_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _validate_payload(payload: dict) -> list[str]:
    """Return a list of missing required fields."""
    errors = []
    for field in ("sharepoint", "extraction_instructions"):
        if field not in payload:
            errors.append(f"Missing required field: {field}")
    sp = payload.get("sharepoint", {})
    for key in ("tenant_id", "client_id", "client_secret", "site_url", "document_library"):
        if key not in sp:
            errors.append(f"Missing sharepoint.{key}")
    ei = payload.get("extraction_instructions", {})
    if "prompt_description" not in ei:
        errors.append("Missing extraction_instructions.prompt_description")
    return errors


def _get_last_poll_time(library_key: str) -> datetime | None:
    """Read the last successful poll timestamp from DynamoDB for a library."""
    if not TRACKING_TABLE:
        return None
    table = dynamodb.Table(TRACKING_TABLE)
    resp = table.get_item(Key={"pk": "POLL_STATE", "sk": library_key})
    item = resp.get("Item")
    if item and "timestamp" in item:
        return datetime.fromisoformat(item["timestamp"])
    return None


def _set_last_poll_time(library_key: str, ts: datetime) -> None:
    if not TRACKING_TABLE:
        return
    table = dynamodb.Table(TRACKING_TABLE)
    table.put_item(Item={
        "pk": "POLL_STATE",
        "sk": library_key,
        "timestamp": ts.isoformat(),
    })


def _store_instructions(request_id: str, instructions: dict) -> str:
    """Write extraction instructions as a sidecar JSON object in S3.

    Returns the S3 key of the sidecar.
    """
    key = f"instructions/{request_id}.json"
    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=key,
        Body=json.dumps(instructions),
        ContentType="application/json",
    )
    return key


def _upload_to_s3(file_bytes: bytes, file_name: str, metadata: dict,
                  instructions_key: str) -> str:
    """Upload raw document bytes and attach a pointer to the instructions sidecar."""
    key = f"raw/{file_name}"
    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=key,
        Body=file_bytes,
        Metadata={
            "sharepoint_id": metadata.get("id", ""),
            "last_modified": metadata.get("last_modified", ""),
            "original_name": file_name,
            "instructions_key": instructions_key,
        },
    )
    logger.info("Uploaded %s to s3://%s/%s", file_name, RAW_BUCKET, key)
    return key


def handler(event, context):
    """API Gateway Lambda proxy handler."""
    # Parse body – API Gateway sends it as a JSON string.
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _api_response(400, {"error": "Invalid JSON body"})

    errors = _validate_payload(body)
    if errors:
        return _api_response(400, {"errors": errors})

    sp = body["sharepoint"]
    extraction_instructions = body["extraction_instructions"]
    langextract_api_key = body.get("langextract_api_key", "")
    modified_since_raw = body.get("modified_since")

    # Store full instructions + API key as a sidecar so the processor can read them.
    request_id = context.aws_request_id if context else "local"
    combined = {**extraction_instructions, "langextract_api_key": langextract_api_key}
    instructions_key = _store_instructions(request_id, combined)

    # Build SharePoint client from the request payload.
    client = SharePointClient(
        tenant_id=sp["tenant_id"],
        client_id=sp["client_id"],
        client_secret=sp["client_secret"],
        site_url=sp["site_url"],
        document_library=sp["document_library"],
    )

    # Determine the "since" filter.
    library_key = f"{sp['site_url']}|{sp['document_library']}"
    if modified_since_raw:
        modified_since = datetime.fromisoformat(modified_since_raw)
    else:
        modified_since = _get_last_poll_time(library_key)

    poll_start = datetime.now(timezone.utc)
    logger.info("Fetching documents from SharePoint since %s", modified_since or "beginning")

    uploaded = 0
    upload_errors = 0
    for file_meta in client.list_files(modified_since=modified_since):
        try:
            content = client.download_file(file_meta)
            _upload_to_s3(content, file_meta["name"], file_meta, instructions_key)
            uploaded += 1
        except Exception:
            logger.exception("Failed to download/upload %s", file_meta["name"])
            upload_errors += 1

    _set_last_poll_time(library_key, poll_start)
    logger.info("Poll complete – uploaded %d files, %d errors", uploaded, upload_errors)

    return _api_response(200, {
        "files_uploaded": uploaded,
        "errors": upload_errors,
        "instructions_key": instructions_key,
        "message": f"Uploaded {uploaded} file(s) for processing.",
    })
