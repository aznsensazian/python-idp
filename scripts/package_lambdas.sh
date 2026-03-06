#!/usr/bin/env bash
#
# Package the two Lambda functions into deployment zips.
#
# Usage:
#   ./scripts/package_lambdas.sh            # creates dist/*.zip
#   ./scripts/package_lambdas.sh <s3-bucket> # also uploads to S3
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
S3_BUCKET="${1:-}"

rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

echo "==> Installing dependencies into a temporary layer..."
LAYER_DIR=$(mktemp -d)
pip install -r "${ROOT_DIR}/requirements.txt" -t "${LAYER_DIR}" --quiet

# --- Helper: build a zip for one Lambda -----------------------------------
package_lambda() {
    local name="$1"
    local zip_path="${DIST_DIR}/${name}.zip"

    echo "==> Packaging ${name}..."
    # Start with shared dependencies
    (cd "${LAYER_DIR}" && zip -r9 "${zip_path}" . -x '*.pyc' '__pycache__/*' > /dev/null)

    # Add shared module
    (cd "${ROOT_DIR}/src" && zip -r9 "${zip_path}" shared/ -x '*.pyc' '__pycache__/*' > /dev/null)

    # Add the Lambda-specific module
    (cd "${ROOT_DIR}/src" && zip -r9 "${zip_path}" "${name}/" -x '*.pyc' '__pycache__/*' > /dev/null)

    echo "    -> ${zip_path}"
}

package_lambda "sharepoint_poller"
package_lambda "document_processor"

rm -rf "${LAYER_DIR}"

# --- Optional S3 upload ----------------------------------------------------
if [[ -n "${S3_BUCKET}" ]]; then
    echo "==> Uploading zips to s3://${S3_BUCKET}/lambda/ ..."
    aws s3 cp "${DIST_DIR}/sharepoint_poller.zip"  "s3://${S3_BUCKET}/lambda/sharepoint_poller.zip"
    aws s3 cp "${DIST_DIR}/document_processor.zip" "s3://${S3_BUCKET}/lambda/document_processor.zip"
    echo "==> Upload complete."
fi

echo "==> Done."
