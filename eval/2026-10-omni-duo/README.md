# omni-stt duo: the 7B and the CTC 3B streaming service on one 48 GB GPU (October 2026)

The streaming track ([eval/2026-10-ctc-stream](../2026-10-ctc-stream/README.md))
does not fit beside the 7B on an L4, so it ran as a second service. Here both
run on one larger GPU: two omni-stt processes behind one router
(`services/omni-stt/duo/`, README "One GPU for both"). The questions were:

1. How long from start to ready, both services loaded?
2. How much GPU memory do both take, idle and under load?
3. Six Khmer and Lao rooms, each with its 7B socket and its streaming
   socket (what Live Translation opens): do the two slow each other down?

Run 2026-10-27 on an NVIDIA A40 (48 GB, 46 GB usable) in a RunPod Secure Cloud
pod (9 vCPU, 50 GB RAM). The pod rebuilt `Dockerfile.duo`'s file system by
hand (the base image's pip installs, Meta's two checkpoints converted to
bf16 by `7b/to_bf16.py`, both cards) and ran `duo-start.sh` unchanged.
Clients: `eval_client.py` from the streaming eval, on the pod itself,
streaming 100 ms PCM16 messages at real-time pace through the router; each
clip its own connection, every stream talking without a break (the
streaming eval's load test). Clips: the first 10 of FLEURS km and lo test
(`prep_fleurs.py`). This directory holds no audio and no transcripts, and the
raw per-message timings were not kept: the tables are the runs' summaries.

## Summary

- **Ready 16 s after start**, both checkpoints dropped from the page cache
  first (`evict.py`, posix_fadvise). The 7B's 15.6 GB loaded in 7.8 s, the
  3B's 6.2 GB in 3.2 s, in parallel. The image pull comes on top of that; the
  image was not built for this run, so the pull was not timed.
- **Memory: 24.0 GB at idle** (7B process 16.4 GB, 3B process 7.5 GB),
  **29.8 GB at the peak** of six 7B streams beside six streaming ones, 35.3 GB
  with ten streaming ones. A 48 GB card has 16 GB to spare at six and six.
- **Six rooms (six 7B + six streaming sockets) fit.** The streaming commit
  lag stays at the look-ahead plus 0.1-0.4 s (p50 2.13-2.19 s, p90 2.37-2.46 s),
  as with the streaming service alone. The 7B's finals arrive 1.2-1.6 s later
  (p50) than with the 7B alone on the same GPU: the two processes share the
  GPU by time slices. The GPU was 79% busy on average.
- **Ten streaming sockets beside six 7B** saturate it (86%): commit lag p90
  2.9-3.0 s, 7B finals p50 3.4-4.6 s. Size for six rooms per card.
- Load does not change the text: CER was the same in every run (below).

## Load

Seconds, p50 / p90. "7B final" is the last `inputTranscript` of a clip after
its speech ended; "commit lag" is a commit's arrival minus the audio time it
reaches; "first partial" is after the speech onset. GPU from `nvidia-smi`
once a second.

| 7B streams | streaming streams | 7B final km | 7B final lo | commit lag km | commit lag lo | first partial km | GPU mean | GPU memory peak |
|---|---|---|---|---|---|---|---|---|
| 6 | 0 | 2.45 / 3.74 | 1.22 / 2.98 | | | | 35% | 29.6 GB* |
| 0 | 6 | | | 2.06 / 2.16 | 2.07 / 2.16 | 0.78 / 2.63 | 50% | 28.9 GB* |
| 6 | 6 | 3.64 / 5.17 | 2.84 / 5.54 | 2.13 / 2.37 | 2.19 / 2.46 | 0.91 / 2.72 | 79% | 29.8 GB |
| 6 | 10 | 4.64 / 7.16 | 3.41 / 6.54 | 2.31 / 2.93 | 2.60 / 2.98 | 0.97 / 3.32 | 86% | 35.3 GB |

\* Both processes stay loaded in every run, and PyTorch keeps what a
process has allocated once: the one-service rows include the other
process's memory.

CER (%, the streaming eval's `judge.cer`), first 10 FLEURS clips: 7B finals
km 16.0, lo 13.8-13.9 in every run with 7B streams; committed streaming text
km 16.7-17.0, lo 15.3-15.6 in every run with streaming streams. Through the
RunPod proxy from a client elsewhere (Live Translation's own streaming
client against the same pod), a Lao clip's first live text came 1.8 s after
its audio began and each 7B piece matched a pause the stream had closed
(`end:true` within 0.6 s of the piece's end).

## Notes

- **Two processes, not one.** One process could load both (the track loads
  its own 3B when the recogniser is another card), but then a client's
  streaming socket would also get the 7B's finals for every piece, and a
  client that wants both opens two sockets: the 7B would decode each piece
  twice. Two processes keep each service as measured on its own, and the
  router gives clients one address.
- The 7B's slowdown comes from sharing the GPU's time, not memory. CUDA MPS
  (one shared context) might reduce it; not tried (the container has no MPS
  daemon).
- The streaming eval found about six continuously talking streams per L4 for
  the 3B alone. On the A40 six streaming sockets used 50% of the GPU alone.
- The router's idle stop was checked on the test pod: the pod's own key
  stopped it through RunPod's API.

## Reproduce

On a GPU host with the duo image (or its file system; port 8080 the router):

```
python3 prep_fleurs.py /opt/set 30                 # FLEURS km_kh and lo_la test, first 30 each
python3 evict.py /opt/models/7b/*.pt /opt/models/ctc3b/*.pt
bash /opt/stt/duo-start.sh                          # time to "[router] ready"
bash load.sh l6x6 6 6 10                            # six 7B + six streaming streams, 10 clips each
```
