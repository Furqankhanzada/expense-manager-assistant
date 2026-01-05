"""Encryption utilities for sensitive data."""

from cryptography.fernet import Fernet

from src.config import get_settings


def get_cipher() -> Fernet:
    """Get the Fernet cipher instance."""
    settings = get_settings()
    return Fernet(settings.encryption_key.encode())


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for storage."""
    cipher = get_cipher()
    return cipher.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an encrypted API key."""
    cipher = get_cipher()
    return cipher.decrypt(encrypted_key.encode()).decode()
