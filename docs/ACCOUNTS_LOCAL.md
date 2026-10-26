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
has no public endpoint; local tests simulate a real operator check through
`verify_company(company_id, representative_user_id)`.

No email delivery adapter exists yet. Registration and reset request responses
explicitly report `delivery_configured=false`; the reset request response is
identical for known and unknown email addresses and never claims a mail was sent.
The current local flow therefore cannot be presented as unattended production
onboarding or password recovery. Do not expose tokens in logs, URLs or chat.

Every protected account request reloads the user, verification flags and session
version from SQLite. Mode changes invalidate the old authentication session.
The trial entitlement is shared by all approved users of the same company.
The archive still filters by company **and owner**; shared company case access,
full original-media retention, plan/subscription benefits, invitation workflow,
real company-verification policy and delivery remain separate future work.
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

Implementation references checked on 25 October 2026:
- https://werkzeug.palletsprojects.com/en/stable/utils/#module-werkzeug.security
- https://flask.palletsprojects.com/en/stable/web-security/
