import base64
import hashlib
from cryptography.fernet import Fernet

from app.core.config import settings


class IntegrationCryptoService:
    """Servicio de cifrado y descifrado simétrico para credenciales externas (Fernet)."""

    def __init__(self, secret: str | None = None) -> None:
        raw_secret = secret or settings.BETTER_AUTH_SECRET or "default-notion-encryption-secret-32b"
        key_32 = hashlib.sha256(raw_secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key_32))

    def encrypt(self, plain_text: str) -> str:
        """Cifra un texto plano devolviendo un token seguro codificado en string."""
        if not plain_text or not plain_text.strip():
            raise ValueError("No se puede cifrar un texto vacío.")
        token_bytes = self._fernet.encrypt(plain_text.strip().encode("utf-8"))
        return token_bytes.decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        """Descifra un token encriptado recuperando el texto original."""
        if not encrypted_token or not encrypted_token.strip():
            raise ValueError("No se puede descifrar un token vacío.")
        plain_bytes = self._fernet.decrypt(encrypted_token.strip().encode("utf-8"))
        return plain_bytes.decode("utf-8")
