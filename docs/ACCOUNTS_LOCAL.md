# Local account foundation

The default `SLPS_AUTH_MODE=pilot` preserves existing pilot access. Opting into
`accounts` requires a strong session secret and a private persistent account DB;
it does not require the pilot password. Account mode always uses a single
company trial, even if legacy `SLPS_PILOT_PLAN=internal` or trial-total settings
are present. Registration remains closed unless explicitly enabled with
`SLPS_ACCOUNT_REGISTRATION_OPEN=true`. No public deployment is implied.

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
attempt. An expired key can be reserved again. This ledger does not mean that a
message was delivered and is not wired into `server.py`.

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
