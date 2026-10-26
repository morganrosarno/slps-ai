# Versioned Swiss primary-source registry

`data/sources.ch.v1.json` contains seven bounded propositions from primary Fedlex, SECO,
CFSL and Suva sources retrieved on **26 October 2026**. It is an initial general
registry, not a complete catalogue of sector rules and not professional approval
of an analysis. It contains short paraphrases, not copied manuals or the private
method. The approved master and adapter instructions are unchanged.

Set `SLPS_SOURCES_PATH` explicitly to this file's absolute deployment path to
select it. No default, remote retrieval or AI call is introduced. Runtime and
`scripts/preflight.py` share the same offline validator. An absent setting still
means no verified references; malformed configured data fails before provider
submission. Unknown model `source_id` values are removed with a visible limitation.

The envelope has `schema_version: 1`, `registry_version`, `jurisdiction: CH` and
`sources`. Each entry includes a stable ID, official HTTPS URL, publisher,
locator, scope, limitations, document version and retrieval date (`verified_at`).
`verification_scope` makes clear what was actually checked. Retrieval in 2026
does not turn the SECO commentary dated December 2015 into a 2026 revision.

Classification describes the **registered proposition**, never automatically the
photographed situation:

| Value | Meaning |
| --- | --- |
| `obligation` | A bounded obligation described in legislation or authoritative guidance. `source_kind` identifies which; scope must still be checked for the company/case. |
| `recommendation` | Technical or application guidance; not automatically a binding statutory requirement. |
| `hypothesis` | Explicit application inference requiring confirmation; permitted only with `application_hypothesis`, never a regulator's verified conclusion. |

The initial file contains obligations and recommendations. No photographic
hypotheses are pre-filled: those depend on actual evidence and context.
Unversioned owner-maintained lists remain supported, but classification-like
extra fields are discarded and cannot acquire the versioned registry's status.
The response exposes only provenance metadata, never registry excerpt text.

## Verification limits and maintenance

- CFSL 6508 uses the official PDF marked **state 23 October 2025**, edition
  **11.25**. It explains the conditions for specialist involvement; it does not
  say every SME must always hire a specialist.
- The SECO general page reports the health-protection obligation. The separate
  OLL 3 article 2 entry paraphrases the **commentary**, classified as guidance.
- Suva's PPE guidance and CFSL's hazard examples do not establish that a specific
  measure or hazard is proven by a photograph.
- The canonical Fedlex OPI text was read through the browser on 26 October
  2026 after an initial text-only retrieval failed. Fedlex marked the text in
  force and displayed version **1 May 2018**. The two law entries cover only
  article 3 paragraphs 1, 2 and 3 and article 5 paragraphs 1 and 2. Article 3
  paragraph 1bis is not summarized. Applicability under articles 1 and 2 and the
  actual risk/protection conditions must be checked; the photograph does not
  itself establish a breach. The observation date is not a new law revision.
- Before professional release, verify case applicability and any subsequent changes in consolidated law
  with a qualified reviewer. Recheck sources when an authority publishes changes;
  increment `registry_version` and retain the old revision in Git. No automatic
  legal freshness or customer-feedback learning is claimed.

Tests cover legacy migration, official-host checks, malformed/oversized data,
duplicate IDs, future dates, classification boundaries, report metadata and
invented-reference removal without network calls.
