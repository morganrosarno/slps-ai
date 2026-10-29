"""Read-only runtime interlock for registration, with an explicit test capability.

This module performs no delivery or ledger initialization. Provider acceptance
remains unimplemented, so normal registration cannot be unlocked by a flag.
"""
from pathlib import Path

from scripts.preflight import ConfiguredAccountDeliveryAdapter, account_delivery_checks
from delivery_boundary import DEFAULT_DELIVERY_TIMEOUT_SECONDS
from delivery_reservations import DeliveryReservationPolicy

DEFAULT_DELIVERY_OUTCOME_RETENTION_SECONDS = DeliveryReservationPolicy().outcome_retention_seconds


class _SyntheticRegistrationCapability:
    __slots__ = ()


_SYNTHETIC_REGISTRATION = _SyntheticRegistrationCapability()


def synthetic_registration_capability():
    """Opaque in-process fixture capability; never sourced from env or HTTP."""
    return _SYNTHETIC_REGISTRATION


_CONFIG_KEYS = {
    "SLPS_DELIVERY_RESERVATION_SECRET": "DELIVERY_RESERVATION_SECRET",
    "SLPS_DELIVERY_DB_PATH": "DELIVERY_DB_PATH",
    "SLPS_DELIVERY_CHECKPOINT_PATH": "DELIVERY_CHECKPOINT_PATH",
    "SLPS_DELIVERY_TIMEOUT_SECONDS": "DELIVERY_TIMEOUT_SECONDS",
    "SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS": "DELIVERY_OUTCOME_RETENTION_SECONDS",
    "SLPS_ACCOUNT_DELIVERY_ADAPTER": "ACCOUNT_DELIVERY_ADAPTER",
    "SLPS_ACCOUNT_DB_PATH": "ACCOUNT_DB_PATH",
    "SLPS_RATE_DB_PATH": "RATE_DB_PATH",
    "SLPS_CASE_DB_PATH": "CASE_DB_PATH",
    "SLPS_HISTORY_ROOT": "HISTORY_ROOT",
    "SLPS_PROMPT_PATH": "PROMPT_PATH",
    "SLPS_SOURCES_PATH": "SOURCES_PATH",
    "SLPS_SESSION_SECRET": "SECRET_KEY",
    "SLPS_PILOT_PASSWORD": "PILOT_PASSWORD",
    "SLPS_PRIVATE_GATE_PASSWORD": "PRIVATE_GATE_PASSWORD",
    "OPENAI_API_KEY": "OPENAI_API_KEY",
}
_REQUIRED_CHECKS = frozenset({
    "account_delivery_secret", "account_delivery_db_path", "account_delivery_checkpoint_path",
    "account_delivery_paths_distinct", "account_delivery_secret_stability",
    "account_delivery_marker_retention", "account_delivery_adapter",
    "account_delivery_provider_verification",
})


def registration_delivery_status(config, *, testing, root: Path) -> str:
    """Return only a fixed public status, never configuration or diagnostics."""
    if (testing is True and config.get("DATA_MODE") == "synthetic"
            and config.get("ACCOUNT_REGISTRATION_TEST_CAPABILITY") is _SYNTHETIC_REGISTRATION):
        return "synthetic_test_only"
    try:
        settings = {env: config.get(key) for env, key in _CONFIG_KEYS.items()}
        adapter = config.get("ACCOUNT_DELIVERY_ADAPTER_CAPABILITY")
        if not isinstance(adapter, ConfiguredAccountDeliveryAdapter):
            adapter = None
        checks = account_delivery_checks(settings, root, registration_open=True,
                                         delivery_adapter=adapter)
        if (len(checks) == len(_REQUIRED_CHECKS)
                and {item.id for item in checks} == _REQUIRED_CHECKS
                and all(item.status == "pass" for item in checks)):
            # The current shared preflight always blocks provider verification.
            # A future integration must supply real acceptance, not an env flag.
            return "ready"
    except Exception:
        pass
    return "delivery_unavailable"
