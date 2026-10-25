"""The node's HTTPS client of the master's artifact routes (cluster/master/api/artifact_routes.py).

Like every other call to the master it verifies the server against the pinned CA, sends
the node credential as a bearer header and bypasses proxies from the environment
(daemon/pairing/ca_pinning.open_url). Both directions are gzip on the wire: downloads ask
for the stored gzip bytes, uploads send a compressed body.

Errors are ArtifactTransferError with `retryable`, which the job runner hands on to the
master: a lost connection, a timeout or a 5xx answer is retried here a few times with
backoff and is retryable for the job after that; content that does not match its hash,
an artifact the master does not have, or an upload over the size limit is not.
"""

import gzip
import hashlib
import http.client
import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Callable, Optional, Union

from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import open_url
from scenegems_tool.cluster.protocol.artifacts import JSON_MEDIA_TYPE, ArtifactKind, ArtifactRef
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, AUTHORIZATION_HEADER, bearer

logger = logging.getLogger(__name__)

TIMEOUT_S = 60.0
ATTEMPTS = 4
BACKOFF_S = 0.5  # doubles per attempt: 0.5, 1 and 2 s between four attempts
COMPRESS_LEVEL = 6
READ_CHUNK_BYTES = 1024 * 1024
RETRIED_STATUSES = {408, 429, 500, 502, 503, 504}


class ArtifactTransferError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, status: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class ArtifactHashMismatch(ArtifactTransferError):
    """Downloaded content that does not hash to its address: corrupt at the source, so not retryable."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ArtifactClient:
    def __init__(
        self,
        master_url: str,
        credential: str,
        context: Union[ssl.SSLContext, Callable[[], ssl.SSLContext]],  # or how to make it, on first use
        *,
        timeout_s: float = TIMEOUT_S,
        attempts: int = ATTEMPTS,
        backoff_s: float = BACKOFF_S,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.master_url = master_url.rstrip("/")
        self._credential = credential
        self._context_source = context
        self._context: Optional[ssl.SSLContext] = context if isinstance(context, ssl.SSLContext) else None
        self._timeout_s = timeout_s
        self._attempts = max(1, attempts)
        self._backoff_s = backoff_s
        self._sleep = sleep

    def context(self) -> ssl.SSLContext:
        if self._context is None:
            self._context = self._context_source()
        return self._context

    def url(self, sha256: str, **query: Optional[str]) -> str:
        parameters = urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})
        return f"{self.master_url}{ARTIFACTS_PATH}/{sha256}" + (f"?{parameters}" if parameters else "")

    # Download

    def download(self, sha256: str, max_bytes: Optional[int] = None) -> bytes:
        """The artifact's content after its hash check; at most max_bytes uncompressed when given."""
        return self._with_retries(f"download artifact {sha256}", lambda: self._download_once(sha256, max_bytes))

    def _download_once(self, sha256: str, max_bytes: Optional[int]) -> bytes:
        request = urllib.request.Request(self.url(sha256), method="GET", headers={AUTHORIZATION_HEADER: bearer(self._credential), "Accept-Encoding": "gzip"})
        digest = hashlib.sha256()
        content = bytearray()
        with open_url(request, self.context(), self._timeout_s) as response:
            encoding = (response.headers.get("Content-Encoding") or "identity").strip().lower()
            decompressor = zlib.decompressobj(wbits=31) if encoding == "gzip" else None
            while True:
                chunk = response.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                piece = decompressor.decompress(chunk) if decompressor is not None else chunk
                content += piece
                digest.update(piece)
                if max_bytes is not None and len(content) > max_bytes:
                    raise ArtifactHashMismatch(f"artifact {sha256} is larger than the {max_bytes} bytes its reference names")
            if decompressor is not None:
                if not decompressor.eof:
                    raise http.client.IncompleteRead(bytes(content))
                tail = decompressor.flush()
                content += tail
                digest.update(tail)
        actual = digest.hexdigest()
        if actual != sha256:
            raise ArtifactHashMismatch(f"artifact {sha256} downloaded from the master hashes to {actual}")
        return bytes(content)

    # Upload

    def upload(self, data: bytes, kind: ArtifactKind, media_type: str = JSON_MEDIA_TYPE, *, job_id: Optional[str] = None, field: Optional[str] = None) -> ArtifactRef:
        """Stores the content on the master and returns its reference; with job_id the job holds it as its result field."""
        sha256 = hashlib.sha256(data).hexdigest()
        body = gzip.compress(data, compresslevel=COMPRESS_LEVEL, mtime=0)
        url = self.url(sha256, kind=kind.value, job_id=job_id, field=field)
        headers = {AUTHORIZATION_HEADER: bearer(self._credential), "Content-Type": media_type, "Content-Encoding": "gzip", "Content-Length": str(len(body))}

        def upload_once() -> dict:
            request = urllib.request.Request(url, data=body, method="PUT", headers=headers)
            with open_url(request, self.context(), self._timeout_s) as response:
                return json.loads(response.read())

        answer = self._with_retries(f"upload artifact {sha256}", upload_once)
        if answer.get("sha256") != sha256 or answer.get("size_bytes") != len(data):
            raise ArtifactTransferError(f"the master stored artifact {sha256} as {answer.get('sha256')} with {answer.get('size_bytes')} bytes", retryable=True)
        return ArtifactRef(sha256=sha256, size_bytes=len(data), kind=kind, media_type=answer.get("media_type", media_type))

    # Retries

    def _with_retries(self, what: str, operation):
        for attempt in range(1, self._attempts + 1):
            try:
                return operation()
            except ArtifactTransferError:
                raise
            except urllib.error.HTTPError as error:
                detail = _error_detail(error)
                if error.code not in RETRIED_STATUSES:
                    raise ArtifactTransferError(f"Cannot {what}: the master answered HTTP {error.code}{detail}", retryable=error.code not in (404, 413), status=error.code) from error
                failure = ArtifactTransferError(f"Cannot {what}: the master answered HTTP {error.code}{detail}", retryable=True, status=error.code)
            except urllib.error.URLError as error:
                if isinstance(error.reason, ssl.SSLCertVerificationError):
                    raise ArtifactTransferError(f"Cannot {what}: the master's certificate does not verify: {error.reason}", retryable=True) from error
                failure = ArtifactTransferError(f"Cannot {what}: {error.reason}", retryable=True)
            except (OSError, http.client.HTTPException, zlib.error, ValueError) as error:
                failure = ArtifactTransferError(f"Cannot {what}: {type(error).__name__}: {error}", retryable=True)
            if attempt < self._attempts:
                delay = self._backoff_s * 2 ** (attempt - 1)
                logger.warning("%s (attempt %d of %d); retrying in %.1f s", failure, attempt, self._attempts, delay)
                self._sleep(delay)
        raise failure


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    try:
        body = str(json.loads(body).get("detail", body))
    except (ValueError, AttributeError):
        pass
    return f": {body[:300]}" if body else ""
