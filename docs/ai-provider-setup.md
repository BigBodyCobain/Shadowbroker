# AI console: hosted and local models

Open the voice console, enable its two-step outbound opt-in, then choose **Change model**. Text commands and transcribed speech share the same command pipeline and existing permission/confirmation gates.

## Connect a model

1. Choose a provider, enter its API key if required, and save with **Connect & load models**.
2. Select a model from the live catalog, or enter the exact model ID supplied by your provider.
3. Save again with the model selected. A saved key alone does not mean the console is connected.
4. Type a question or command. Known map shortcuts run locally; other requests go through the configured AI command picker. Tool results remain visible in the transcript.

| Provider | Connection | Default text API |
| --- | --- | --- |
| OpenAI | OpenAI key | Responses |
| Claude / Anthropic | Anthropic key | Messages |
| Google Gemini | Gemini key | OpenAI-compatible chat |
| xAI / Grok | xAI key | Responses |
| OpenRouter | OpenRouter key | Chat Completions |
| Meta / Llama | OpenRouter key, catalog filtered to `meta-llama/` | Chat Completions |
| Ollama | `http://127.0.0.1:11434/v1`, optional gateway key | Chat Completions |
| LM Studio | `http://127.0.0.1:1234/v1`, optional gateway key | Chat Completions |
| Custom API | Your saved HTTP(S) API base and optional key | Chat Completions or Responses |

Catalogs come from the selected provider, including installed models on Ollama. There is no frozen list of supposedly current model IDs. Availability depends on your account and server; a model ID appearing in a catalog does not guarantee tool-following quality. Catalog errors are shown and manual IDs remain usable.

Local Llama models also work through Ollama, LM Studio, or a compatible server. Pull/load the model and enable that server's API first. The URL is resolved by the **Shadowbroker backend**: in Docker, loopback refers to the container; use the appropriate host address such as `host.docker.internal` where supported.

When changing a custom destination, supply a key explicitly or clear the old connection first. Keys are bound to their intended provider; OpenAI credentials are never borrowed for a custom host. Environment-managed credentials/settings take precedence and the setup UI reports that condition.

## Open articles automatically

Say or type **Open an article about port traffic**, **Show me the story about storm warnings**, or **Open article https://the-source-link**. The console resolves a matching article from its loaded news feed and opens the existing dossier automatically, including source details and corroborating stories. Articles without coordinates can also open. Known article phrases work without a language model; other wording can use the model's `open_article` tool.

Only existing feed articles are selectable; an invented or unrelated URL cannot trigger navigation. Publisher pages open from the dossier's explicit **GO TO ARTICLE** button, and only HTTP(S) links are permitted. A missing story produces a failure instead of selecting another item.

External agents use `show_article` through the existing authenticated command channel, with `query` or the exact source `url`. This retains the full-access requirement for remote display commands. Its result reports `queued: true, displayed: false`: the dashboard poll requests the preview, but the channel has no display receipt yet. The local AI console's `open_article` action uses the active dashboard directly.

AI turns also receive the existing bounded `sb.grounding.v1` map/selection snapshot, so the model has context for requests about the current area without screenshots or full telemetry dumps.

## Speak commands

Speech input is configured separately from the language model. Open **Speech input settings**, choose OpenAI, Gemini, or a local/OpenAI-compatible transcription API, save credentials to load its catalog, choose the speech model, and save. Speech input defaults to off. A local chat model alone is not a speech recognizer; it needs a separate transcription server exposing `/v1/audio/transcriptions`.

Use **Speak a command**, grant microphone permission, speak, then finish the recording. Each clip is limited to 30 seconds. The browser converts the clip into mono 16-bit PCM WAV at 16 kHz and sends it to the authenticated backend. The backend validates and rebuilds the WAV, then calls only the saved speech service. The returned transcript enters the same command path as typed text.

Escape, window blur, and cancellation stop microphone capture and suppress pending transcript submission. Commands already executed by the backend cannot be undone by cancelling a later response. Microphone access requires a secure browser context (HTTPS or localhost).

**Read replies aloud** uses installed device voices only. If no local voice is available, the console displays the reason and keeps text replies. Browser-direct cloud recognition remains prohibited.

Native realtime audio remains an advanced option for OpenAI, Gemini, and compatible realtime gateways. It requires a realtime model supported by the existing session protocol; configure its separate text model to use typed commands. Catalog discovery does not establish protocol compatibility with every future audio model.

## Privacy and limits

All hosted inference and transcription requests are brokered by the backend behind operator authentication, the two-step outbound opt-in, rate limits, and the daily budget gate. Provider keys stay server-side; browser responses contain only key-presence flags. Model lookup uses the saved connection and never sends a key in its URL or follows upstream redirects.

Speech recordings are processed in memory and are not written to disk. Audio reaches the selected transcription service; the resulting command text may then reach the selected language model. Provider retention policies still apply. Read [the outbound-data inventory](OUTBOUND_DATA.md) before enabling hosted services.

Spend figures are estimates, especially for newly released, local, and transcription models without a matching price entry. Configure provider-side billing limits as appropriate; the app's estimate is not a billing guarantee.

Configuration names include `VOICE_API_PROVIDER`, `VOICE_API_STYLE`, `VOICE_MODEL_STANDARD`, and `VOICE_STT_PROVIDER`, `VOICE_STT_MODEL`, `VOICE_STT_BASE_URL`, `VOICE_STT_API_KEY`. Existing configurations keep their legacy provider resolution until an explicit profile is selected.

## Protocol references

- [OpenAI model discovery](https://developers.openai.com/api/reference/resources/models/methods/list) and [speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text)
- [Anthropic model discovery](https://platform.claude.com/docs/en/api/models/list)
- [Gemini model discovery](https://ai.google.dev/api/models) and [audio input](https://ai.google.dev/gemini-api/docs/generate-content/audio)
- [xAI inference APIs](https://docs.x.ai/developers/rest-api-reference/inference/chat-completions)
- [OpenRouter model catalog](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
