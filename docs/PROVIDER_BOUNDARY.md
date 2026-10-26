# Offline provider-boundary conformance

`provider_boundary.py` defines an **unwired provider-neutral boundary**, not a
working provider integration. It includes no network client, SDK, credentials,
provider selection, fallback, retry, approved-method content or customer route.
The canonical request/response envelopes are an application contract. A future
vendor-specific transport must explicitly map its vendor wire format to them;
these fixtures do not claim compatibility with an existing vendor endpoint.

`ProviderConfig` requires an explicit task/model/HTTPS endpoint/host allowlist,
locale (`it`, `de`, `fr`, `en`), response schema, timeout and request/response byte
caps. Endpoint URLs cannot contain user information, query credentials,
fragments, IP literals, local hosts, alternate ports or path traversal. There is
no default provider/model/endpoint. Configuration and transport-body reprs avoid
exposing model/endpoint/payload details; errors contain only fixed safe messages.
No exception body or provider response is logged.

The injected `SingleAttemptTransport` must authenticate out of band, verify TLS,
resolve approved hosts safely (including rejecting private/link-local resolution),
apply the streaming response cap, honour cancellation and timeout, and perform
**one attempt with no redirect, retry or provider substitution**. This repository
does not implement that transport. Caller-side checks before/after dispatch are
additional safeguards, not a mechanism to forcibly interrupt an uncooperative
transport. No worker or background thread is started.

The orchestrator remains responsible for the durable request reservation before
each callback; the boundary calls `transport.send` at most once per invocation.
Timeout/cancellation after dispatch does not prove non-billing and must never
refund an uncertain attempt. Token, currency and provider-specific limits still
require their own integration and real authorized checks.

JSON parsing rejects duplicate keys, nonfinite numbers, invalid UTF-8, excessive
nesting/arrays/text, truncation, oversized responses and mismatched
schema/model/locale. Vision output reuses the existing frame/source/bounding-box
invariants. Speech maps wire `start`/`end` into `start_seconds`/`end_seconds`,
validates timing against duration and preserves language and declared text.
Spoken statements are not converted into observed visual facts.

`RealVideoAdapterBoundary` is intentionally distinct from
`SyntheticVideoAdapters`. Both the existing orchestrator and customer synthetic
route reject it; no environment switch enables it. The synthetic route remains
default-disabled and requires testing/synthetic mode plus its own exact adapter
type. No integration path to a real provider is introduced by this increment.

## Conformance without network

```
python3 scripts/provider_conformance.py
python3 -m pytest -q tests/test_provider_boundary.py
```

`tests/fixtures/provider_boundary/*.json` contains fixed sanitized **synthetic
recorded wire fixtures**, not captures of customer media or real provider tests.
The command dispatches only to an in-memory recorded transport, guards socket
creation and prints mapping results, attempt count and `real_provider_tested:
false`. Offline conformance proves contract handling, not model accuracy,
latency, price, legal correctness or production readiness.
