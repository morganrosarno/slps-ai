# Local account foundation

The default `SLPS_AUTH_MODE=pilot` preserves existing pilot access. Opting into
`accounts` requires a strong session secret and a private persistent account DB;
it does not require the pilot password. Account mode always uses a single
company trial, even if legacy `SLPS_PILOT_PLAN=internal` or trial-total settings
are present. `SLPS_ACCOUNT_REGISTRATION_OPEN=true` now expresses intent only.
Landing, session API and registration POST share a runtime delivery interlock:
registration stays unavailable until every shared delivery preflight check
passes, including provider verification. That verification is not implemented
yet, so the normal runtime stays closed even with the flag set. A blocked POST
returns `account_delivery_unavailable` before account/token creation, delivery
or registration-rate mutations. Existing-account login remains available.
No public deployment is implied.

The session exposes effective `registration_open` and a fixed
`registration_status`: `closed`, `unavailable`, `delivery_unavailable`, or
`synthetic_test_only` for explicit fixtures. It never reveals provider details,
paths, secrets or individual preflight failures. `delivery_configured` remains
false. This interlock reads existing delivery state without initializing or
migrating a ledger from a request and invokes no transport.
An already-open registration form closes immediately on the interlock error,
clears its password and displays a focused message in IT/DE/FR/EN. It offers
existing-account login without automatically resubmitting or refreshing.

Disposable synthetic fixtures may inject the opaque object returned by
`account_delivery_runtime.synthetic_registration_capability()` through the
in-process `ACCOUNT_REGISTRATION_TEST_CAPABILITY` configuration. It is accepted
only when `app.testing is True` and `DATA_MODE` is exactly `synthetic`. Strings,
booleans, mappings, environment/HTTP values and arbitrary objects cannot replace
it. This explicit fixture bypass does not attest production readiness, send a
message, expose a token, verify a company or enable real-data mode. Removing it
or changing either required mode closes registration on the next request.
The opaque capability alone is no longer sufficient: a trusted fixture must
also call `install_synthetic_registration_workflow(app)` from
`account_registration_nosend`. This prepares a disposable synthetic ledger and
binds the workflow to that app's account store. Before account creation, the
provider-neutral coordinator records the deterministic no-send adapter's
deliberate rejection (`failed/transport_rejected`). It never records a successful
email acceptance. The `.example` action link contains a non-actionable synthetic
token, never issued to the account store or persisted. Only a fresh, final,
chain-verified rejection allows the existing atomic account + pending-review
transaction. Coordinator error, uncertainty, success or replay stops before
account mutation. If the account transaction fails afterward, its rows roll
back and the independent synthetic rejection remains; this is not a cross-store
atomic transaction. No adapter/ledger is constructed by anonymous requests.

Registration stores company name, optional identifier, representative role,
email, language (`it`, `de`, `fr`, `en`) and a password hash. Email confirmation,
company verification and approval to represent/join that company are separate
states. All three are required before analysis or case access. A submitted
identifier or email domain does not verify the company. Matching an existing
company never automatically joins it; additional users require trusted
provisioning. Company deduplication is a preliminary safeguard, not registry
verification or a complete protection against alternate company spellings.

`AccountStore.issue_token` is a trusted delivery-adapter/local-test primitive:
only a digest, purpose and expiration are stored. No HTTP response returns the
raw token. Email and reset confirmation accept a supplied token in a JSON body,
require CSRF/same-origin checks and consume it once. Password reset invalidates
existing account sessions via a stored version. Company/membership verification
has no public endpoint. New registrations and unapproved members enter a local
operator queue. The queue requires an explicit in-process capability, stores no
raw operator reference or idempotency key, and records each coded decision in an
append-only, hash-linked audit. Company approval and representative authority
are one atomic decision; a later member can be approved only after the company.
The older `verify_company` shortcut is disabled outside explicit test fixtures.
No identifier, email domain or submitted role can approve either state.

L'uso operativo locale della coda è descritto nel runbook pubblico
[`COMPANY_VERIFICATION_OPERATOR.md`](COMPANY_VERIFICATION_OPERATOR.md). Il comando
rimane fuori dal server e proietta soltanto JSON depurato.

The delivery boundary is provider-neutral and remains deliberately unwired. It
may prepare verification, password-reset and company-invitation messages only
after an injected transport is configured and tested; the default path performs
no network request and sends no email. Registration and reset request responses
explicitly report `delivery_configured=false`; the reset request response is
identical for known and unknown email addresses and never claims a mail was sent.
The current local flow therefore cannot be presented as unattended production
onboarding, password recovery or invitation delivery. Do not expose tokens in
logs, URLs, analytics, browser storage or chat.

The customer status view keeps three decisions separate: personal email,
company identity and the person's authorisation for that company. A declared
role or entered UID/CHE identifier never approves the latter two. Pending
company and membership states explicitly require an operator decision, while
analysis, history, consultation and checkout remain unavailable.

The unwired contract accepts only these future action paths: `verify_email` uses
`/account/verify-email`, `reset_password` uses `/account/reset-password`, and
`company_invitation` uses `/account/company-invitation`. They are allowlisted
link contracts, not active customer endpoints. A different path fails before a
reservation or transport attempt.

`SQLiteDeliveryReservationStore` is the durable idempotency primitive for a
future transport. It records only an HMAC-SHA256 digest of the operation key,
never the raw key, and refuses to open the database if the injected secret does
not match its stored fingerprint. The default retention is seven days and the
default active-reservation cap is 50,000. At capacity it removes expired rows
only, then fails closed; it never evicts an active reservation to permit another
attempt. An expired key can be reserved again. This reservation alone does not
mean that a message was delivered and is not wired into `server.py`.

The same private SQLite store can append a delivery outcome after a future
single transport attempt. Outcomes are limited to `accepted`, `failed` and
`uncertain`, each with a small allowlist of machine codes. An uncertain outcome
may be reconciled once to accepted or failed; a final outcome cannot change.
Every reconciliation is idempotent and linked to the existing reservation by
its HMAC digest. Provider references and reconciliation keys are HMACed; raw
values, recipients, action URLs and tokens are not stored or returned. A chained
HMAC plus the reservation head makes missing, changed or reordered events fail
closed. Reservation retention and outcome retention are separate policy values.
An expired reservation with a retained outcome cannot be reopened; an uncertain
outcome can still be reconciled to a final result during its outcome-retention
window. Retained outcomes count against the bounded reservation capacity. A
cleanup removes the row only after both the reservation and outcome windows
have elapsed, so a shorter outcome policy can never shorten idempotency; only
then can the same key be reserved again deterministically.

The SQLite state is anchored to a separate authenticated checkpoint file. Every
store operation verifies the canonical ledger digest in SQLite and the sidecar
before reading or changing data. This detects SQL-only coherent truncation and
replacement of the database with an older copy while the current checkpoint
remains. Checkpoint replacement is atomic and fail-closed; a crash between the
two filesystem commits can require restoring the last complete snapshot. There
is no external monotonic anchor in this local profile: an actor able to roll back
both files, or the entire volume, to the same older snapshot cannot be detected
here. That case requires infrastructure-controlled versioning or a trusted
external anchor. This proves only local ledger consistency, not that a recipient
read a message or that a provider delivered it.

`scripts/delivery_outcome_operator.py` is a protected offline interface for a
future trusted delivery adapter. The secret and request JSON are accepted from
bounded file descriptors (or the secret from a protected environment setting),
while stdout contains only status, allowlisted code, timestamps and Boolean
metadata. The command refuses to create a missing database or checkpoint and
contains no transport or network client. Both files are mandatory members of
the `single-instance` durable-storage inventory. A quiesced snapshot includes
both; restore tests reopen the pair and verify the outcome chain before use.
`SLPS_DELIVERY_DB_PATH` and `SLPS_DELIVERY_CHECKPOINT_PATH` must be distinct
paths below the durable root.

`ProviderNeutralDeliveryCoordinator` is the unwired handoff contract between
that ledger and a future injected adapter. It validates through the existing
strict message boundary, reserves before the adapter, invokes the adapter at
most once and immediately writes an allowlisted redacted outcome. Reservation
and the initial uncertain `dispatch_started` event are one SQLite transaction;
the marker is therefore durable before adapter invocation and receives the
longer outcome-retention window. Explicit rejection or cancellation proven to
occur before adapter invocation reconciles the marker to a final failure, while
acceptance reconciles it to final success. Malformed acknowledgement, timeout,
transport exception or cancellation after dispatch leave `dispatch_started`
unchanged because none can prove that the provider rejected the operation. The
marker may be reconciled only once to accepted or failed. A concurrent or later
replay never invokes the adapter and never rewrites the marker merely to rename
the uncertainty; it returns the retained event. Before reserving, the validated
request is canonically bound to the marker with length-framed SHA-256 over the
operation key, trimmed lowercase recipient, purpose, locale, canonical action URL
(lowercase host, no default port, approved path and decoded token) and canonical
UTC expiry. The ledger persists only an HMAC
digest of that binding. Reusing a key with any different bound value fails with
a redacted conflict and never projects the old outcome under the new purpose;
an identical replay, including equivalent recipient case and UTC expiry offset,
returns the retained outcome. A legacy reservation without this marker fails
closed without sending. If the final
outcome write fails, the caller returns the retained marker or an
already-committed matching final outcome but may not retry the adapter.
Reconciliation keys are deterministic SHA-256-derived values and are HMACed by
the ledger; no raw recipient, action token, operation key or provider reference
is returned.

The marker prevents a second send after the reservation window expires for as
long as outcome retention remains active. After both configured retention
windows have elapsed, the bounded ledger may reclaim the row; production policy
must therefore set outcome retention for the required replay horizon and use a
durable infrastructure anchor where a longer guarantee is required.
The coordinator refuses to initialize unless the ledger's read-only declared
marker retention is at least `MAX_ACTION_TTL_SECONDS + ceil(timeout) + 60`
seconds. `MAX_ACTION_TTL_SECONDS` is the same 86,400-second limit enforced when
validating action links; the extra minute is a conservative clock margin. Thus
an accepted configuration cannot reclaim the marker while even a maximum-TTL
action link remains valid. A short policy such as 300 seconds fails before any
reservation or adapter invocation.

This coordinator is still absent from `server.py` and has no provider SDK,
credentials, endpoint, network client, retry, fallback or background worker.
`python scripts/delivery_conformance.py` runs accepted, rejected, timeout,
exception and malformed-response probes against in-memory fake adapters while
socket creation is blocked. Passing it proves only the offline contract and
durable bookkeeping, not provider compatibility, deliverability, cost or
production readiness.

Every protected account request reloads the user, verification flags and session
version from SQLite. Mode changes invalidate the old authentication session.
The trial entitlement is shared by all approved users of the same company.
The archive filters by company **and owner** and now retains original media in
the protected local history foundation. Shared company case access,
plan/subscription benefits, invitation workflow,
external registry checks, production operator tooling and delivery remain
separate future work.
No names, prices, consultation counts or response-time promises are fixed here.

Account entry pages are `/register` and `/account`; unverified/anonymous account
users reaching `/app/` are returned to `/account`. The account screen localizes
its labels and errors in IT/DE/FR/EN. This does not imply that the entire existing
application has already been translated. Language preference is the only value
this screen saves in local storage; credentials and tokens are not persisted there.

Login attempts are limited before password hashing, by both IP scope and a
normalized email scope. Signing into another account does not reset a victim's
failed-attempt counter. Registration and recovery requests have their own limits.
Account login JSON is limited to 8 KB before parsing.

Validation uses synthetic local companies/media and mocked analysis only. The
master and model API implementation are unchanged. No paid call is needed for
these tests.

## Preflight della modalità account

`python scripts/preflight.py` riconosce il profilo da `SLPS_AUTH_MODE`.
In modalità `accounts` non richiede né usa `SLPS_PILOT_PASSWORD`,
`SLPS_PILOT_TENANT_ID` o `SLPS_PILOT_OWNER_ID`. Restano obbligatori un segreto
di sessione forte e la configurazione necessaria al motore di analisi.

Per il collaudo account, `SLPS_ACCOUNT_DB_PATH` deve essere impostato
esplicitamente su un percorso assoluto, esterno al codice e non temporaneo. Se
il file esiste, il controllo lo apre in sola lettura: verifica tabelle, colonne
necessarie alla revoca delle sessioni, permessi locali e presenza di almeno un
utente attivo con email, azienda e rappresentanza approvate. Non crea account,
non migra il database e non stampa percorsi, email o altri dati.

Il confine di consegna resta intenzionalmente scollegato da un trasporto. Il
registro idempotente locale e i percorsi ammessi impediscono duplicati e link
fuori contratto, ma non provano né eseguono un invio. Per questo
`SLPS_ACCOUNT_REGISTRATION_OPEN=true` è un blocco di staging: l'interfaccia
accetterebbe una richiesta, ma non potrebbe consegnare verifica email, recupero
password o inviti aziendali. Con registrazioni chiuse, un account verificato predisposto
in modo fidato consente il collaudo del login; l'assenza di consegna e la
verifica umana di azienda/rappresentanza restano avvisi espliciti.

Il preflight è solo locale: non prova che il volume sia davvero persistente,
né backup/ripristino, invio email, disponibilità del modello o credito API.
Questi punti restano cancelli separati prima dello staging aperto o del lancio.

Implementation references checked on 25 October 2026:
- https://werkzeug.palletsprojects.com/en/stable/utils/#module-werkzeug.security
- https://flask.palletsprojects.com/en/stable/web-security/
