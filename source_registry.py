"""Offline, versioned primary-source registry. No model URLs are ever fetched.

Classification describes the registered proposition, not its applicability to
a photograph or a legal finding. Legacy owner lists stay explicitly unclassified.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 200_000
CLASSIFICATIONS = {"obligation", "recommendation", "hypothesis"}
KINDS = {"law", "authority_guidance", "technical_guidance", "application_hypothesis"}
OFFICIAL_HOSTS = {"www.fedlex.admin.ch", "fedlex.admin.ch", "www.seco.admin.ch",
                  "seco.admin.ch", "www.suva.ch", "suva.ch", "www.ekas.admin.ch",
                  "ekas.admin.ch", "www.cfsl.admin.ch", "cfsl.admin.ch"}
BASE_KEYS = {"id", "title", "url", "verified_at", "excerpt"}
DETAIL_KEYS = {"classification", "source_kind", "publisher", "locator", "scope",
               "document_version", "limitations", "verification_scope"}
PUBLIC_KEYS = ("id", "title", "url", "verified_at", "classification", "source_kind",
               "publisher", "locator", "scope", "document_version", "limitations",
               "verification_scope", "registry_version")


class RegistryError(ValueError):
    """Invalid registry; callers must fail closed before provider submission."""


def _text(value, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise RegistryError("invalid text")
    return value


def _date(value):
    _text(value, 40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RegistryError("invalid verification date") from None
    if parsed.date() > date.today():
        raise RegistryError("future verification date")


def validate_registry(payload) -> list[dict]:
    """Return a defensive normalized list, accepting legacy lists for migration."""
    version = None
    if isinstance(payload, dict):
        if set(payload) != {"schema_version", "registry_version", "jurisdiction", "sources"}:
            raise RegistryError("invalid envelope")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["jurisdiction"] != "CH":
            raise RegistryError("unsupported registry")
        version = _text(payload["registry_version"], 80)
        payload = payload["sources"]
    if not isinstance(payload, list) or len(payload) > 30:
        raise RegistryError("invalid source list")
    result, identifiers = [], set()
    for item in payload:
        if not isinstance(item, dict):
            raise RegistryError("invalid source")
        for key in BASE_KEYS:
            _text(item.get(key), 20_000 if key == "excerpt" else 2000)
        if item["id"] in identifiers or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", item["id"]):
            raise RegistryError("ambiguous source identifier")
        identifiers.add(item["id"])
        try:
            url = urlsplit(item["url"])
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.port not in (None, 443) or any(c.isspace() for c in item["url"])):
                raise RegistryError("unsafe source URL")
        except ValueError:
            raise RegistryError("unsafe source URL") from None
        _date(item["verified_at"])
        source = {key: copy.deepcopy(item[key]) for key in BASE_KEYS}
        if version is not None:
            if set(item) != BASE_KEYS | DETAIL_KEYS or url.hostname not in OFFICIAL_HOSTS:
                raise RegistryError("versioned registry requires approved primary-source host and fields")
            if not isinstance(item["classification"], str) or not isinstance(item["source_kind"], str):
                raise RegistryError("invalid claim classification")
            if item["classification"] not in CLASSIFICATIONS or item["source_kind"] not in KINDS:
                raise RegistryError("invalid claim classification")
            if item["classification"] == "obligation" and item["source_kind"] not in {"law", "authority_guidance"}:
                raise RegistryError("guidance is not automatically an obligation")
            if (item["classification"] == "hypothesis") != (item["source_kind"] == "application_hypothesis"):
                raise RegistryError("hypotheses must be labelled as application inferences")
            for key in DETAIL_KEYS - {"limitations"}:
                _text(item[key])
            limits = item["limitations"]
            if not isinstance(limits, list) or not 1 <= len(limits) <= 8:
                raise RegistryError("source limitations required")
            for limit in limits:
                _text(limit)
            source.update({key: copy.deepcopy(item[key]) for key in DETAIL_KEYS})
            source["registry_version"] = version
        # Never trust classification-like extra fields in an unversioned legacy list.
        result.append(source)
    return result


def read_registry(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise RegistryError("registry too large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RegistryError("invalid JSON") from None
    return validate_registry(payload)


def public_source(source: dict) -> dict:
    """Only provenance metadata reaches the report, never registry excerpt text."""
    return {key: copy.deepcopy(source[key]) for key in PUBLIC_KEYS if key in source}
