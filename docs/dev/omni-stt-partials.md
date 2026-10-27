# omni-stt: partial text while a piece is still being spoken

Status: a prototype behind a flag that is off by default (`STT_PARTIALS=0`).
The stability rule and the scheduler are implemented and tested without a
model (`services/omni-stt/partials.py`, `tests/test_omni_stt_partials.py`);
the server hook runs the extra passes through the same batcher as the
finals, with no priority of its own yet. Nothing here has run on a GPU;
the cost figures below are a model of the work, and the section at the end
says what a GPU run should measure before the flag is turned on anywhere.
A second, unrelated helper lives beside it: energy dips as a secondary cue
for where a piece should be cut (`dips.py`, last section).

For Khmer and Lao there is now a cheaper route than decoding the growing
buffer again: the CTC 3B streaming track (`services/omni-stt/ctc_stream.py`,
`?stream=ctc`). It sends `partial` (the revisable tail) and `committed` (text
that is never revised) from chunked CTC passes, and runs as a separate
service. Measurements: [eval/2026-10-ctc-stream](../../eval/2026-10-ctc-stream/README.md).

## Why

omni-stt sends text only when a piece ends (`inputTranscript`, after the
`language` message). A listener therefore waits the whole piece plus its
recognition: with the default endpointing a piece is up to `MAX_UTTERANCE_S`
long, and continuous speech is cut by the cap, so captions arrive in
several-second blocks. Commercial recognisers show text as it is said; the
companion apps are built around that, and hold the other recogniser's
sentences until omni-stt's language message arrives.

Omnilingual's LLM-decoder cards have no streaming mode: the decoder prefills
the whole utterance's audio frames and then generates the text. The only way
to show text early is to decode the growing buffer again, which costs the
GPU several times what one final decode costs. Hence the flag, and the rule
that nothing about the final text may change.

## Message flow

With the flag on, per `/listen` connection, between the Segmenter's outputs:

```
audio in ──> Segmenter buffer grows (the piece being spoken)
              every STT_PARTIAL_MS of new audio, a PASS over a copy of the buffer:
                [language ID on the copy, rooms with several languages]
                recognition on the copy                       (the Batcher, "asr")
              → {"type":"partial", "text": <the whole hypothesis>, ...}
              → {"type":"stable",  "text": <committed prefix>, "delta": <new words>, ...}   when it grew
piece ends (ENDPOINT_MS of quiet, a forced cut, a flush)
              → {"type":"language", ...}            as today
              → {"type":"inputTranscript", ...}     as today: the one authoritative text
```

Fields (`services/omni-stt/README.md`, Protocol): `text`; `lang` and
`confidence` from the pass's own language ID (1.0 in a one-language room);
`start_ms`, the piece's start, which is also what its final carries (the
Segmenter fixes the buffer's start once speech is seen and the final is taken
from the same index); `end_ms`, how far into the stream the pass heard, at
most the final's. `stable` adds `delta`, the words this message committed, so
a client can append rather than diff.

The final goes out by the unchanged path: the Segmenter's utterance, the
connection's queue, `recognise`, the Batcher. Partial passes read a copy of
the buffer and never touch the Segmenter, so the final text is exactly what
it is with the flag off. Within a connection a `partial`/`stable` of a piece
always precedes that piece's `language`: when the piece ends, the pass in
flight (if any) is cancelled before the final is queued, and a cancelled
pass's result is dropped, not sent. The Batcher skips a job whose future was
cancelled while it waited, so a dropped pass costs nothing more.

## The stability rule

A hypothesis is split into whitespace-separated words. After each pass:

1. The leading words that the previous pass and this one agree on are the
   stable candidates (a prefix stable across two consecutive passes).
2. The committed prefix never shrinks. It grows to the agreed prefix only
   while the current hypothesis still starts with the committed words; once
   a pass rewrites a committed word, nothing more is committed for that piece
   (the client keeps what it has, and the final replaces it all).
3. Only whole words: a word still being said ("mou", then "moun") is never
   committed, and a word with a different trailing mark ("moun" vs "moun,")
   is a different word.
4. Passes with different language guesses never agree with each other.

So `stable` is monotonic: each one's `text` is the previous one's plus
`delta`. It can be wrong (two passes can agree on a wrong word), which is
why the final replaces it rather than extending it.

Limits: for scripts written without spaces (Khmer, Lao, Chinese, Japanese) a
"word" is a run between spaces, often a whole phrase, so commits are rare and
late there; a character-level rule with a safety margin would be the next
step. The two-pass rule is the simplest member of the LocalAgreement family
the stack's simultaneous mode uses (`docs/dev/architecture.md`); a longer
agreement window commits later but is wrong less often.

## A forced cut, a flush, a disconnect

- **Forced cut** (`MAX_UTTERANCE_S`, or a `CUT_ENDPOINT_MS` pause near the
  cap): the Segmenter takes the audio up to the cut as the piece and keeps
  the rest as the start of the next. The passes so far covered the whole
  buffer, including audio after the cut, so a `stable` may hold words the
  final of this piece will not contain; they come back in the next piece's
  passes and final. The client rule below (the final replaces the piece)
  handles it; the next piece's first pass is due as soon as its leftover is
  an interval long, and its `start_ms` is the cut's.
- **Flush** (`{"type":"flush"}`, end of a file, push-to-talk release): the
  pass in flight is cancelled, the piece's final follows, then `flushed`.
- **Disconnect**: the pass in flight is cancelled with everything else.
- A new piece starts with an empty tracker and an empty schedule.

## Cost model

A piece of length L seconds with a pass every I seconds of new audio has
n = floor(L / I) passes (the first when the buffer is I long; the buffer
includes the half-second pre-roll). Pass k decodes k·I seconds, so the audio
decoded for partials is I·n(n+1)/2 on top of the final's L:

| piece L | passes (I = 1.5 s) | audio decoded, partials | total / final-only |
|---|---|---|---|
| 3 s | 2 | 4.5 s | 2.5x |
| 6 s | 4 | 15 s | 3.5x |
| 10 s | 6 | 31.5 s | 4.2x |
| 15 s | 10 | 82.5 s | 6.5x |

GPU time is not quite proportional to audio: a pass has a fixed cost (the
prefill is one batched call; the generation loop is one decoder step per
text token, ~10-18 characters a second of speech) and short passes are
dominated by it, so expect roughly 3-4x the GPU time per piece at the
default 6-10 s cap and a 1.5 s interval, and more with longer pieces. A
longer interval cuts it fast (I = 3 s on a 6 s piece: 2 passes, 1.5x); the
cost is quadratic in the pass count. Two ways to make it cheaper later,
neither done: pass over a trailing window (the last few seconds plus a
little context) rather than the whole buffer, which breaks the clean
"prefix of the whole hypothesis" rule and needs its own alignment; or a
CTC card, which can decode a frame at a time but is less accurate.

The passes also take GPU time from finals, which is the latency the
companion apps care about most: see Batching.

## Batching

Partial passes go through the one `Batcher` (`server.py`), in the same `asr`
queue as finals, each with the pass's own language code. A pass is a normal
job: it batches with whatever is waiting (omni_batch's aligned decode makes
mixed lengths cheap), is retried alone if its batch fails, and is dropped
unrun if cancelled while it waits.

Finals must not wait behind partials. The prototype's rule is the scheduler's
`busy` check: a pass is **skipped** while anything is waiting in the
Batcher's queues (a final from any connection, or another connection's
pass), and asked for again on the next audio block, so it runs as soon as
the queue is empty. With one connection the queue is empty whenever the GPU
is idle, so passes run as often as the interval says; under load the finals
take the GPU and partials thin out on their own. One pass per connection is
in flight at a time.

What remains, in the Batcher rather than here:

- a third kind, `asr_partial`, taken only when `asr` is empty, with a cap on
  the partial items per batch, so that a pass already queued when a final
  arrives does not lengthen the final's batch;
- a budget: skip passes when the Batcher's busy share over the last minute
  (it already logs it) is above a threshold, so a busy instance degrades to
  finals-only instead of to late finals;
- counting partial GPU time apart from finals in the Batcher's log line.

## Language ID

In a one-language room there is nothing to decide: the pass uses that
language, `confidence` 1.0. With several languages the final's language is
only known when the piece ends (VoxLingua107 classifies the whole clip), so
each pass runs language ID on the audio so far first (the Batcher's `lid`
kind; ~50 ms and batched) and decodes with that guess. The guess on the
first 1.5 s can differ from the final's, and from the next pass's. Rules:

- a pass whose language is not in `?transcribe` sends nothing (as a final
  of that language sends only its `language` message);
- partials of different languages never agree, so a flip stops commits
  until the final; the final `language` message is the authoritative one;
- the client must not release what it holds on a partial's `lang`: only
  the `language` message says which recogniser a piece belongs to.

An alternative, not done: send a `language` message early (after the first
pass) when the confidence is high, and only a correction with the final.
It would let the companion apps release held captions sooner, which is a
latency win of its own, but a wrong early language is costly for them and
the language ID's accuracy on 1.5 s is unmeasured.

## What the companion apps should display

- Treat `partial` as the whole current text of the piece (`start_ms` keys
  the piece); show it in the "still being said" style, replacing the
  previous `partial` of the same piece.
- Treat `stable` as the settled part: show `text` in the settled style and
  the rest of the latest `partial` after it in the tentative style. Appending
  `delta` is equivalent as long as the client holds nothing from another
  piece under the same key.
- On `inputTranscript` for that `start_ms`, replace the piece's partial and
  stable text with the final text, whatever they said. The final is what
  gets translated and spoken; do not translate or speak partials unless the
  translation path is itself built for revisions (the stack's simultaneous
  mode is; a sentence-at-a-time translator is not).
- A `language` message still arrives only at the end of the piece: anything
  held until the language is known stays held. Partials carry a provisional
  `lang` for display only.
- Expect `end_ms` to lag the stream by up to an interval plus a pass's
  decode time, and no partials at all for pieces shorter than the interval.
- Key everything by `start_ms`: when the GPU is behind, the next piece's
  first `partial` can arrive before the previous piece's `language` and
  `inputTranscript`. Within one piece the order is always partials and
  stables, then `language`, then `inputTranscript`.

## Energy dips: `dips.py`

An unrelated helper, kept beside the service because the same companion apps
measured it and it may feed the forced cut later. `find_dips(audio)` on 16
kHz float audio frames it in 20 ms, takes each frame's level in dB and a
running level, the RMS of the trailing 1.5 s before the frame (so a quiet
speaker's gaps count as a loud one's, and a long silence stops counting once
the level has sunk to it), and returns runs of at least 60 ms that sit 12 dB
or more under the running level, each as start, end and depth.
`sentence_end_candidates(dips, word_ends, lead_ms=-100, lag_ms=250)` pairs
word ends with a dip starting from 100 ms before to 250 ms after them.

The companion apps measured, on their own test with their recogniser's word
timings, an AUC of 0.92 for telling sentence ends from other word ends with
this rule (a dip of 12 dB or more starting within -100..+250 ms of the word
end). That is their measurement from their implementation (an asymmetric
tracking level on 10 ms frames); it is cited, not reproduced here, and this
implementation differs in the running level and the frame size.

How it could feed `pause_cut` (nothing changed there now): `pause_cut`
ranks runs of low VAD probability in the last `CUT_WINDOW_S` by length, then
mean probability, then recency. A dip could (a) break ties or re-rank runs
of similar length, a deep dip over a shallow one; (b) replace the fallback
when the VAD finds no run at all, where today the quietest 20 ms of the last
2 s is used and often lands inside a word, by preferring the deepest dip of
60 ms or more; (c) with partial text and a recogniser that gives word
timings, pick the dip nearest a word end, which is what the apps' AUC is
about. Omnilingual gives no word timings, so (c) waits on another
recogniser or on alignment. Any of these should be scored with
`eval/2026-10-pause-cut` before it ships.

## What a GPU run should measure next

With the flag on, one connection, the continuous-speech clips of
`eval/2026-10-pause-cut` streamed at real time:

1. That every final is byte-for-byte the flag-off final (same card, same
   settings): the one invariant.
2. GPU time per piece with and without partials (the Batcher's busy share),
   at `STT_PARTIAL_MS` 1000, 1500 and 2500, and the pass count per piece.
3. Final-transcript delay (speech end to `inputTranscript`) with and without
   partials, one stream and four: how much the passes delay finals.
4. Time to first `partial` and to first `stable` after speech starts, and
   how far `stable` lags the speech (end_ms minus the stream time).
5. How often a `stable` disagrees with the final (word error of the stable
   text against the final's prefix), per language, and after forced cuts.
6. Language ID agreement between the first pass and the final, per
   language pair, to decide whether an early `language` message is safe.
