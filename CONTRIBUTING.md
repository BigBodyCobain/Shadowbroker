# Contributing to Shadowbroker

Thank you for taking the time to contribute. This document covers things specific to this project — for general open-source contribution etiquette, see the GitHub docs.

---

## Code contributions

1. Fork the repo on GitHub (`bigbodycobain/Shadowbroker`) or GitLab (`bigbodycobain/Shadowbroker` mirror).
2. Make your changes on a feature branch.
3. Run the local test suite:
   - Backend: `pytest backend/tests/`
   - Frontend: `cd frontend && npx vitest run`
4. Open a Pull Request against `main`.

CI runs on every PR. If CI fails, that's blocking — please push fixes rather than asking for it to be merged anyway.

---

## Reporting security issues

Do **not** file security issues as public GitHub issues. Email the maintainer or use a private security advisory on GitHub. Public disclosure of an exploitable vulnerability without prior coordination will be rejected from the project.

---

## Translation contributions

Shadowbroker supports UI localization (`frontend/src/i18n/`). Translation contributions are welcome but held to a stricter standard than most code changes, because translations can subtly reshape user perception in ways that are hard to spot during review. Read this section before submitting one.

### The neutrality requirement

**Translations must be technically faithful to the English source.** That means:

- Each `t('key')` entry should mean approximately the same thing in the target language as in English, modulo idiom.
- Technical terms with established meanings (e.g. "GPS jamming," "military flight," "Tor," "onion routing," "encryption") should be translated using the corresponding established technical term in the target language — **not** softened, rebranded, or politically reframed.
- The set of UI strings should be **the same** between languages. Don't omit features from one locale that are visible in another.

### What will get a translation PR rejected

Translation choices that align the project with the framing or terminology of state propaganda — from **any** country — will be rejected. This applies symmetrically:

| Country / source | Examples of substitutions we will reject |
|---|---|
| **PRC / CCP** | Calling Taiwan a "province" or "renegade province"; reframing protest layers as "riots"; using softened or euphemistic terms for surveillance, internment, or jamming when the source text is direct |
| **Russia** | Calling the Ukraine war a "special military operation"; relabeling occupied territories as Russian; softening sanctions/jamming/disinfo terminology |
| **United States / EU** | Reframing adversaries with editorial labels not in the source (e.g. inserting "regime" where the English says "government"); applying labels like "terrorist" or "rogue state" to entities the English source describes neutrally |
| **Israel / Palestine / any active conflict** | Substituting one side's preferred terminology when the source uses the other side's or a neutral term |
| **Any government** | Adding political slogans, omitting features that government finds inconvenient, or inserting terminology associated with a specific political faction |

The test is **"would a translator working strictly from the English source produce this rendering?"** If the answer requires assuming a political stance the source does not take, the substitution does not belong in the translation.

### How translation PRs are reviewed

Changes to `frontend/src/i18n/**` are owned by the maintainer (see `CODEOWNERS`) and require explicit approval. We will:

1. Diff the translation against the English source key-by-key.
2. Spot-check a sample of entries with a native speaker of the target language when possible.
3. Look for the patterns above.
4. Look for suspicious additions to the i18n infrastructure itself (e.g. a remote translation fetcher, telemetry on language choice) — the i18n layer is supposed to be 100% client-side static JSON.

A PR that adds a new language is harder to review than one that fixes typos in an existing language. For new languages, please be patient and expect a real review window. For typo fixes, please describe each change in the PR body so the reviewer can verify intent.

### What about adding a new language?

We welcome new languages. The mechanical setup is documented in the header comment of `frontend/src/i18n/index.ts`. Beyond that:

- We are more likely to merge a new language quickly if at least one reviewer in the maintainer's network speaks it.
- If you are the *only* speaker of the target language reading this repo, your translation is welcome but the merge timeline will be longer while a reviewer is found.
- Partial translations are fine — the system falls back to English for any missing key.

---

## Anything else

If you have a question that isn't a security report, opening a GitHub Discussion or a draft PR with a question in the body is the fastest way to get a response. Direct emails are read but not always replied to promptly.
