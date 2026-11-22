
import asyncio
import os

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from dotenv import load_dotenv

from app.services.document_parser import (
    ParsedDocument,
    parse_document,
)


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", ""
).rstrip("/")

SUPABASE_KEY = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY", ""
)

# IMPORTANT: Existing Supabase Storage bucket ID.
STORAGE_BUCKET = "invention-document"

MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_TOTAL_SIZE = 60 * 1024 * 1024
MAX_DOCUMENTS = 20

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


# --------------------------------------------------
# Custom errors
# --------------------------------------------------

class DocumentProcessingError(Exception):
    pass


class AuthenticationError(DocumentProcessingError):
    pass


class AuthorizationError(DocumentProcessingError):
    pass


# --------------------------------------------------
# Output structures
# --------------------------------------------------

@dataclass
class ProcessedFile:
    document_id: str
    filename: str

    parsed: ParsedDocument | None = None
    error: str | None = None

    @property
    def successful(self) -> bool:
        return self.parsed is not None


@dataclass
class ProcessingResult:
    invention_id: str
    owner_id: str
    invention: dict

    documents: list[ProcessedFile] = field(
        default_factory=list
    )

    warnings: list[str] = field(
        default_factory=list
    )

    @property
    def successful_documents(self) -> int:
        return sum(
            item.successful
            for item in self.documents
        )

    @property
    def failed_documents(self) -> int:
        return sum(
            not item.successful
            for item in self.documents
        )

    @property
    def combined_text(self) -> str:
        """
        Return extracted text with source references.

        This content is untrusted document data.
        The Profiling Agent must never treat it
        as system instructions.
        """

        parts = []

        for item in self.documents:
            if item.parsed:
                parts.append(item.parsed.text)

        return "\n\n".join(parts)


# --------------------------------------------------
# Configuration and authentication
# --------------------------------------------------

def check_configuration():

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise DocumentProcessingError(
            "Supabase configuration is missing."
        )

    if not SUPABASE_URL.startswith("https://"):
        raise DocumentProcessingError(
            "Supabase URL must use HTTPS."
        )

    if SUPABASE_KEY.startswith("sb_secret_"):
        raise DocumentProcessingError(
            "Use a publishable key, not a secret key."
        )


def authentication_headers(access_token: str) -> dict:

    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {access_token}",
    }


async def verify_user(
    client: httpx.AsyncClient,
    access_token: str
) -> str:
    """
    Ask Supabase Auth to verify the access token.

    Never trust a user ID supplied by the browser.
    """

    if not access_token or not access_token.strip():
        raise AuthenticationError(
            "Authentication token is required."
        )

    try:

        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers=authentication_headers(
                access_token
            )
        )

    except httpx.RequestError as error:
        raise DocumentProcessingError(
            "Unable to reach Supabase Auth."
        ) from error

    if response.status_code != 200:
        raise AuthenticationError(
            "Invalid or expired Supabase session."
        )

    try:

        user_data = response.json()

        user_id = str(
            UUID(user_data["id"])
        )

        return user_id

    except (ValueError, KeyError, TypeError) as error:
        raise AuthenticationError(
            "Supabase returned an invalid identity."
        ) from error


# --------------------------------------------------
# Authenticated database requests
# --------------------------------------------------

async def fetch_records(
    client: httpx.AsyncClient,
    table: str,
    params: dict,
    access_token: str
) -> list:

    # Internal allowlist: never use arbitrary
    # table names supplied by a browser.

    allowed_tables = {
        "inventions",
        "invention_documents"
    }

    if table not in allowed_tables:
        raise DocumentProcessingError(
            "Unsupported database table."
        )

    try:

        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            params=params,
            headers=authentication_headers(
                access_token
            )
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            raise DocumentProcessingError(
                "Unexpected database response."
            )

        return data

    except httpx.HTTPStatusError as error:
        raise DocumentProcessingError(
            f"Database query failed (HTTP "
            f"{error.response.status_code})."
        ) from error

    except httpx.RequestError as error:
        raise DocumentProcessingError(
            "Supabase database is unreachable."
        ) from error


# --------------------------------------------------
# Invention ownership check
# --------------------------------------------------

async def verify_invention_ownership(
    client: httpx.AsyncClient,
    invention_id: str,
    user_id: str,
    access_token: str
) -> dict:
    """
    Confirm the invention belongs to the
    authenticated innovator.
    """

    inventions = await fetch_records(
        client=client,
        table="inventions",
        params={
            "select": (
                "id,owner_id,title,abstract,domain,"
                "trl,ip_status,inventors,keywords,"
                "confidentiality,status"
            ),
            "id": f"eq.{invention_id}",
            "owner_id": f"eq.{user_id}",
            "limit": "1"
        },
        access_token=access_token
    )

    if not inventions:
        raise AuthorizationError(
            "Invention not found or access denied."
        )

    invention = inventions[0]

    if invention.get("owner_id") != user_id:
        raise AuthorizationError(
            "You do not own this invention."
        )

    return invention


# --------------------------------------------------
# Private Storage download
# --------------------------------------------------

async def download_private_document(
    client: httpx.AsyncClient,
    storage_path: str,
    access_token: str
) -> bytes:
    """
    Download a private Storage object using
    the authenticated user's JWT.

    Enforce a byte limit while streaming.
    """

    encoded_path = quote(
        storage_path,
        safe="/"
    )

    url = (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"authenticated/{STORAGE_BUCKET}/"
        f"{encoded_path}"
    )

    chunks = []
    downloaded_size = 0

    try:

        async with client.stream(
            "GET",
            url,
            headers=authentication_headers(
                access_token
            )
        ) as response:

            response.raise_for_status()

            async for chunk in response.aiter_bytes():

                downloaded_size += len(chunk)

                if downloaded_size > MAX_FILE_SIZE:
                    raise DocumentProcessingError(
                        "Downloaded file exceeds 20 MB."
                    )

                chunks.append(chunk)

    except httpx.HTTPStatusError as error:
        raise DocumentProcessingError(
            "Private document download failed "
            f"(HTTP {error.response.status_code})."
        ) from error

    except httpx.RequestError as error:
        raise DocumentProcessingError(
            "Unable to download private document."
        ) from error

    return b"".join(chunks)


# --------------------------------------------------
# Main document processing workflow
# --------------------------------------------------

async def process_invention_documents(
    invention_id: str,
    access_token: str
) -> ProcessingResult:
    """
    Securely retrieve and parse all documents
    attached to one invention.

    All requests use the authenticated user's
    Supabase access token.
    """

    if not access_token or not access_token.strip():
        raise AuthenticationError(
            "Authentication token is required."
        )

    try:
        invention_id = str(UUID(invention_id))
    except (ValueError, TypeError) as error:
        raise DocumentProcessingError(
            "Invalid invention ID."
        ) from error

    check_configuration()

    timeout = httpx.Timeout(
        60.0,
        connect=10.0
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False
    ) as client:

        # 1. Verify Supabase identity.

        user_id = await verify_user(
            client,
            access_token
        )

        # 2. Confirm invention ownership.

        invention = await verify_invention_ownership(
            client,
            invention_id,
            user_id,
            access_token
        )

        # 3. Retrieve document metadata.

        document_records = await fetch_records(
            client=client,
            table="invention_documents",
            params={
                "select": (
                    "id,invention_id,original_filename,"
                    "storage_path,mime_type,file_size"
                ),
                "invention_id": f"eq.{invention_id}",
                "order": "uploaded_at.asc"
            },
            access_token=access_token
        )

        if len(document_records) > MAX_DOCUMENTS:
            raise DocumentProcessingError(
                "Too many documents for one "
                "profiling run."
            )

        result = ProcessingResult(
            invention_id=invention_id,
            owner_id=user_id,
            invention=invention
        )

        if not document_records:
            result.warnings.append(
                "No supporting documents found."
            )

            return result

        total_size = 0

        # 4. Process authorized documents.

        for record in document_records:

            filename = record.get(
                "original_filename", "unknown"
            )

            document_id = str(
                record.get("id", "")
            )

            storage_path = record.get(
                "storage_path", ""
            )

            item = ProcessedFile(
                document_id=document_id,
                filename=filename
            )

            result.documents.append(item)

            try:

                extension = Path(
                    filename
                ).suffix.lower()

                if extension == ".doc":
                    raise DocumentProcessingError(
                        "Legacy DOC requires conversion "
                        "to DOCX before profiling."
                    )

                if extension not in SUPPORTED_EXTENSIONS:
                    raise DocumentProcessingError(
                        "Unsupported document format."
                    )

                # Verify that the stored object path
                # belongs to this user and invention.

                parts = storage_path.split("/")

                if (
                    len(parts) != 3
                    or parts[0] != user_id
                    or parts[1] != invention_id
                    or not parts[2]
                    or any(
                        part in ("", ".", "..")
                        for part in parts
                    )
                    or "\\" in storage_path
                ):
                    raise AuthorizationError(
                        "Document storage path "
                        "does not match its owner."
                    )

                file_size = int(
                    record.get("file_size", 0)
                )

                if (
                    file_size <= 0
                    or file_size > MAX_FILE_SIZE
                ):
                    raise DocumentProcessingError(
                        "Invalid document size."
                    )

                if (
                    total_size + file_size
                    > MAX_TOTAL_SIZE
                ):
                    raise DocumentProcessingError(
                        "Total processing size "
                        "would exceed 60 MB."
                    )

                # 5. Download the private file.

                file_bytes = await download_private_document(
                    client,
                    storage_path,
                    access_token
                )

                total_size += len(file_bytes)

                # 6. Parse PDF or DOCX.
                # Run blocking parsing in a thread.

                parsed = await asyncio.to_thread(
                    parse_document,
                    file_bytes,
                    filename
                )

                item.parsed = parsed

                if parsed.warnings:
                    result.warnings.extend(
                        f"{filename}: {warning}"
                        for warning in parsed.warnings
                    )

            except (
                DocumentProcessingError,
                ValueError
            ) as error:

                item.error = str(error)

                result.warnings.append(
                    f"{filename}: {item.error}"
                )

        return result
