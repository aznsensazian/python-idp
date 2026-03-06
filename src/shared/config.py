"""Centralized configuration loaded from environment variables and SSM Parameter Store."""

import json
import os

import boto3


def _get_ssm_parameter(name: str, decrypt: bool = True) -> str:
    """Retrieve a parameter from AWS Systems Manager Parameter Store."""
    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"]


def get_sharepoint_config() -> dict:
    """Return SharePoint connection settings from SSM."""
    prefix = os.environ["SSM_PARAMETER_PREFIX"]
    return {
        "tenant_id": _get_ssm_parameter(f"{prefix}/sharepoint/tenant_id"),
        "client_id": _get_ssm_parameter(f"{prefix}/sharepoint/client_id"),
        "client_secret": _get_ssm_parameter(f"{prefix}/sharepoint/client_secret"),
        "site_url": _get_ssm_parameter(f"{prefix}/sharepoint/site_url"),
        "document_library": _get_ssm_parameter(f"{prefix}/sharepoint/document_library"),
    }


def get_extraction_instructions() -> dict:
    """Return the extraction instructions stored in SSM.

    The SSM parameter stores a JSON object with:
      - prompt_description: str  – natural-language extraction rules
      - examples: list[dict]     – few-shot ExampleData dicts
      - model_id: str            – LLM model identifier
    """
    prefix = os.environ["SSM_PARAMETER_PREFIX"]
    raw = _get_ssm_parameter(f"{prefix}/extraction/instructions", decrypt=False)
    return json.loads(raw)


def get_langextract_api_key() -> str:
    """Return the API key used by langextract (e.g. Gemini or OpenAI key)."""
    prefix = os.environ["SSM_PARAMETER_PREFIX"]
    return _get_ssm_parameter(f"{prefix}/extraction/api_key")


# Bucket names come straight from Lambda environment variables set by CloudFormation.
RAW_BUCKET = os.environ.get("RAW_BUCKET", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")
