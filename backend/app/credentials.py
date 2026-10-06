from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError

from .config import APP_NAME


_ACCOUNT = "novelai-persistent-api-token"
_DISCORD_WEBHOOK_ACCOUNT_PREFIX = "discord-webhook-"


def _service_name() -> str:
    return os.getenv("NOVELAI_STUDIO_CREDENTIAL_SERVICE", APP_NAME)


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    """Stores the persistent token in the Windows Credential Manager via keyring."""

    def get_token(self) -> str | None:
        environment_token = os.getenv("NOVELAI_API_TOKEN")
        if environment_token:
            return environment_token.strip()
        try:
            value = keyring.get_password(_service_name(), _ACCOUNT)
        except KeyringError as exc:
            raise CredentialStoreError("Windows 자격 증명 저장소를 읽지 못했습니다.") from exc
        return value.strip() if value else None

    def set_token(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise CredentialStoreError("API 토큰이 비어 있습니다.")
        try:
            keyring.set_password(_service_name(), _ACCOUNT, token)
        except KeyringError as exc:
            raise CredentialStoreError("Windows 자격 증명 저장소에 토큰을 저장하지 못했습니다.") from exc

    def delete_token(self) -> None:
        try:
            keyring.delete_password(_service_name(), _ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CredentialStoreError("Windows 자격 증명 저장소에서 토큰을 삭제하지 못했습니다.") from exc

    @staticmethod
    def _discord_webhook_account(webhook_id: str) -> str:
        return f"{_DISCORD_WEBHOOK_ACCOUNT_PREFIX}{webhook_id}"

    def get_discord_webhook_url(self, webhook_id: str) -> str | None:
        try:
            value = keyring.get_password(
                _service_name(), self._discord_webhook_account(webhook_id)
            )
        except KeyringError as exc:
            raise CredentialStoreError(
                "Windows 자격 증명 저장소에서 Discord 웹훅을 읽지 못했습니다."
            ) from exc
        return value.strip() if value else None

    def set_discord_webhook_url(self, webhook_id: str, url: str) -> None:
        url = url.strip()
        if not url:
            raise CredentialStoreError("Discord 웹훅 주소가 비어 있습니다.")
        try:
            keyring.set_password(
                _service_name(), self._discord_webhook_account(webhook_id), url
            )
        except KeyringError as exc:
            raise CredentialStoreError(
                "Windows 자격 증명 저장소에 Discord 웹훅을 저장하지 못했습니다."
            ) from exc

    def delete_discord_webhook_url(self, webhook_id: str) -> None:
        try:
            keyring.delete_password(
                _service_name(), self._discord_webhook_account(webhook_id)
            )
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CredentialStoreError(
                "Windows 자격 증명 저장소에서 Discord 웹훅을 삭제하지 못했습니다."
            ) from exc
