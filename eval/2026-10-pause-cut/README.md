# omni-stt's forced cut at a pause (October 2026)

This measures a speaker who never pauses long enough to end a turn. omni-stt
cuts such a speaker at `MAX_UTTERANCE_S`. Live Translation runs with
`ENDPOINT_MS` 700 and `MAX_UTTERANCE_S` 15. The old cut went at the quietest
20 ms of the last 2 s, which is often inside a word. A user then heard a 14 s
sentence followed by a "3 words, 2.2 s" leftover.

The new cut (`services/omni-stt/server.py`, `pause_cut`; see the README there,
Endpointing):

- It looks for the best pause Silero heard in the last 3.5 s: the longest run
  of 32 ms windows under 0.5 lasting 96 ms or more.
- It cuts at the quietest 20 ms of that pause.
- Within the last 3.5 s, a 200 ms pause cuts at once.
- The audio after the cut starts the next utterance.

## Method

`make_continuous.py` builds the clips from the real-voice clips
(`../2026-10-real-voices`):

- CMU Haitian Creole, and FLEURS English, Khmer and Lao: 30 sentences each.
- Each sentence is levelled to RMS 2000.
- The sentences are joined with 100–250 ms gaps over a faint noise floor.

No gap is long enough to end a turn at 700 ms. Pauses inside the readers'
sentences still can.

`run.sh` streams each clip to a Cloud Run revision in real time with
`client.mjs`, one language per stream. The services ran with Live
Translation's settings (`ENDPOINT_MS` 700, `MAX_UTTERANCE_S` 15):

- **300M** (ht, en): an image with the old segmenter, against the same image
  base with the new one.
- **7B** stock bf16 (km, lo): the same comparison.

`score.py` computes the scores (its header defines each column):

- **cer**: CER on the joined text.
- **bnd_cer**: CER in a 10-character reference window around each cut.
- **long_***: the same for the cap's own cuts, after an utterance of 11.4 s
  or more.
- **damaged**: for ht and en, cuts where the neighbouring words are not the
  aligned reference words, or a reference word between them is lost.
  Recognition errors near a cut count too, so this overstates real cut damage.

A first run at twice real time dropped one utterance to the service's backlog
limit. Every number below is from the real-time runs.

## Results

| | ht 300M old → new | en 300M | km 7B | lo 7B |
|---|---|---|---|---|
| CER | 4.7 → **4.4** | 11.6 → 12.1 | 13.5 → **12.6** | 13.8 → 13.9 |
| CER at the cap's cuts (long_bnd_cer) | 7.5 → **2.5** | 19.0 → 21.5 | 21.3 → **15.6** | 18.9 → **10.0** |
| cap cuts damaged (ht, en) | 5/8 → **2/8** | 5/10 → 7/13 | – | – |
| CER at every cut (bnd_cer) | 6.6 → **5.5** | 16.1 → 20.0 | 15.2 → **13.4** | 18.5 → **16.7** |
| utterances under 3 s | 9 → 8 | 1 → 1 | 2 → **0** | 5 → 7 |
| longest utterance, s | 14.6 → 14.7 | 14.8 → 14.8 | 14.8 → 14.8 | 14.4 → 14.2 |

**Haitian Creole:** the cut used to fall between "paske" and "ou", and "ou"
was lost. It now falls before them, giving "…lage kòz yo | paske ou toujou…".
Likewise "jete l | nanm lanmè" became "…moulen | li jete l nan lanmè".

**English:** a wash. Most of its "damaged" cuts are normalisation ("u s" for
"US", "2017" spoken as words), not the cut itself. Both versions lose about
three words at their cuts:

- old: "and", "of", "volcano"
- new: "needed", "fir trees", "force"

Neither version cut a word cleanly in two. `split_words` was 0 throughout:
when a cut lands mid-word, the recogniser drops or garbles the word rather
than spelling both halves.

`results.json` holds the scores. `transcripts/` holds the four runs' output
(`client.mjs` format, latencies removed).

    python3 make_continuous.py --audio ../2026-10-real-voices/audio --out audio ht en km lo
    STT_URL=wss://<revision> STT_TOKEN=... SPEED=1 bash run.sh new_300m ht en
    python3 score.py --audio audio --refs ../2026-10-real-voices/sentences transcripts/*.json
