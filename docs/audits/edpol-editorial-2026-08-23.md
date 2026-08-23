# ShadowBroker EdPol rewrite record — final local candidate

Date: 2026-08-23. Scope: public product copy in `frontend/src/app`,
`frontend/src/components`, and `frontend/src/i18n`. Authority inputs were the
EdPol editorial-language policy `1.1.0`
(`sha256:3d2c66102da7f3066b6609581067a838035d7813a73366587a1437f55d2bdb76`),
typography policy `1.1.1`, and AI-origin evidence policy. This review does not
infer authorship from style.

## Applied rewrite and composition changes

- The public Time Machine card now says exactly what is available: recorded
  snapshots are available in the local operator runtime. It does not imitate an
  available control or imply public access.
- Removed public AI-brief and market-correlation triggers, together with the
  market ticker. They were operator-side effects or out-of-scope visual noise,
  not a useful public map action.
- Public layer text no longer offers SAR, AI-pin or Shodan surfaces that belong
  to the local operator boundary. The retained map, source layers and news use
  direct, observable labels.
- Existing source-derived headlines, attribution, timestamps and runtime scores
  remain data, not editorial claims. Their source provenance remains governed by
  the product data boundary.

## Post-scan

The candidate scan considered 126 files, scanned 125, and skipped only
`frontend/src/app/favicon.ico` as an unsupported extension. It returned 407
`structural-candidate` matches, principally technical `unknown` placeholders
and decorative symbols in private/operator code. The scanner declares those
manual-context candidates; they are neither exact EdPol policy findings nor an
AI-origin determination. The exact-rule invocation returned no blocking policy
match.

Manual review of the changed public path found no unsupported superiority,
fabricated metric, vague call-to-action, or ungrounded availability claim. The
browser final state visibly uses `Data service degraded` when the source health
is not `ok`.

The current public deployment is older than this rewrite candidate and is not
claimed as EdPol-verified by this report.
