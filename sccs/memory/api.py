# SCCS Memory API
# Optional Anthropic Files API layer for cloud sync

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.memory.item import MemoryItem


def _get_anthropic_client():
    """
    Get an authenticated Anthropic client.

    Raises:
        RuntimeError: If anthropic package is not installed or API key is missing.
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic package not installed. "
            "Install with: uv pip install -e '.[memory]'"
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Export it before using --api flag."
        )

    return anthropic.Anthropic(api_key=api_key)


class AnthropicMemorySync:
    """
    Optional Anthropic Files API layer.

    Only activated via explicit --api flag. Never runs automatically.
    Requires: uv pip install -e '.[memory]' and ANTHROPIC_API_KEY env var.
    """

    def __init__(self):
        self._client = _get_anthropic_client()

    def upload_memory_export(self, content: str, filename: str = "memory_export.txt") -> str:
        """
        Upload memory content to Anthropic Files API.

        Args:
            content: Text content to upload.
            filename: Filename for the uploaded file.

        Returns:
            file_id of the uploaded file.
        """
        import io

        file_bytes = content.encode("utf-8")
        response = self._client.beta.files.upload(
            file=(filename, io.BytesIO(file_bytes), "text/plain"),
        )
        return response.id

    def list_uploaded_files(self) -> list[dict]:
        """List all files uploaded to Anthropic Files API."""
        response = self._client.beta.files.list()
        return [
            {
                "id": f.id,
                "filename": getattr(f, "filename", ""),
                "created_at": getattr(f, "created_at", None),
            }
            for f in response.data
        ]

    def download_file(self, file_id: str) -> str:
        """Download file content from Anthropic Files API."""
        response = self._client.beta.files.retrieve_content(file_id)
        if isinstance(response, bytes):
            return response.decode("utf-8")
        return str(response)

    def sync_to_api(self, items: list[MemoryItem]) -> dict:
        """
        Upload memory export to Anthropic Files API.

        Args:
            items: List of memory items to upload.

        Returns:
            Dict with 'uploaded' (list of file_ids) and 'failed' (list of errors).
        """
        from sccs.memory.bridge import ClaudeAiBridge

        uploaded = []
        failed = []

        export_content = ClaudeAiBridge.export_to_context_block(items)
        try:
            file_id = self.upload_memory_export(export_content)
            uploaded.append(file_id)
        except Exception as e:
            failed.append(str(e))

        return {"uploaded": uploaded, "failed": failed}
