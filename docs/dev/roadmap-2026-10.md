# Roadmap, late October 2026

What the continuous-speech tests of 20–21 October
([`eval/2026-10-continuous-ht/`](../../eval/2026-10-continuous-ht/README.md))
showed, and what this round of work does about it. Each item is its own
pull request; the order at the end is the order to merge them in.

## What the tests showed

- **Piece length was set by omni-stt's pause settings, not by the speaker.**
  A 700 ms pause rule and a 15 s cap (copied from the README's 7B example)
  on a presenter who only takes short breaths gave 12.7 s pieces, a first
  translated sound at 19.5 s, and a listener 18.2 s behind. Cutting at
  200 ms breaths with a 10 s cap and 1 s of minimum speech gave 3.8 s
  pieces, first audio at 8.4 s and a per-piece lag of 9.1 s.
- **Short pieces cost translation quality** (2.52 to 2.21 on the 0–3
  scale), and **context restores it**: the previous two source pieces and
  the last translation, sent as context only, gave 2.52–2.67 at the same
  or better lag.
- The companion apps' per-sentence lag metric under-reported the lag when
  the voice was backlogged; the corrected metric attributes audio by the
  speech service's byte offsets.
- Energy dips of 12 dB or more under the running level, starting within
  −100 to +250 ms of a word end, mark sentence ends well (AUC 0.92).
- Cloud voices spent about 16% of their output on leading and trailing
  silence.
- An `afftdn`-style denoiser in front of Omnilingual recovered about
  15 points of recognition on degraded audio; RNNoise hurt another
  recogniser.
- On real Haitian Creole speakers the open translators scored 34–36%
  against about 93% for a cloud LLM.

## The round

| # | Item | Where | Risk |
|---|---|---|---|
| 1 | Ship the tested cutting defaults (`ENDPOINT_MS=200`, `MAX_UTTERANCE_S=10`, `MIN_SPEECH_MS=1000`), fix the README examples, add the pause-statistics and simulated-settings trade-off table, and let the pause-cut window shorten progressively once a piece passes about 4 s (today it is capped at a third of the cap). Unit tests; `sim.py` re-run. | `services/omni-stt/` | Low: a defaults change, measured |
| 2 | Previous-pieces context in the stack's own translation path: the last two source pieces and the last translation, context only, reset on a language switch or after 30 s idle, bounded. Protocol field, server, tests, and a plain statement of which open model can use context (Hy-MT2 takes a chat prompt; MADLAD takes a tagged sentence and cannot). The plain path stays where a model has no context support. | `server/`, `docs/dev/protocol.md` | Medium: touches the translation hot path, off unless the client sends context |
| 3 | Partial text from omni-stt, behind a flag and off by default: re-transcribe the growing buffer about every 1.5 s, commit the text prefix that is stable across two passes, emit `partial` and `stable` messages. GPU cost 3–4×. Plus an optional energy-dip helper for choosing cut points. Design doc, prototype, tests; the full implementation may slip to the next round. | `services/omni-stt/` | Medium: new code path, flag off |
| 4 | Trim leading and trailing silence in `/v1/speak` voices (Coqui, MMS): measure first, keep about 60 ms of lead and 80 ms of tail, leave voiceless audio alone. | `services/omni-stt/voices.py` | Low |
| 5 | Publish the continuous-speech harness as eval tooling: real-time pacing, the corrected per-sentence lag metric, pause statistics, the cut simulator and token logging, runnable against the open stack and a generic endpoint. No audio committed; a note on fetching public-domain VOA clips with `yt-dlp`. | `eval/tools/` | Low: tooling only |
| 6 | Optional noise-reduction front-end for omni-stt input (an `afftdn` equivalent), off by default, documented with the measurements. | `services/omni-stt/` | Low: flag off |
| 7 | Low-resource translation research plan (document only): open-weight LLMs with context against Hy-MT2 for Haitian Creole, Lao and Khmer into English; the no-content-filter advantage. | `docs/dev/` | None |
| 8 | Cost formulas as a script, reading `site/data/list-prices.json`, so the site's cost page is reproducible from the command line. | `eval/tools/cost.py` | None |

## Rules for every item

- The repository is public: no private model names, buckets, hostnames,
  secrets or spend, and no transcripts of copyrighted clips.
  `bash site/check_private.sh` (after `python3 site/build.py`) passes on
  every branch; it also scans `docs/` and the eval READMEs.
- Feature branches and pull requests, squash-merged. Nothing is deployed
  from this round without a separate decision: the defaults in item 1
  reach the live service only with the next deploy.

## Merge order

1. Item 1 (defaults and progressive cut window): the measured win, and the
   base for the other `services/omni-stt/server.py` changes.
2. Items 5, 8 and 7: tooling and documents, no runtime change.
3. Item 4 (voice trim) and item 6 (denoiser, flag off).
4. Item 2 (context in the stack path).
5. Item 3 (partial text, flag off), rebased on item 1.
