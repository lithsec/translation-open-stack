# Continuous-speech harness

Tools for measuring a live speech-translation service on continuous speech:
how long the listener is kept waiting, what decides it, and how good the
output is. They are the scripts behind `../2026-10-continuous-ht` and
`../2026-10-continuous-azure`, made general: one streamer that writes an event
log, and analysis scripts that read it, so the same metrics come out whatever
the service is.

| Tool | What it does | Needs |
|---|---|---|
| `pace.py` | Streams a 16 kHz WAV at real time (100 ms chunks, as a microphone) to the open stack, to omni-stt, or to your own service through a small adapter class, and writes the event log | numpy, websockets |
| `lag.py` | First audio, per-piece lag (p50/p90), final lag, piece count and lengths, backlog, token totals, from an event log | numpy |
| `pauses.py` | Silero VAD pause statistics of a clip: gaps per minute at several thresholds, speech between gaps; saves the probabilities | numpy; torch for the VAD |
| `cutsim.py` | Where omni-stt's `Segmenter` would cut the clip under several pause settings, from the saved probabilities (exec's omni-stt's own source, no models) | numpy |
| `dips.py` | Energy dips in the clip (short drops under the running loud level) and how close given cut times are to one | numpy |
| `judge.py` | Gemini grading of the translation 0–3 per reference sentence, critical errors, and the transcript's CER; prompts in `prompts/` | gcloud or an API key |
| `cost.py` | Cost of a run from its usage (see its docstring) | |

Python 3.12+, run with `python3 -I` from anywhere (the scripts know their
own folder). No audio, transcripts or run logs are committed; only metrics.

## A clip

Voice of America programmes are works of the US government and in the public
domain, and VOA broadcasts in the languages commercial speech services serve
least, which is why the October rounds used them. Fetch audio with
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and cut and convert it with ffmpeg:

```bash
yt-dlp -f bestaudio -x --audio-format wav -o full.%(ext)s "<VOA programme URL>"
ffmpeg -i full.wav -ss 00:01:00 -t 00:05:00 -ar 16000 -ac 1 -sample_fmt s16 clip.wav
```

Choose a window with one speaker and no music (`prompts/survey.txt` asks a
Gemini model for a segment map of the first minutes, if you would rather not
listen through). Keep the audio out of the repository: work in a folder
outside it, and commit only the metrics, as the eval folders do (never a
clip, a transcript, a reference or a run log).

References for grading: a transcript and a translation of the clip, split
into sentences. `prompts/reference.txt` and `prompts/translate.txt` make them
with a Gemini model (send the clip's audio with the first); nobody checks them
by hand, so they are approximate and the grades rank runs against each other.

## Against the open stack

```bash
docker compose up -d --build                     # README.md: the stack on your GPU
STACK_TOKEN=... python3 -I eval/tools/pace.py --service stack --url ws://localhost:8790 \
    --lang en --src es clip.wav --out run.jsonl --save-audio out.wav
python3 -I eval/tools/lag.py run.jsonl --wav clip.wav --pieces --text out.txt --source-text src.txt
```

The stack takes 24 kHz audio; `pace.py` resamples each chunk to the rate the
hello announces. Other connection options (`docs/dev/protocol.md`) go through
`--option`: `--option stream=1`, `--option room=main`, `--option cands=en,es`.
The stack reports no utterance times, so `lag.py` gives per-piece lag from each
transcript's arrival (`input_to_audio_*`) rather than from the speech itself,
and says so.

## Against omni-stt

```bash
STT_OPEN=1 STT_MODELS=/tmp/stt-models python3 services/omni-stt/server.py     # or the Cloud Run URL
STT_TOKEN=... python3 -I eval/tools/pace.py --service omni --url ws://localhost:8080 \
    --langs ht,en --option transcribe=ht clip.wav --out run.jsonl
python3 -I eval/tools/lag.py run.jsonl --wav clip.wav --pieces
```

omni-stt reports `start_ms`/`end_ms` per utterance; `pace.py` puts them on the
clip's timeline (it subtracts the pre-roll silence it sent first). It is a
recogniser only, so the log has pieces and no audio: `lag.py` reports the
pieces, their lengths and the transcript delay; translation and voice come
from whatever you put after it (next section).

## Against your own service

Subclass `pace.Adapter` in a module of your own and pass it as
`--service path/to/my_adapter.py:MyAdapter`:

```python
import json
import pace

class MyAdapter(pace.Adapter):
    name = "mine"
    rate = 16000                     # what your service wants; pace.py resamples to it
    token_env = "MY_TOKEN"           # --token or this variable; sent as a bearer header

    async def connect(self):
        await self.open(f"{self.url}/stream?lang={self.options.get('lang', 'es')}")
        hello = json.loads(await self.ws.recv())
        self.log("hello", rate=hello["rate"])
        self.rate = hello["rate"]

    async def on_message(self, msg):
        if isinstance(msg, bytes):                      # translated audio, PCM16 at self.rate
            self.log.audio(msg, self.rate, piece=self.current_piece)
            return
        d = json.loads(msg)
        if d["type"] == "heard":
            self.log("input", text=d["text"], start_ms=self.clip_ms(d["start_ms"]), end_ms=self.clip_ms(d["end_ms"]))
        elif d["type"] == "translated":
            self.log("done", text=d["text"], piece=d["id"])
            self.log_usage(d.get("usage"), status=200, ms=d.get("ms"))
        elif d["type"] == "sentence":                   # the service marks where a piece's audio starts
            self.current_piece = d["id"]
            self.log("marker", label="start", piece=d["id"], offset=self.log.audio_samples)
```

`connect`, `send_chunk`, `on_message`, `finish` and `close` are the whole
interface; the base class gives a `websockets` connection (`self.open`,
`self.ws`), a receive loop over it, `self.log` (the event log), `clip_ms` (a
time the service counts from its first sample, onto the clip's timeline) and
`log_usage` (token counts in the usual fields). A service that is not a
WebSocket overrides `receive` too. The two built-in adapters, `StackAdapter`
and `OmniAdapter` in `pace.py`, are the worked examples.

Chunks are sent when they end: chunk k at `(k + 1) × 100 ms` after the clip
starts, with a second of silence first (`--preroll`) and silence after the
clip until nothing has arrived for 10 s (`--quiet-end`, at most `--tail-max`).
A `pace` event every 10 s and the `end` event carry the send lateness, so a
run on a busy machine shows itself.

## Event log

One JSON object per line, written by `pace.py` and read by `lag.py`,
`dips.py` and `cost.py`. Every line has:

- `t`: milliseconds on the clip's timeline, from a monotonic clock: 0 when the
  first chunk of the clip starts to be sent, so chunk k has been delivered at
  `(k + 1) × 100`. Events before the clip (the hello, the pre-roll) are negative.
- `kind`: one of the kinds below. Unknown kinds are ignored by the analysis.

| kind | fields | meaning |
|---|---|---|
| `start` | `service`, `rate`, `clip_s`, `chunk_ms`, `preroll_ms` | the clip begins |
| `hello` | whatever the service said first (`rate`, `mode`, ...) | |
| `partial` | `text` | an interim transcript, replaced by the next |
| `input` | `text`, optional `lang`, `confidence`, `start_ms`, `end_ms`, `piece` | what the service heard, in the source language: one per **piece**. `start_ms`/`end_ms` are the piece's speech on the clip's timeline, when the service reports them; `piece` is the service's own id for it, the same one its markers use (without ids, markers are matched to inputs in order) |
| `lang` | `lang`, optional `confidence`, `start_ms`, `end_ms` | the language identified |
| `translation` | `text`, optional `piece` | a delta of translated text: append it |
| `done` | `text`, optional `piece` | a piece's translation is complete (the whole text) |
| `audio` | `samples`, `rate`, `offset`, optional `on`, `off`, `piece`, `bytes` | a chunk of translated audio. `offset` = output samples received before it (the chunk's place in the output stream); `on`/`off` = the first and the end of the last voiced 10 ms frame inside it (RMS over 150, about −47 dBFS), absent when it is silent |
| `marker` | `label` (`start` or `end`), `piece`, `offset`, optional `bytes` | the service's own mark of where a piece's audio starts or ends in the output stream, at `offset` samples |
| `usage` | `prompt`, `cached`, `completion`, `reasoning`, optional `status`, `ms`, `totalMs`, `stream` | token counts of one translation call, as the service reported them (the fields of the October run logs) |
| `pace` | `sent_ms`, `late_ms` | the streamer's own lateness, every 10 s |
| `error` | `detail` | |
| `flushed`, `other` | | omni-stt's flush acknowledgement; any JSON not understood (`data`) |
| `end` | `sent_ms`, `late_ms_p50`, `late_ms_max` | the stream ended |

Tokens never appear in the log; the texts do, so a log is as private as the
clip it was made from, and is not committed.

## Metrics (`lag.py`)

The definitions match `../2026-10-continuous-ht/README.md`:

- **First audio**: speech start to the first voiced sound of the translation,
  as played.
- **Per-piece lag**: for each piece, from the moment its speech *starts* to
  the first voiced sound of its translation as played, after any earlier
  translation still playing. Median and 90th percentile. Also from the
  piece's speech *end* (`piece_end_lag_*`), and from the transcript's arrival
  (`input_to_audio_*`) when the service reports no times.
- **Final lag**: the speaker's last word to the end of the last translated
  audio, as played.
- **Pieces**: how many, their lengths (seconds, from the times) and sizes
  (words; `--units chars` for Japanese, Chinese, Korean), how many got no
  audio or no translation.
- **Backlog**: the longest an arriving chunk waited behind audio still
  playing, overall and per minute; `voiced_output_s`.
- **Usage**: calls, non-200 answers, token totals and call time, when the log
  has `usage` events.

"As played" models a player that plays chunks in arrival order, each when it
arrives or when the previous one ends, with no pacing of its own.

**Which audio is which piece's.** The per-piece figures depend on it, and the
output says which rule was used (`attribution`):

- `offsets`: the log carries the service's markers (`marker` events, or
  `audio` events tagged with a `piece`), so a chunk belongs to the piece whose
  span of the output stream holds its `offset`. A backlogged voice is then
  counted correctly: a piece's first sound is its own, however late it plays.
- `arrival`: no markers, so a chunk belongs to the latest piece whose `input`
  arrived before it. When the voice is backlogged, the tail of the previous
  piece arrives after the next piece's transcript and is taken for that
  piece's start, and per-piece lag is **under-reported**. On one Spanish run
  measured both ways it gave 2.1 s where offsets give 5.3 s
  (`../2026-10-continuous-azure`). First audio and final lag do not depend on
  attribution. The October Haitian Creole figures (`../2026-10-continuous-ht`)
  were measured by arrival.

So when you write an adapter, log markers if the service gives any way of
telling which audio belongs to which sentence (a sentence-start message, a
byte count, an id on the audio frames). `tests/test_eval_tools.py` holds a
hand-built log where the two rules disagree.

Speech start and end come from the clip (`--wav`: the first and last 20 ms
frame over a fifth of the 90th-percentile RMS) or `--speech-start`/`--speech-end`.

## Pauses and cuts

```bash
python3 -I eval/tools/pauses.py clip.wav --probs clip.npz --out pauses.json     # torch: runs Silero
python3 -I eval/tools/cutsim.py --probs clip.npz --out cuts.json                # no torch
python3 -I eval/tools/cutsim.py --probs clip.npz --set "breath=endpoint_ms:200,max_s:10,min_speech_ms:1000"
python3 -I eval/tools/dips.py clip.wav --near run.jsonl
```

`pauses.py` runs Silero VAD as omni-stt does (the same pinned revision, 512-
sample windows, streamed in order) and saves the probabilities, then counts
gaps (runs of windows under the threshold) and the speech between gaps of at
least k ms, which is how long a piece gets when the cutter waits for such a
gap. Silero needs torch; with `--probs` alone it reuses a saved file and needs
only numpy.

`cutsim.py` drives omni-stt's own `Segmenter` (the endpointing section of
`services/omni-stt/server.py` is exec'd; nothing is imported) over the clip's
96 ms blocks and the saved probabilities and reports, per setting, the
pieces, their lengths, cuts at the cap, cuts with no VAD gap at them, and,
with `--ref-ends`, cuts within a second of a reference sentence end. It shows
only where the pieces would be cut: no recognition, network or GPU. The
module constants the segmenter reads are taken from `server.py`'s own
assignments (`CONSTANTS` in `cutsim.py`); that list must track `server.py`'s
settings when they change, and a missing name is reported.

`dips.py` is the cutter-without-a-VAD view: energy drops under the running
loud level, how many per minute, and whether given times (an event log's
piece ends, or a list) sit within 150 ms of one, against random times.

## Grading

```bash
python3 -I eval/tools/lag.py run.jsonl --text out.txt --source-text src.txt
GOOGLE_CLOUD_PROJECT=<your project> python3 -I eval/tools/judge.py --pair "Spanish -> English" \
    --refs ref_en.json --output out.txt --src-ref ref_es.txt --src-hyp src.txt --out judge.json
```

`judge.py` fills `prompts/judge.txt` with the numbered reference sentences
and the whole live output and asks a Gemini model (default `gemini-2.5-pro`,
temperature 0) for a 0–3 score per sentence with critical errors flagged,
then prints the mean, the percentage of the maximum, and the counts. On
Vertex AI the project comes from `GOOGLE_CLOUD_PROJECT` and the token from
`gcloud auth print-access-token`, as in `../README.md`; with `GEMINI_API_KEY`
set instead it calls the Gemini API. `--src-ref`/`--src-hyp` add the
recogniser's CER (NFKC, lowercase, punctuation dropped). One judge grading
against model-made references: differences of a few tenths on the 0–3 scale
are within run-to-run noise.

## Tests

`tests/test_eval_tools.py` (CI's unit-test step) covers the chunking,
resampling and voiced-frame marking, the pacer's timing with a fake clock and
the real one, a full `pace.run` against a fake adapter, `lag.py` on the
hand-built backlog log (offsets give the corrected answer, arrival
under-reports), `cutsim.py` against omni-stt's real source, and the pause
and dip statistics on synthetic audio.
