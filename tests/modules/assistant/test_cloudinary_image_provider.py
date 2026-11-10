import asyncio
import cloudinary.uploader

import pytest

from app.core.config import settings
from app.modules.assistant.domain.exceptions import ImageStorageUnavailableException
from app.modules.assistant.infrastructure.external.cloudinary_image_provider import (
    CloudinaryImageProvider,
)


def test_upload_returns_secure_url_and_attempt_public_id(monkeypatch):
    provider = CloudinaryImageProvider.__new__(CloudinaryImageProvider)
    provider._configured = True
    upload_options = {}

    def upload(*args, **kwargs):
        upload_options.update(kwargs)
        return {
            "secure_url": "https://res.cloudinary.com/test/image/upload/item.png",
            "public_id": kwargs["public_id"],
        }

    monkeypatch.setattr(
        cloudinary.uploader,
        "upload",
        upload,
    )
    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_in_thread)
    result = asyncio.run(provider.upload(b"image", public_id="agent/messages/attempt"))
    assert result.url.startswith("https://")
    assert result.public_id == "agent/messages/attempt"

    assert settings.CLOUDINARY_TIMEOUT_SECONDS >= 1
    assert upload_options["timeout"] == settings.CLOUDINARY_TIMEOUT_SECONDS


def test_upload_hides_provider_failure(monkeypatch):
    provider = CloudinaryImageProvider.__new__(CloudinaryImageProvider)
    provider._configured = True

    def fail(*args, **kwargs):
        raise RuntimeError("secret API key must not escape")

    monkeypatch.setattr(cloudinary.uploader, "upload", fail)

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_in_thread)
    with pytest.raises(ImageStorageUnavailableException) as error:
        asyncio.run(provider.upload(b"image", public_id="agent/messages/attempt"))
    assert "secret API key" not in str(error.value)


def test_invalid_provider_url_compensates_created_asset(monkeypatch):
    provider = CloudinaryImageProvider.__new__(CloudinaryImageProvider)
    provider._configured = True
    deleted = []
    monkeypatch.setattr(
        cloudinary.uploader,
        "upload",
        lambda *args, **kwargs: {
            "secure_url": "http://res.cloudinary.com/test/item.png",
            "public_id": "agent/messages/attempt",
        },
    )
    monkeypatch.setattr(
        cloudinary.uploader,
        "destroy",
        lambda public_id, **kwargs: deleted.append(public_id),
    )

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_in_thread)
    with pytest.raises(ImageStorageUnavailableException):
        asyncio.run(provider.upload(b"image", public_id="agent/messages/attempt"))
    assert deleted == ["agent/messages/attempt"]
