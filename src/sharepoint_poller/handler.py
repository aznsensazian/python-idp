"""Lambda handler – polls SharePoint for new/modified documents and uploads them to S3.

Triggered on a schedule by EventBridge.  Tracks the last-polled timestamp in
DynamoDB so only new or modified files are downloaded on each invocation.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from shared.config import get_sharepoint_config, RAW_BUCKET, TRACKING_TABLE
from shared.sharepoint_client import SharePointClient

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def _get_last_poll_time() -> datetime | None:
    """Read the last successful poll timestamp from DynamoDB."""
    table = dynamodb.Table(TRACKING_TABLE)
    resp = table.get_item(Key={"pk": "POLL_STATE", "sk": "last_poll"})
    item = resp.get("Item")
    if item and "timestamp" in item:
        return datetime.fromisoformat(item["timestamp"])
    return None


def _set_last_poll_time(ts: datetime) -> None:
    table = dynamodb.Table(TRACKING_TABLE)
    table.put_item(Item={
        "pk": "POLL_STATE",
        "sk": "last_poll",
        "timestamp": ts.isoformat(),
    })


def _upload_to_s3(file_bytes: bytes, file_name: str, metadata: dict) -> str:
    """Upload raw document bytes to the raw S3 bucket and return the S3 key."""
    key = f"raw/{file_name}"
    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=key,
        Body=file_bytes,
        Metadata={
            "sharepoint_id": metadata.get("id", ""),
            "last_modified": metadata.get("last_modified", ""),
            "original_name": file_name,
        },
    )
    logger.info("Uploaded %s to s3://%s/%s", file_name, RAW_BUCKET, key)
    return key


def handler(event, context):
    """Entry point for the SharePoint poller Lambda."""
    poll_start = datetime.now(timezone.utc)
    sp_config = get_sharepoint_config()

    client = SharePointClient(
        tenant_id=sp_config["tenant_id"],
        client_id=sp_config["client_id"],
        client_secret=sp_config["client_secret"],
        site_url=sp_config["site_url"],
        document_library=sp_config["document_library"],
    )

    last_poll = _get_last_poll_time()
    logger.info("Polling SharePoint since %s", last_poll or "beginning")

    uploaded = 0
    for file_meta in client.list_files(modified_since=last_poll):
        try:
            content = client.download_file(file_meta)
            _upload_to_s3(content, file_meta["name"], file_meta)
            uploaded += 1
        except Exception:
            logger.exception("Failed to download/upload %s", file_meta["name"])

    _set_last_poll_time(poll_start)
    logger.info("Poll complete – uploaded %d files", uploaded)

    return {"statusCode": 200, "body": json.dumps({"files_uploaded": uploaded})}
