"""Lambda handler – processes raw documents from S3 using langextract.

Triggered by S3 event notifications when new objects land in the raw/ prefix
of the raw bucket.  Extracts structured JSON according to the extraction
instructions stored in SSM Parameter Store, then writes the result to the
output S3 bucket.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

import boto3
import langextract as lx

from shared.config import (
    get_extraction_instructions,
    get_langextract_api_key,
    OUTPUT_BUCKET,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")

# Document types that need to be read as binary/image vs text extraction.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc"}


def _download_from_s3(bucket: str, key: str, tmp_dir: str) -> str:
    """Download an S3 object to a local temp file and return the path."""
    file_name = os.path.basename(key)
    local_path = os.path.join(tmp_dir, file_name)
    s3.download_file(bucket, key, local_path)
    return local_path


def _build_examples(raw_examples: list[dict]) -> list:
    """Convert plain dicts from SSM config into langextract ExampleData objects."""
    examples = []
    for ex in raw_examples:
        extractions = [
            lx.data.Extraction(
                extraction_class=e["extraction_class"],
                extraction_text=e["extraction_text"],
                attributes=e.get("attributes", {}),
            )
            for e in ex.get("extractions", [])
        ]
        examples.append(
            lx.data.ExampleData(text=ex["text"], extractions=extractions)
        )
    return examples


def _read_document_text(local_path: str) -> str:
    """Read text content from a document file.

    For PDFs and Word documents, we read the raw bytes and pass
    the file path to langextract which handles parsing internally.
    For images, langextract also accepts file paths directly.
    """
    return local_path


def _extract(local_path: str, instructions: dict, api_key: str) -> dict:
    """Run langextract on a single document and return structured results."""
    examples = _build_examples(instructions.get("examples", []))
    model_id = instructions.get("model_id", "gemini-2.5-flash")
    prompt_description = instructions["prompt_description"]

    result = lx.extract(
        text_or_documents=local_path,
        prompt_description=prompt_description,
        examples=examples,
        model_id=model_id,
        api_key=api_key,
    )

    # Convert result to a serialisable dict.
    extractions = []
    if hasattr(result, "extractions"):
        for ext in result.extractions:
            extractions.append({
                "extraction_class": ext.extraction_class,
                "extraction_text": ext.extraction_text,
                "attributes": ext.attributes if hasattr(ext, "attributes") else {},
            })
    elif isinstance(result, list):
        for ext in result:
            extractions.append({
                "extraction_class": getattr(ext, "extraction_class", ""),
                "extraction_text": getattr(ext, "extraction_text", ""),
                "attributes": getattr(ext, "attributes", {}),
            })

    return {"extractions": extractions}


def _upload_result(result: dict, original_key: str) -> str:
    """Write the structured JSON to the output bucket."""
    # Turn  raw/invoice.pdf  ->  processed/invoice.json
    base_name = Path(original_key).stem
    output_key = f"processed/{base_name}.json"

    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=output_key,
        Body=json.dumps(result, indent=2, default=str),
        ContentType="application/json",
    )
    logger.info("Result written to s3://%s/%s", OUTPUT_BUCKET, output_key)
    return output_key


def handler(event, context):
    """Entry point for the document-processor Lambda."""
    instructions = get_extraction_instructions()
    api_key = get_langextract_api_key()

    processed = 0
    errors = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        logger.info("Processing s3://%s/%s", bucket, key)

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                local_path = _download_from_s3(bucket, key, tmp_dir)
                result = _extract(local_path, instructions, api_key)
                result["source_file"] = key
                _upload_result(result, key)
                processed += 1
            except Exception:
                logger.exception("Failed to process %s", key)
                errors += 1

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": processed, "errors": errors}),
    }
