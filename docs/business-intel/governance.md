# Governance

Shadowbroker can become powerful enough to create operational and legal risk if collection is not controlled. This document sets the default rules.

## Collection Rules

Allowed by default:

- Official public records and open-data portals.
- Licensed commercial data.
- First-party business data.
- Operator-created notes and observations.
- Public web pages where access, use, and retention comply with source terms.
- Consented recordings, transcripts, and media.

Requires review:

- Credentialed portals.
- Private or semi-private community groups.
- Personal profiles.
- Meeting audio/video.
- Bulk contact imports.
- Sources with unclear commercial-use rights.

Not allowed:

- Bypassing authentication, CAPTCHAs, rate limits, robots restrictions, or anti-automation systems.
- Joining groups under false pretenses.
- Covert recording of private conversations.
- Scraping private messages or private group content in violation of terms.
- Building personal dossiers unrelated to a legitimate business purpose.
- Publishing private dashboard data to the public internet.

## Data Minimization

Default policy:

- Store the signal, not every raw detail.
- Prefer parcel/address/project facts over personal facts.
- Hash or redact phone numbers, emails, and full names unless needed for an active business workflow.
- Expire raw media and raw notes unless promoted to evidence.
- Keep source links and timestamps for audit.

## Consent Labels

Every field observation should carry one collection mode:

| Mode | Meaning |
|---|---|
| `public_record` | Government or public-data source |
| `licensed` | Paid/licensed feed |
| `first_party` | CRM, estimate, invoice, route, or operator note |
| `public_observation` | Observation in a public place |
| `consented_recording` | Audio/video captured with required consent |
| `restricted_manual` | Manually entered from a restricted source; no automation |

## Retention Defaults

| Data | Default Retention |
|---|---|
| Raw dashcam rolling video | 24-72 hours |
| Bookmarked field video | 30-180 days depending on business need |
| Meeting recordings | Explicit project retention only |
| Transcripts/notes | Active deal plus audit period |
| Normalized permit/sale signals | Long-lived business history |
| Raw source exports | Short-lived unless license allows archival |
| API credentials | Secret manager or local encrypted store only |

## Access Rules

- Admin actions require `ADMIN_KEY` or stronger local auth.
- Family/child learning tools must be separated from business intel and raw sensitive data.
- TV view should be read-only and safe for casual visibility.
- Field node can upload observations but should not be able to dump all source data.
- External sharing requires export review.

## Audit Checklist

Before enabling a new source:

- Terms reviewed.
- Commercial use allowed or approved.
- Access method documented.
- Rate limit configured.
- Attribution added where needed.
- PII handling documented.
- Retention configured.
- Source owner assigned.
- Test import run on small sample.
