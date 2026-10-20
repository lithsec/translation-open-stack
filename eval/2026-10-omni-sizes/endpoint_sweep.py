"""Endpointing sweep: the omni-stt service's own Segmenter over the FULL real-voice
clips, each segment decoded by Omnilingual, for several ENDPOINT_MS / MAX_UTTERANCE_S.

    STACK=/root/w/stack python3 endpoint_sweep.py --card omniASR_LLM_300M --audio audio --out out_sweep \
        [--settings 300:6,500:10,...] [--langs ht,km,lo,en] [--level 2000]

STACK holds services/omni-stt/server.py and server/ (audio_in, engines) from the
service checkout. As omni_batch.py: the audio goes in as 100 ms messages through
the service's AudioIn (fixed 96 ms blocks), Silero VAD at server.py's pinned ref
(load_vad, a fresh copy per clip), vad_block's per-block speech probability,
then Segmenter(endpoint_ms, max_s) (MIN_SPEECH_MS 400, SHORT_TURN_ENDPOINT_MS 700,
TRAILING_KEEP_MS 250 as in server.py) and a flush at the end of the clip.
The VAD probabilities depend only on the audio, so they are computed once per
clip and replayed into each setting's Segmenter.

Per segment: start/end ms; emit_ms = the stream position when the Segmenter
handed it out (offline replay, so audio time, not wall time); speech_end_ms =
the end of the last block the VAD called speech before the emit; forced = cut by
MAX_UTTERANCE_S (the "still talking" branch); flush = the end-of-clip flush.

Decoding goes through the service's own path (server.load_omni -> the stack's
Omnilingual engine: a temp 16-bit wav, batch 1, the card's language code, and
the is_nonspeech filter), one utterance at a time on the GPU, timed per
utterance (rtf = decode seconds / audio seconds). A segment with the same
samples in several settings is decoded once. score_sweep.py computes CER.
"""
import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import soundfile as sf


def stt_module():
    path = Path(os.environ["STACK"]) / "services" / "omni-stt" / "server.py"
    spec = importlib.util.spec_from_file_location("omni_stt_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def vad_blocks(stt, pcm16: bytes):
    from audio_in import vad_block
    vad = stt.load_vad()
    vad.reset_states()
    conn_in = stt.audio_input(16000, "batch")
    out = []
    for off in range(0, len(pcm16), 3200):  # 100 ms messages, as omni_transcribe.mjs sends
        for block in conn_in.feed(pcm16[off:off + 3200]):
            out.append((block, vad_block(vad, block)))
    return out


def segment(stt, blocks, endpoint_ms, max_s):
    seg = stt.Segmenter(endpoint_ms=endpoint_ms, max_s=max_s)
    segs, last_speech = [], 0
    for block, prob in blocks:
        # Segmenter.feed's forced branch: in a turn, and the buffer reaches max_s.
        forced = (len(seg.buf) + len(block)) / 16000 >= max_s and (seg.speech_seen or prob > 0.5)
        res = seg.feed(block, prob)
        if prob > 0.5:
            last_speech = int(seg.total * 1000 / 16000)
        for u, s, e in res:
            segs.append({"start_ms": s, "end_ms": e, "emit_ms": int(seg.total * 1000 / 16000),
                         "speech_end_ms": last_speech, "forced": forced, "u": u})
    for u, s, e in seg.flush():
        segs.append({"start_ms": s, "end_ms": e, "emit_ms": int(seg.total * 1000 / 16000),
                     "speech_end_ms": last_speech, "forced": False, "flush": True, "u": u})
    return segs


def level(wav, marks_path, target_rms):
    """The real-voice clips join FLEURS recordings made at very different gains:
    some sentences peak near -42 dBFS (km: 5 of 30, en: 23 of 30 under -30 dBFS),
    where Silero VAD hears nothing and the Segmenter drops the whole sentence.
    --level evens them out, sentence by sentence, so the endpointing settings
    are measured apart from that."""
    import numpy as np
    x = wav.astype(np.float32)
    for m in json.load(open(marks_path))["sentences"]:
        a, b = int(m["start"] * 16000), int(m["end"] * 16000)
        seg = x[a:b]
        rms = float(np.sqrt(np.mean(seg ** 2))) or 1.0
        g = min(target_rms / rms, 29204.0 / (float(np.abs(seg).max()) or 1.0))
        x[a:b] = seg * g
    return np.clip(x, -32768, 32767).astype(np.int16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="omniASR_LLM_300M")
    ap.add_argument("--audio", required=True, help="dir with <lang>.wav (16 kHz mono PCM16)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--langs", default="ht,km,lo,en")
    ap.add_argument("--settings", default="300:6,300:10,300:15,300:25,500:6,500:10,500:15,500:25,"
                                          "800:6,800:10,800:15,800:25,700:6,700:10,700:15,700:25")
    ap.add_argument("--level", type=float, default=0.0,
                    help="scale each sentence (audio/<lang>.json marks) to this RMS (int16 units, peak capped "
                         "at -1 dBFS), as a microphone with AGC would deliver it; 0 = the clip as recorded")
    args = ap.parse_args()
    import torch
    stt = stt_module()
    t0 = time.time()
    omni = stt.load_omni("cuda", args.card)
    load_s = time.time() - t0
    settings = [(int(a), float(b)) for a, b in (x.split(":") for x in args.settings.split(","))]
    res = {"card": args.card, "gpu": torch.cuda.get_device_name(0), "load_s": round(load_s, 1), "level_rms": args.level,
           "segmenter": {"min_speech_ms": stt.MIN_SPEECH_MS, "short_turn_endpoint_ms": stt.SHORT_TURN_ENDPOINT_MS,
                         "trailing_keep_ms": stt.TRAILING_KEEP_MS, "vad_ref": stt.VAD_REF}, "runs": []}
    dec_s = aud_s = 0.0
    torch.cuda.reset_peak_memory_stats()
    for lang in args.langs.split(","):
        wav, sr = sf.read(os.path.join(args.audio, f"{lang}.wav"), dtype="int16")
        assert sr == 16000 and wav.ndim == 1
        if args.level:
            wav = level(wav, os.path.join(args.audio, f"{lang}.json"), args.level)
        blocks = vad_blocks(stt, wav.tobytes())
        cache = {}
        for ep, mx in settings:
            segs = segment(stt, blocks, ep, mx)
            for s in segs:
                u = s.pop("u")
                key = (s["start_ms"], s["end_ms"], len(u))
                if key not in cache:
                    torch.cuda.synchronize()
                    t = time.time()
                    text = omni.transcribe(u, lang) if len(u) >= 400 else ""
                    torch.cuda.synchronize()
                    cache[key] = (text, time.time() - t)
                    dec_s += cache[key][1]
                    aud_s += len(u) / 16000
                s["text"], s["decode_s"] = cache[key][0], round(cache[key][1], 3)
            res["runs"].append({"lang": lang, "endpoint_ms": ep, "max_s": mx, "segments": segs})
            print(lang, ep, mx, len(segs), "segments", sum(s["forced"] for s in segs), "forced", flush=True)
    res["rtf_batch1"] = round(dec_s / aud_s, 4)
    res["decoded_audio_s"] = round(aud_s, 1)
    res["mem_peak_gb"] = round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / f"{args.card}{'_level' if args.level else ''}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("done rtf", res["rtf_batch1"], flush=True)


if __name__ == "__main__":
    main()
