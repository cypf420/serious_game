from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FieldCipher:
    """Versioned AES-256-GCM envelope for sensitive text and JSON fields."""

    def __init__(self, key_base64: str, *, key_id: str) -> None:
        try:
            key = base64.urlsafe_b64decode(key_base64.encode("ascii"))
        except Exception as exc:
            raise ValueError("field encryption key must be URL-safe base64") from exc
        if len(key) != 32:
            raise ValueError("field encryption key must decode to exactly 32 bytes")
        if not key_id.strip():
            raise ValueError("field encryption key id is required")
        self._cipher = AESGCM(key)
        self.key_id = key_id.strip()

    def encrypt_text(self, plaintext: str, *, purpose: str) -> str:
        nonce = os.urandom(12)
        aad = f"serious-game:{purpose}:v1".encode("utf-8")
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return json.dumps({
            "v": 1,
            "kid": self.key_id,
            "purpose": purpose,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }, separators=(",", ":"), sort_keys=True)

    def decrypt_text(self, envelope: str, *, purpose: str) -> str:
        value = json.loads(envelope)
        if value.get("v") != 1 or value.get("kid") != self.key_id:
            raise ValueError("unsupported field encryption envelope or key id")
        if value.get("purpose") != purpose:
            raise ValueError("field encryption purpose mismatch")
        aad = f"serious-game:{purpose}:v1".encode("utf-8")
        plaintext = self._cipher.decrypt(
            base64.urlsafe_b64decode(value["nonce"]),
            base64.urlsafe_b64decode(value["ciphertext"]),
            aad,
        )
        return plaintext.decode("utf-8")

    def encrypt_json(self, value: dict, *, purpose: str) -> dict:
        plaintext = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return {"encrypted_envelope": self.encrypt_text(plaintext, purpose=purpose)}

    def decrypt_json(self, value: dict, *, purpose: str) -> dict:
        envelope = value.get("encrypted_envelope")
        if not isinstance(envelope, str):
            raise ValueError("encrypted JSON envelope is missing")
        return json.loads(self.decrypt_text(envelope, purpose=purpose))
