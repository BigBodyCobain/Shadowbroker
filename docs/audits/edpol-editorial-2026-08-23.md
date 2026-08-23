# ShadowBroker EdPol rewrite record

Date: 2026-08-23. Policy inputs: EdPol language policy `1.1.0` and typography
policy `1.1.1`, retrieved as public authority inputs for this review.

## Applied rewrite

- Replaced generic or simulated-operational copy: `GLOBAL THREAT INTERCEPT`,
  `THREAT INTERCEPT`, `TOP SECRET // SI-TK // NOFORN`, `FLIR`, and the made-up
  `OPTIC VIS` metric string.
- Reframed the product subtitle in English, Farsi, French and Simplified
  Chinese as the factual scope: map layers and intelligence feeds.
- Replaced the faux reticle, scanlines and CRT vignette with a named page
  identity and a source-derived service-status surface.
- Rewrote title and description metadata to describe an OSINT map, source-aware
  data layers and local operator controls without unsupported superiority claims.

## Boundary and residual risk

Feed items, source titles, risk scores and upstream labels remain source/runtime
data rather than editorially rewritten product copy. Their accuracy, attribution
and licensing must continue to be enforced by the existing product data
boundaries. The post-change source scan is recorded with the final local
verification evidence; no claim is made about copy in the currently deployed,
older public runtime.

## Deterministic post-scan

The exact-rule scan used language-policy `1.1.0`
(`3d2c66102da7f3066b6609581067a838035d7813a73366587a1437f55d2bdb76`)
over eight user-facing English source files. It found no `policy-exact`
matches. It emitted 102 `structural-candidate` source matches for `unknown`
and decorative emoji, all marked manual-context review by the scanner rather
than treated as an authorship or publication verdict. The verified local
unavailable-service browser state contains neither an `unknown` placeholder
nor the removed fabricated metric labels.
