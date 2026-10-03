"""Enterprise-grade data security, encryption, and cryptographic provenance.

This module provides:
1. DataVault: AES-256 (Fernet) encryption for local PII at rest.
2. ProvenanceSigner: Ed25519 cryptographic signatures for research data.
3. CodebaseHasher: Integrity verification for academic datasets.
4. Research salt storage: read/provision the private research salt (item 10,
   V1). The salt lives here — beside the key it complements — never in the
   domain; both secrets are created atomically and owner-only (V7).
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, cast

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


def _chmod_owner_only(path: Path) -> None:
    """Restrict *path* to its owner (0600) where the OS supports POSIX
    permissions. A private key written with a shared machine's default
    umask is readable by every account on it (measured 0o644 under umask
    022), and the worst-case user runs AA on shared and library computers.
    No-op on Windows, where the file inherits the directory ACLs — the
    best a portable app can do without pywin32. Failures are logged,
    never raised: a permission hiccup must not stop data being written.
    """
    if os.name != "posix":
        return
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("could not set owner-only permissions on %s: %s", path, exc)


def read_public_key_fingerprint(key_path: Path) -> str | None:
    """The research public key's fingerprint: SHA-256 of the raw public key
    bytes, hex. This is what a contributor publishes; a bundle recipient
    recomputes it from the public key in verification.json /
    bundle_signature.json and compares.

    READ-ONLY: never generates a key. Returns None when the key is absent
    or unreadable — a consent screen that merely asks must not mint one.
    """
    try:
        if not key_path.exists():
            return None
        with open(key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(), password=None
            )
        raw_public = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(raw_public).hexdigest()
    except Exception as exc:  # noqa: BLE001 — read-only probe; absence, not an error
        logger.debug("read_public_key_fingerprint(%s) failed: %s", key_path, exc)
        return None


def _create_file_owner_only(path: Path, data: bytes) -> bool:
    """Create *path* atomically with owner-only permissions from the first
    byte (V7: os.open with O_CREAT | O_EXCL and mode 0600 — there is no
    write-then-chmod window in which the file holds a secret at default
    permissions, and no silent last-writer-wins between two AA processes).

    Returns False when the file already exists — a racing process won;
    the caller then READS the winner's file rather than overwriting it.
    On Windows the mode maps to owner read/write and the file inherits the
    directory's ACLs, as disclosed for the provenance key.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return True


def _read_when_settled(path: Path, attempts: int = 40, delay_s: float = 0.05) -> str:
    """Read a text file another process may still be writing (O_EXCL race).

    The loser of the creation race can arrive between the winner's open()
    and its write(); poll briefly for content rather than fork the identity
    or fail spuriously.
    """
    for _ in range(attempts):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text:
            return text
        time.sleep(delay_s)
    raise OSError(
        f"{path} is empty after waiting for a racing writer to settle"
    )


def read_research_salt(path: Path) -> str | None:
    """The salt at *path*, or None when absent, blank or unreadable.

    READ-ONLY: never creates anything. Surrounding whitespace is stripped,
    matching how the file is written (no trailing newline) rather than how
    the environment variable is read (verbatim).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    salt = text.strip()
    return salt or None


def provision_research_salt(path: Path) -> str:
    """Return the salt at *path*, generating and storing it if absent.

    Called when the user agrees to research and retried at each session
    build while consent is active, so a grant made when creation first
    failed heals itself. A generated salt is 32 bytes of CSPRNG hex,
    created atomically and owner-only (_create_file_owner_only, V7); a
    racing process reads the winner's file instead of overwriting it.

    Raises:
        OSError: the file cannot be created, or the winner's file cannot
            be read. Callers treat this as "research stays inactive",
            never as fatal.
    """
    existing = read_research_salt(path)
    if existing is not None:
        return existing
    salt = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _create_file_owner_only(path, salt.encode("utf-8")):
        logger.info("Research salt provisioned at %s", path)
        return salt
    logger.info("Research salt already provisioned by a racing process at %s", path)
    return _read_when_settled(path)


# =====================================================================
# 1. LOCAL DATA ENCRYPTION (The Vault)
# =====================================================================

class DataVault:
    """Handles AES-256 encryption for protecting the user's Profile JSON at rest."""

    def __init__(self, master_password: str, storage_dir: Path):
        """Derives a secure encryption key from a human password using PBKDF2."""
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 1. Manage the Master Salt (Allows 1 password for all profiles)
        salt_path = self.storage_dir / ".vault_salt"
        if salt_path.exists():
            salt = salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            salt_path.write_bytes(salt)

        # 2. Derive the AES-256 Key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000, # Slows down brute-force attacks
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))
        self.fernet = Fernet(key)

    def encrypt_dict(self, data: dict[str, Any]) -> bytes:
        """Serializes a dictionary to JSON and encrypts it."""
        json_data = json.dumps(data).encode("utf-8")
        return self.fernet.encrypt(json_data)

    def decrypt_dict(self, encrypted_data: bytes) -> dict[str, Any]:
        """Decrypts AES-256 payload and deserializes back to a dictionary."""
        try:
            decrypted_data = self.fernet.decrypt(encrypted_data)
            return json.loads(decrypted_data.decode("utf-8"))
        except Exception as e:
            logger.error("Decryption failed. Invalid password or corrupted file.")
            raise ValueError("Invalid Master Password") from e


# =====================================================================
# 2. DATA PROVENANCE (Cryptographic Signing)
# =====================================================================

class ProvenanceSigner:
    """Generates Ed25519 cryptographic signatures to verify research data origin."""

    def __init__(self, key_path: Path):
        """Loads the private signing key, or generates one if it doesn't exist."""
        self.key_path = key_path
        self.private_key, self.public_key_hex = self._load_or_generate_keys()

    def _load_or_generate_keys(self) -> tuple[ed25519.Ed25519PrivateKey, str]:
        if self.key_path.exists():
            # Load existing key
            with open(self.key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None # In production, you could encrypt this key too
                )
            _chmod_owner_only(self.key_path)
        else:
            # Generate a new anonymous identity for this installation
            logger.info("Generating new Ed25519 Cryptographic Identity for Research Provenance.")  # noqa: E501
            private_key = ed25519.Ed25519PrivateKey.generate()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            if not _create_file_owner_only(self.key_path, pem):
                # A racing process won the create; use ITS key, not ours —
                # last-writer-wins would fork the installation's identity (V7).
                private_key = self._load_private_key_settled()

        # Derive the public key (this is what you will use to verify data later)
        public_key = private_key.public_key()
        public_key_hex = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        ).hex()

        # serialization.load_pem_private_key returns the full private-key
        # union; this module only ever writes and reads Ed25519 keys.
        return cast(ed25519.Ed25519PrivateKey, private_key), public_key_hex

    def _load_private_key_settled(self, attempts: int = 40, delay_s: float = 0.05):
        """Load the key a racing process may still be writing (V7)."""
        for _ in range(attempts):
            try:
                with open(self.key_path, "rb") as key_file:
                    return serialization.load_pem_private_key(
                        key_file.read(), password=None
                    )
            except (OSError, ValueError):
                time.sleep(delay_s)
        raise OSError(
            f"provenance key at {self.key_path} is unreadable after a "
            "creation race"
        )

    def sign_hex(self, content_hash: str) -> str:
        """Sign a hex-encoded content hash and return the hex-encoded signature.

        Used by ResearchSignalAggregator to attach Ed25519 provenance to every
        research signal written to the database.  The signature proves that a
        signal originated from this specific AA installation without revealing
        the installation's identity (the public key is stored separately).

        Args:
            content_hash: A SHA-256 hex digest of the signal's content fields.

        Returns:
            Hex-encoded Ed25519 signature over the content hash bytes.
        """
        data = content_hash.encode("utf-8")
        signature = self.private_key.sign(data)
        return signature.hex()


# =====================================================================
# 3. CODEBASE INTEGRITY (Your Idea)
# =====================================================================

class CodebaseHasher:
    """Hashes the current state of the AA source code to detect alterations."""

    @staticmethod
    def hash_src_directory(src_path: Path) -> str:
        """Calculates a SHA-256 hash of all Python files in the src directory."""
        hasher = hashlib.sha256()

        # Get all .py files, sort them to ensure deterministic hashing
        py_files = sorted(src_path.rglob("*.py"))

        for file_path in py_files:
            # Skip the virtual environment or pycache if they accidentally sneak in
            if ".venv" in file_path.parts or "__pycache__" in file_path.parts:
                continue

            try:
                # Read file as bytes and update hash
                with open(file_path, "rb") as f:
                    hasher.update(f.read())
            except Exception:
                pass

        return hasher.hexdigest()