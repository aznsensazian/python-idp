"""Lightweight Microsoft Graph client for SharePoint document library access."""

import logging
from datetime import datetime, timezone
from typing import Generator

import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

# File extensions we support for extraction.
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".docx", ".doc"}


class SharePointClient:
    """Authenticate via client-credentials and list / download files."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 site_url: str, document_library: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.site_url = site_url
        self.document_library = document_library
        self._token: str | None = None
        self._site_id: str | None = None
        self._drive_id: str | None = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        url = TOKEN_URL.format(tenant_id=self.tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _resolve_site_id(self) -> str:
        if self._site_id:
            return self._site_id
        # site_url expected as "contoso.sharepoint.com:/sites/MySite"
        url = f"{GRAPH_BASE}/sites/{self.site_url}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        self._site_id = resp.json()["id"]
        return self._site_id

    def _resolve_drive_id(self) -> str:
        if self._drive_id:
            return self._drive_id
        site_id = self._resolve_site_id()
        url = f"{GRAPH_BASE}/sites/{site_id}/drives"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        for drive in resp.json().get("value", []):
            if drive["name"].lower() == self.document_library.lower():
                self._drive_id = drive["id"]
                return self._drive_id
        raise ValueError(f"Document library '{self.document_library}' not found")

    def list_files(self, modified_since: datetime | None = None) -> Generator[dict, None, None]:
        """Yield metadata dicts for supported files, optionally filtered by last-modified time."""
        drive_id = self._resolve_drive_id()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                if "file" not in item:
                    continue
                name: str = item["name"]
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                last_modified = datetime.fromisoformat(
                    item["lastModifiedDateTime"].replace("Z", "+00:00")
                )
                if modified_since and last_modified <= modified_since:
                    continue
                yield {
                    "id": item["id"],
                    "name": name,
                    "size": item.get("size", 0),
                    "last_modified": last_modified.isoformat(),
                    "download_url": item.get("@microsoft.graph.downloadUrl", ""),
                }
            url = data.get("@odata.nextLink")

    def download_file(self, file_meta: dict) -> bytes:
        """Download file content given metadata from list_files."""
        download_url = file_meta.get("download_url")
        if not download_url:
            drive_id = self._resolve_drive_id()
            url = f"{GRAPH_BASE}/drives/{drive_id}/items/{file_meta['id']}/content"
            resp = requests.get(url, headers=self._headers(), timeout=120)
        else:
            resp = requests.get(download_url, timeout=120)
        resp.raise_for_status()
        return resp.content
