"""Explicit synthetic registration rehearsal; no delivery transport is enabled."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Lock
from pathlib import Path

from accounts import AccountConflict, AccountStore, LOCALES, clean_text, company_identity, normalize_email, valid_password
from account_delivery_runtime import registration_delivery_status
from delivery_boundary import CancellationToken, DeliveryConfig, DeliveryTransportResult
from delivery_provider_readiness import ProviderNeutralDeliveryCoordinator
from delivery_reservations import SQLiteDeliveryReservationStore


class SyntheticRegistrationUnavailable(RuntimeError):
    pass


class _NoSendAdapter:
    """A deliberate rejection, never a simulated successful email delivery."""
    __slots__ = ("calls",)

    def __init__(self):
        self.calls = 0

    def send(self, _envelope, *, cancellation):
        self.calls += 1
        return DeliveryTransportResult(False)


class _SyntheticWorkflow:
    __slots__ = ("accounts", "ledger", "adapter", "coordinator", "lock")

    def __init__(self, accounts, ledger):
        self.accounts, self.ledger = accounts, ledger
        self.adapter, self.lock = _NoSendAdapter(), Lock()
        self.coordinator = ProviderNeutralDeliveryCoordinator(
            config=DeliveryConfig(("accounts.slps.example",)), adapter=self.adapter,
            ledger=ledger, cancellation=CancellationToken(),
        )


def _enabled(app):
    return (app.testing is True and app.config.get("DATA_MODE") == "synthetic"
            and app.config.get("AUTH_MODE") == "accounts"
            and app.config.get("ACCOUNT_REGISTRATION_OPEN") is True
            and registration_delivery_status(app.config, testing=app.testing,
                                             root=app.root_path) == "synthetic_test_only")


def synthetic_workflow_available(app):
    workflow = app.extensions.get("synthetic_registration_workflow")
    return (type(workflow) is _SyntheticWorkflow and _enabled(app)
            and workflow.accounts is app.extensions.get("account_store")
            and type(workflow.adapter) is _NoSendAdapter)


def install_synthetic_registration_workflow(app, ledger=None):
    """Trusted fixture only: bind existing synthetic stores, never open a flag.

    The caller owns the disposable ledger and its synthetic HMAC key. No file,
    provider, credential or configuration is created from an HTTP request.
    """
    accounts = app.extensions.get("account_store")
    if not _enabled(app) or type(accounts) is not AccountStore:
        raise SyntheticRegistrationUnavailable()
    if ledger is None:
        root = Path(app.config["ACCOUNT_DB_PATH"]).parent / "synthetic-registration-delivery"
        ledger = SQLiteDeliveryReservationStore(
            root / "ledger.sqlite3", checkpoint_path=root / "checkpoint.json",
            key_secret=b"synthetic-registration-nosend-key-only-42",
        )
    if type(ledger) is not SQLiteDeliveryReservationStore:
        raise SyntheticRegistrationUnavailable()
    workflow = _SyntheticWorkflow(accounts, ledger)
    app.extensions["synthetic_registration_workflow"] = workflow
    return workflow


def prepare_synthetic_registration(app, data):
    """Pre-commit proof only. An error here means no account was created."""
    workflow = app.extensions.get("synthetic_registration_workflow")
    if not synthetic_workflow_available(app):
        raise SyntheticRegistrationUnavailable()
    email = normalize_email(data.get("email"))
    if not email.endswith(".test") or not valid_password(data.get("password")):
        raise ValueError("synthetic_registration_input")
    _, _, company = company_identity(data.get("company_name"), data.get("company_identifier", ""))
    role, locale = clean_text(data.get("role"), "role", 100), data.get("locale", "it")
    if locale not in LOCALES:
        raise ValueError("synthetic_registration_input")
    with workflow.accounts.connect() as db:
        if (db.execute("SELECT 1 FROM account_users WHERE email=?", (email,)).fetchone()
                or db.execute("SELECT 1 FROM account_companies WHERE identity_key=?", (company,)).fetchone()):
            raise AccountConflict("registration_unavailable")
    digest = hashlib.sha256(json.dumps([email, company, role, locale],
                                      ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    key = "synthetic-registration:" + digest
    # Fixed non-actionable fixture token: never issued to AccountStore or persisted.
    action = "https://accounts.slps.example/account/verify-email?token=" + "synthetic_unusable_" + "0" * 32
    expires = (datetime.now(timezone.utc).replace(second=0, microsecond=0)
               + timedelta(minutes=30)).isoformat()
    try:
        with workflow.lock:
            before = workflow.adapter.calls
            result = workflow.coordinator.dispatch(
                recipient=email, purpose="verify_email", locale=locale,
                action_url=action, expires_at_utc=expires, idempotency_key=key,
            )
            # A replay, forged success or uncertain result cannot create an account.
            if (workflow.adapter.calls != before + 1 or not isinstance(result, dict)
                    or result.get("status") != "failed" or result.get("code") != "transport_rejected"
                    or result.get("final") is not True or result.get("chain_valid") is not True
                    or result.get("provider_reference_present") is not False):
                raise SyntheticRegistrationUnavailable()
    except Exception:
        raise SyntheticRegistrationUnavailable() from None
    return {"synthetic_only": True, "sent": False, "status": "failed", "code": "transport_rejected"}
