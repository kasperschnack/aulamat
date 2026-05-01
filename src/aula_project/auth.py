from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from getpass import getpass
import json
import logging
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin

from aula_project.config import Settings
from aula_project.models import AuthCacheStatus, AuthResult


LOGGER = logging.getLogger(__name__)
TOKEN_EXPIRY_BUFFER_SECS = 60
SESSION_COOKIE_NAMES = (
    "SimpleSAML",
    "SimpleSAMLAuthToken",
    "AUTH_SESSION_ID",
    "KEYCLOAK_SESSION",
)


@dataclass(slots=True)
class AuthenticatedSession:
    client: Any
    auth_result: AuthResult


def _load_aula_auth() -> tuple[type[Any], Any, Any, type[Exception]]:
    try:
        from aula import FileTokenStorage
        from aula.auth_flow import authenticate, create_client
        from aula.http import AulaAuthenticationError
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "The 'aula' package is not installed. Run 'uv sync --dev' before using the CLI."
        ) from exc

    return FileTokenStorage, authenticate, create_client, AulaAuthenticationError


def _format_epoch(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def _format_epoch_local(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value)).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _local_timezone_name() -> str:
    return datetime.now().astimezone().tzname() or "local"


def inspect_token_cache(token_cache_path: Path) -> AuthCacheStatus:
    if not token_cache_path.exists():
        return AuthCacheStatus(cache_path=str(token_cache_path), cache_exists=False)

    try:
        raw_data = json.loads(token_cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AuthCacheStatus(cache_path=str(token_cache_path), cache_exists=True)

    if not isinstance(raw_data, dict):
        return AuthCacheStatus(cache_path=str(token_cache_path), cache_exists=True)

    tokens = raw_data.get("tokens", {})
    cookies = raw_data.get("cookies", {})
    expires_at = tokens.get("expires_at") if isinstance(tokens, dict) else None
    valid_for_seconds = None
    reusable = False
    if expires_at is not None:
        try:
            valid_for_seconds = int(float(expires_at) - time.time())
            reusable = valid_for_seconds > TOKEN_EXPIRY_BUFFER_SECS
        except (TypeError, ValueError):
            valid_for_seconds = None
    elif isinstance(tokens, dict) and tokens.get("access_token"):
        reusable = True

    session_cookie_names = [
        cookie_name
        for cookie_name in SESSION_COOKIE_NAMES
        if isinstance(cookies, dict) and isinstance(cookies.get(cookie_name), str) and cookies.get(cookie_name)
    ]

    return AuthCacheStatus(
        cache_path=str(token_cache_path),
        cache_exists=True,
        cached_at=str(raw_data.get("created_at")) if raw_data.get("created_at") else None,
        access_token_expires_at=_format_epoch(expires_at),
        access_token_expires_at_local=_format_epoch_local(expires_at),
        local_timezone=_local_timezone_name(),
        access_token_valid_for_seconds=valid_for_seconds,
        access_token_reusable=reusable,
        refresh_token_present=bool(isinstance(tokens, dict) and tokens.get("refresh_token")),
        cookie_count=len(cookies) if isinstance(cookies, dict) else 0,
        session_cookie_names=session_cookie_names,
        raw={
            "token_keys": sorted(tokens.keys()) if isinstance(tokens, dict) else [],
            "cookie_keys": sorted(cookies.keys()) if isinstance(cookies, dict) else [],
        },
    )


def _install_mitid_step4_compat_patch() -> None:
    try:
        from bs4 import BeautifulSoup, Tag
        from aula.auth.exceptions import NetworkError, SAMLError
        from aula.auth.mitid_client import MITID_BASE_URL, MitIDAuthClient
    except ImportError:
        return

    if getattr(MitIDAuthClient, "_aula_project_step4_patched", False):
        return

    async def _patched_step4_complete_mitid_flow(
        self: Any, verification_token: str, authorization_code: str
    ) -> dict[str, str]:
        try:
            session_uuid = self._client.cookies.get("SessionUuid", "")
            challenge = self._client.cookies.get("Challenge", "")

            params = {
                "__RequestVerificationToken": verification_token,
                "NewCulture": "",
                "MitIDUseConfirmed": "True",
                "MitIDAuthCode": authorization_code,
                "MitIDAuthenticationCancelled": "",
                "MitIDCoreClientError": "",
                "SessionStorageActiveSessionUuid": session_uuid,
                "SessionStorageActiveChallenge": challenge,
            }

            response = await self._client.post(f"{MITID_BASE_URL}/login/mitid", data=params)
            redirect_hops = 0
            while response.is_redirect and "Location" in response.headers and redirect_hops < 10:
                redirect_hops += 1
                next_url = urljoin(str(response.url), response.headers["Location"])
                LOGGER.debug("Following MitID completion redirect %s to %s", redirect_hops, next_url)
                response = await self._client.get(next_url)

            if str(response.url).endswith("/loginoption"):
                LOGGER.info("Multiple identities detected, handling identity selection")
                soup = await self._handle_login_option_page(response)
            else:
                soup = BeautifulSoup(response.text, features="html.parser")

            relay_state_input = soup.find("input", {"name": "RelayState"})
            saml_response_input = soup.find("input", {"name": "SAMLResponse"})

            relay_state = None
            saml_response = None
            if isinstance(relay_state_input, Tag):
                relay_state = str(relay_state_input.get("value", ""))
            if isinstance(saml_response_input, Tag):
                saml_response = str(saml_response_input.get("value", ""))

            # Fallback for pages where values are rendered differently but still embedded in HTML.
            if not relay_state:
                relay_match = re.search(r'name=["\']RelayState["\'][^>]*value=["\']([^"\']+)["\']', response.text)
                if relay_match:
                    relay_state = relay_match.group(1)
            if not saml_response:
                saml_match = re.search(
                    r'name=["\']SAMLResponse["\'][^>]*value=["\']([^"\']+)["\']', response.text
                )
                if saml_match:
                    saml_response = saml_match.group(1)

            if not relay_state or not saml_response:
                debug_dir = Path(".aula_auth_debug")
                debug_dir.mkdir(parents=True, exist_ok=True)
                html_path = debug_dir / "mitid-step4-response.html"
                meta_path = debug_dir / "mitid-step4-response.txt"
                html_path.write_text(response.text, encoding="utf-8")
                form_names: list[str] = []
                for form in soup.find_all("form"):
                    if isinstance(form, Tag):
                        action = str(form.get("action", ""))
                        form_names.append(action)
                input_names: list[str] = []
                for input_tag in soup.find_all("input"):
                    if isinstance(input_tag, Tag):
                        name = input_tag.get("name")
                        if isinstance(name, str) and name:
                            input_names.append(name)
                meta_path.write_text(
                    "\n".join(
                        [
                            f"url: {response.url}",
                            f"status: {response.status_code}",
                            f"redirect_hops: {redirect_hops}",
                            f"forms: {form_names}",
                            f"inputs: {input_names}",
                        ]
                    ),
                    encoding="utf-8",
                )
                raise SAMLError(
                    "Could not find SAML data in MitID completion response. "
                    f"Saved debug HTML to {html_path} and metadata to {meta_path}."
                )

            return {
                "relay_state": relay_state,
                "saml_response": saml_response,
            }

        except Exception as exc:
            if isinstance(exc, (SAMLError, NetworkError)):
                raise
            raise NetworkError(f"Network error during MitID completion: {exc}") from exc

    MitIDAuthClient._step4_complete_mitid_flow = _patched_step4_complete_mitid_flow
    MitIDAuthClient._aula_project_step4_patched = True


def _print_qr_codes_in_terminal(qr1: Any, qr2: Any) -> None:
    print("=" * 60)
    print("SCAN THESE QR CODES WITH YOUR MITID APP")
    print("=" * 60)
    print("QR CODE 1 (scan this first):")
    qr1.print_ascii(invert=True)
    print("QR CODE 2 (scan this second):")
    qr2.print_ascii(invert=True)
    print("=" * 60)
    print("Waiting for MitID approval...")
    print("=" * 60)


def _on_login_required() -> None:
    print("Session expired or not found. Open your MitID app to approve the login.")


async def _select_identity(identities: list[str]) -> int:
    print("\nMultiple MitID identities found:")
    for index, identity in enumerate(identities, start=1):
        print(f"  {index}. {identity}")

    while True:
        choice = input("Select identity [1]: ").strip() or "1"
        if choice.isdigit():
            selected = int(choice)
            if 1 <= selected <= len(identities):
                return selected - 1
        print("Enter a valid number from the list.")


async def _prompt_token_digits() -> str:
    return input("MitID token code (6 digits): ").strip()


async def _prompt_password() -> str:
    return getpass("MitID password: ")


@asynccontextmanager
async def authenticated_session(settings: Settings):
    file_token_storage, authenticate, create_client, aula_auth_error = _load_aula_auth()
    _install_mitid_step4_compat_patch()
    settings.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
    token_storage = file_token_storage(str(settings.token_cache_path))
    initial_cache = inspect_token_cache(settings.token_cache_path)
    login_required = False

    def _wrapped_on_login_required() -> None:
        nonlocal login_required
        login_required = True
        _on_login_required()

    token_data = await authenticate(
        settings.mitid_username,
        token_storage,
        on_qr_codes=_print_qr_codes_in_terminal,
        on_login_required=_wrapped_on_login_required,
        on_identity_selected=_select_identity,
        auth_method=settings.auth_method,
        on_token_digits=_prompt_token_digits,
        on_password=_prompt_password,
    )

    strategy = "fresh_login"
    if not login_required:
        if initial_cache.access_token_reusable:
            strategy = "cached_access_token"
        elif initial_cache.refresh_token_present:
            strategy = "refreshed_access_token"
        elif initial_cache.cache_exists:
            strategy = "reused_cached_session"

    try:
        client = await create_client(token_data)
    except aula_auth_error:
        token_data = await authenticate(
            settings.mitid_username,
            token_storage,
            on_qr_codes=_print_qr_codes_in_terminal,
            on_login_required=_wrapped_on_login_required,
            force_login=True,
            on_identity_selected=_select_identity,
            auth_method=settings.auth_method,
            on_token_digits=_prompt_token_digits,
            on_password=_prompt_password,
        )
        client = await create_client(token_data)
        strategy = "fresh_login_after_cookie_rejection"

    auth_result = AuthResult(strategy=strategy, cache=inspect_token_cache(settings.token_cache_path))
    async with client:
        yield AuthenticatedSession(client=client, auth_result=auth_result)


@asynccontextmanager
async def authenticated_client(settings: Settings):
    async with authenticated_session(settings) as session:
        yield session.client
