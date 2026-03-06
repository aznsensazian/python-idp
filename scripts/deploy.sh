#!/usr/bin/env bash
#
# Deploy the CloudFormation stack.
#
# Usage:
#   ./scripts/deploy.sh <stack-name> <s3-code-bucket> <params-file>
#
# The params-file is a JSON array of ParameterKey/ParameterValue objects,
# for example:
#
#   [
#     {"ParameterKey": "SharePointTenantId",       "ParameterValue": "..."},
#     {"ParameterKey": "SharePointClientId",       "ParameterValue": "..."},
#     {"ParameterKey": "SharePointClientSecret",   "ParameterValue": "..."},
#     {"ParameterKey": "SharePointSiteUrl",        "ParameterValue": "contoso.sharepoint.com:/sites/MySite"},
#     {"ParameterKey": "SharePointDocumentLibrary","ParameterValue": "Documents"},
#     {"ParameterKey": "LangExtractApiKey",        "ParameterValue": "..."},
#     {"ParameterKey": "LambdaCodeBucket",         "ParameterValue": "my-code-bucket"},
#     {"ParameterKey": "ExtractionInstructions",   "ParameterValue": "{\"prompt_description\":\"...\",\"examples\":[],\"model_id\":\"gemini-2.5-flash\"}"}
#   ]
#
set -euo pipefail

STACK_NAME="${1:?Usage: deploy.sh <stack-name> <s3-code-bucket> <params-file>}"
CODE_BUCKET="${2:?Provide the S3 bucket that contains Lambda zips}"
PARAMS_FILE="${3:?Provide path to parameters JSON file}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Packaging Lambda functions..."
"${ROOT_DIR}/scripts/package_lambdas.sh" "${CODE_BUCKET}"

echo "==> Deploying CloudFormation stack: ${STACK_NAME}..."
aws cloudformation deploy \
    --template-file "${ROOT_DIR}/cloudformation.yaml" \
    --stack-name "${STACK_NAME}" \
    --parameter-overrides "$(cat "${PARAMS_FILE}")" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset

echo "==> Stack outputs:"
aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs" \
    --output table

echo "==> Deployment complete."
