"""Client for the deepvac hub's cloud licensing control plane.

Implements the desktop half of the browser-based device-code activation
flow (see ../../hub/docs/sequences.md in the sibling `hub` repo): generates
and persists this installation's own Ed25519 keypair, talks to the
licensing-api over plain HTTP, and independently verifies every signed
license certificate it receives using a locally fetched trusted public key
-- it never trusts product/edition/feature fields without a valid signature.

This module intentionally has no dependency on the hub's own Python
package (SQLAlchemy, Postgres, etc. have no place in the desktop app) --
the canonical-serialization and verification rules are duplicated here in
minimal form and must stay in lockstep with
hub/src/licensing/licensing/canonical.py if that format ever changes.
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.error
import urllib.request
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.common import DATA_DIR

PRODUCT_CODE = "deepvac-insight"

# The docker-compose stack in the sibling `hub` repo maps Nginx to host port
# 8080 (see hub/compose.yaml) -- override via env var for any other
# deployment (a real vendor-hosted endpoint, a different local port, etc).
DEFAULT_API_BASE_URL = "http://localhost:8080/api/v1"


def api_base_url() -> str:
    return os.environ.get("DEEPVAC_LICENSING_API_URL", DEFAULT_API_BASE_URL).rstrip("/")


_LICENSE_DIR = DATA_DIR / "license"
_DEVICE_PRIVATE_KEY_PATH = _LICENSE_DIR / "device_private_key.bin"
_LICENSE_PATH = _LICENSE_DIR / "license.json"

_REQUIRED_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "license_id",
        "user_id",
        "organization_id",
        "device_id",
        "device_public_key_hash",
        "product_code",
        "edition_code",
        "features",
        "issued_at",
        "not_before",
        "expires_at",
        "key_id",
        "license_version",
    }
)


class LicensingError(Exception):
    """Base class for all errors raised by this module."""


class ApiError(LicensingError):
    """A non-2xx response from licensing-api, or a network failure."""


class InvalidLicenseError(LicensingError):
    """A license envelope that fails signature, binding, or validity checks."""


# ── canonical serialization + verification (mirrors hub's canonical.py) ───


def _canonicalize(payload: dict) -> bytes:
    payload_keys = frozenset(payload.keys())
    if payload_keys != _REQUIRED_PAYLOAD_KEYS:
        missing = _REQUIRED_PAYLOAD_KEYS - payload_keys
        extra = payload_keys - _REQUIRED_PAYLOAD_KEYS
        raise InvalidLicenseError(
            f"License payload has invalid shape (missing={sorted(missing)}, extra={sorted(extra)})"
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _parse_iso8601(value: str) -> datetime:
    # Server always sends "...Z"; fromisoformat needs "+00:00" before 3.11,
    # and this app supports Python 3.10 (see pyproject.toml).
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def device_public_key_hash(device_public_key_raw: bytes) -> str:
    return urlsafe_b64encode(sha256(device_public_key_raw).digest()).decode("ascii")


def verify_envelope(envelope: dict, trusted_public_keys: dict[str, bytes]) -> dict:
    """Verify signature, key trust, validity window, and device-key binding.

    Returns the payload dict on success; raises InvalidLicenseError otherwise.
    Never trusts any field until the signature over the canonical bytes has
    been checked against a *locally* trusted public key.
    """
    key_id = envelope.get("key_id")
    raw_public_key = trusted_public_keys.get(key_id)
    if raw_public_key is None:
        raise InvalidLicenseError(f"Unknown or untrusted signing key_id: {key_id!r}")

    payload = envelope["payload"]
    canonical_bytes = _canonicalize(payload)
    signature = urlsafe_b64decode(envelope["signature"])
    public_key = Ed25519PublicKey.from_public_bytes(raw_public_key)
    try:
        public_key.verify(signature, canonical_bytes)
    except InvalidSignature as exc:
        raise InvalidLicenseError("License signature verification failed.") from exc

    now = datetime.now(timezone.utc)
    not_before = _parse_iso8601(payload["not_before"])
    expires_at = _parse_iso8601(payload["expires_at"])
    if now < not_before:
        raise InvalidLicenseError("License is not valid yet (not_before is in the future).")
    if now >= expires_at:
        raise InvalidLicenseError("License has expired.")

    local_public_key_raw = load_device_public_key_raw()
    if local_public_key_raw is not None:
        expected_hash = device_public_key_hash(local_public_key_raw)
        if payload["device_public_key_hash"] != expected_hash:
            raise InvalidLicenseError(
                "License is bound to a different device than this installation's keypair."
            )

    return payload


# ── device keypair persistence ─────────────────────────────────────────────


def get_or_create_device_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    """Returns (private_key, raw_public_key_bytes), generating and persisting
    a new keypair on first use. The private key never leaves this machine
    and is never sent to the server.
    """
    _LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    if _DEVICE_PRIVATE_KEY_PATH.exists():
        raw = _DEVICE_PRIVATE_KEY_PATH.read_bytes()
        private_key = Ed25519PrivateKey.from_private_bytes(raw)
    else:
        private_key = Ed25519PrivateKey.generate()
        raw = private_key.private_bytes(
            encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption()
        )
        _DEVICE_PRIVATE_KEY_PATH.write_bytes(raw)
        with contextlib.suppress(NotImplementedError):
            _DEVICE_PRIVATE_KEY_PATH.chmod(0o600)
    public_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    return private_key, public_raw


def load_device_public_key_raw() -> bytes | None:
    if not _DEVICE_PRIVATE_KEY_PATH.exists():
        return None
    raw = _DEVICE_PRIVATE_KEY_PATH.read_bytes()
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    return private_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)


# ── local license cache ─────────────────────────────────────────────────────


def load_license() -> dict | None:
    if not _LICENSE_PATH.exists():
        return None
    try:
        return json.loads(_LICENSE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_license(envelope: dict) -> None:
    _LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    _LICENSE_PATH.write_text(json.dumps(envelope), encoding="utf-8")


def has_valid_local_license() -> bool:
    """True if a cached license exists and verifies against the server's
    currently-trusted public keys. Any failure (no license, network error,
    signature/binding/expiry failure) returns False -- the caller should
    then run the activation flow.
    """
    envelope = load_license()
    if envelope is None:
        return False
    try:
        trusted_keys = fetch_public_keys()
        verify_envelope(envelope, trusted_keys)
    except LicensingError:
        return False
    return True


# ── HTTP calls to licensing-api ─────────────────────────────────────────────


def _request_json(
    method: str, url: str, payload: dict | None = None, timeout: float = 10.0
) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local dev API)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body
        with contextlib.suppress(ValueError):
            detail = json.loads(body).get("detail", body)
        raise ApiError(f"{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"Could not reach licensing service at {url}: {exc.reason}") from exc


def fetch_public_keys() -> dict[str, bytes]:
    response = _request_json("GET", f"{api_base_url()}/licensing/public-keys")
    return {key["key_id"]: urlsafe_b64decode(key["public_key"]) for key in response.get("keys", [])}


@dataclass(frozen=True)
class ActivationStart:
    activation_id: str
    user_code: str
    verification_url: str
    expires_at: str
    polling_interval_seconds: int


def start_activation(
    product_code: str = PRODUCT_CODE, edition_code: str | None = None
) -> ActivationStart:
    payload: dict = {"product_code": product_code}
    if edition_code:
        payload["edition_code"] = edition_code
    response = _request_json("POST", f"{api_base_url()}/activations", payload)
    return ActivationStart(
        activation_id=response["activation_id"],
        user_code=response["user_code"],
        verification_url=response["verification_url"],
        expires_at=response["expires_at"],
        polling_interval_seconds=response["polling_interval_seconds"],
    )


def poll_activation_status(activation_id: str) -> str:
    response = _request_json("GET", f"{api_base_url()}/activations/{activation_id}")
    return response["status"]


def complete_activation(activation_id: str, display_name: str | None = None) -> dict:
    """Submits this installation's device public key and, on success,
    verifies and persists the returned license before returning its payload.
    """
    _, public_raw = get_or_create_device_keypair()
    payload = {"device_public_key": urlsafe_b64encode(public_raw).decode("ascii")}
    if display_name:
        payload["display_name"] = display_name
    envelope = _request_json(
        "POST", f"{api_base_url()}/activations/{activation_id}/complete", payload
    )
    trusted_keys = fetch_public_keys()
    license_payload = verify_envelope(envelope, trusted_keys)
    save_license(envelope)
    return license_payload
