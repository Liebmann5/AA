"""Enterprise-grade data security, encryption, and cryptographic provenance.

This module provides:
1. DataVault: AES-256 (Fernet) encryption for local PII at rest.
2. ProvenanceSigner: Ed25519 cryptographic signatures for research data.
3. CodebaseHasher: Integrity verification for academic datasets.
"""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

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
        else:
            # Generate a new anonymous identity for this installation
            logger.info("Generating new Ed25519 Cryptographic Identity for Research Provenance.")  # noqa: E501
            private_key = ed25519.Ed25519PrivateKey.generate()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.key_path, "wb") as key_file:
                key_file.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))

        # Derive the public key (this is what you will use to verify data later)
        public_key = private_key.public_key()
        public_key_hex = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        ).hex()

        return private_key, public_key_hex

    def sign_payload(self, payload: dict[str, Any], code_hash: str) -> dict[str, Any]:
        """Cryptographically signs a row of research data.

        Adds the signature, the public key (anonymous user ID), and the code hash.
        """
        # We must sign a deterministic string representation of the data
        # We remove any existing signatures to prevent recursive signing
        clean_payload = {k: v for k, v in payload.items() if not k.startswith("_")}

        # Add your brilliant Codebase Integrity Hash
        clean_payload["_codebase_hash"] = code_hash
        clean_payload["_public_key"] = self.public_key_hex

        # Serialize to bytes, sorted by key to ensure exact deterministic matching
        payload_bytes = json.dumps(clean_payload, sort_keys=True).encode("utf-8")

        # Generate the cryptographic signature
        signature = self.private_key.sign(payload_bytes)

        # Attach the signature to the final output
        clean_payload["_signature"] = signature.hex()
        return clean_payload

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