"""Centralized configuration loaded from environment variables and SSM Parameter Store.

SSM-based config is used as a fallback when extraction instructions are not
provided at runtime through the API request payload.
"""

import json
import os

import boto3


def _get_ssm_parameter(name: str, decrypt: bool = True) -> str:
    """Retrieve a parameter from AWS Systems Manager Parameter Store."""
    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"]


def get_extraction_instructions() -> dict:
    """Return the extraction instructions stored in SSM (fallback).

    The SSM parameter stores a JSON object with:
      - prompt_description: str  – natural-language extraction rules
      - examples: list[dict]     – few-shot ExampleData dicts
      - model_id: str            – LLM model identifier
    """
    prefix = os.environ.get("SSM_PARAMETER_PREFIX", "")
    if not prefix:
        return {}
    raw = _get_ssm_parameter(f"{prefix}/extraction/instructions", decrypt=False)
    return json.loads(raw)


def get_langextract_api_key() -> str:
    """Return the API key used by langextract (fallback from SSM)."""
    prefix = os.environ.get("SSM_PARAMETER_PREFIX", "")
    if not prefix:
        return ""
    return _get_ssm_parameter(f"{prefix}/extraction/api_key")


# Bucket / table names from Lambda environment variables set by CloudFormation.
RAW_BUCKET = os.environ.get("RAW_BUCKET", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")
