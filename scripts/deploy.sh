#!/usr/bin/env bash
#
# Deploy the CloudFormation stack.
#
# Usage:
#   ./scripts/deploy.sh <stack-name> <s3-code-bucket> [params-file]
#
# The optional params-file is a JSON array of ParameterKey/ParameterValue
# objects.  At minimum you must supply LambdaCodeBucket.
#
# Example params-file:
#
#   [
#     {"ParameterKey": "LambdaCodeBucket",       "ParameterValue": "my-code-bucket"},
#     {"ParameterKey": "LangExtractApiKey",       "ParameterValue": "AIza..."},
#     {"ParameterKey": "ExtractionInstructions",  "ParameterValue": "{}"}
#   ]
#
set -euo pipefail

STACK_NAME="${1:?Usage: deploy.sh <stack-name> <s3-code-bucket> [params-file]}"
CODE_BUCKET="${2:?Provide the S3 bucket that contains Lambda zips}"
PARAMS_FILE="${3:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Packaging Lambda functions..."
"${ROOT_DIR}/scripts/package_lambdas.sh" "${CODE_BUCKET}"

PARAM_OVERRIDES=""
if [[ -n "${PARAMS_FILE}" && -f "${PARAMS_FILE}" ]]; then
    PARAM_OVERRIDES="--parameter-overrides $(cat "${PARAMS_FILE}")"
fi

echo "==> Deploying CloudFormation stack: ${STACK_NAME}..."
aws cloudformation deploy \
    --template-file "${ROOT_DIR}/cloudformation.yaml" \
    --stack-name "${STACK_NAME}" \
    ${PARAM_OVERRIDES} \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset

echo "==> Stack outputs:"
aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs" \
    --output table

echo "==> Deployment complete."
