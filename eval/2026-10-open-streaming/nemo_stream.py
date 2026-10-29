# A NeMo cache-aware streaming FastConformer-RNNT over a whole unseen clip, written in
# the stream_partials.py shape. One stream, computationally aware: chunk k can start
# when its audio has arrived (its last sample's time on the clip's clock) and the
# previous step is done; its text arrives when its own step is done (measured on the
# GPU, synchronised). This is a real-time stream on a dedicated GPU, without sleeping.
# One warm-up pass over the first clip runs first and is not kept.
#
# The model's output is append-only (greedy RNNT over a cache: earlier tokens are never
# revised), so each partial's words are all "stable" except the last one, which a later
# sub-word can still extend. Finals: the model has no end-of-utterance output, so a
# Silero VAD (silero-vad 5, 500 ms of silence ends a turn, the same rule SimulStreaming's
# controller and omni-stt's segmenter use in spirit) marks turn ends; a final is the
# words since the previous final, sent with the first step whose audio reaches the
# VAD's decision point.
#
#   MODEL=nvidia/nemotron-3.5-asr-streaming-0.6b REV=<sha> ATT="56,6" TAG=nemo \
#     /root/venv-nemo/bin/python nemo_stream.py CLIPS_ROOT OUT_DIR
# Writes OUT_DIR/<TAG>_<pattern>_<lang>.json and OUT_DIR/<TAG>_cost.json
import json, os, sys, time
import numpy as np, soundfile as sf, torch

ROOT, OUT = sys.argv[1], sys.argv[2]
MODEL = os.environ.get("MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b")
REV = os.environ.get("REV", "main")
ATT = [int(x) for x in os.environ.get("ATT", "56,6").split(",")]
TAG = os.environ.get("TAG", "nemo")
LANGS = os.environ.get("LANGS", "en,es,fr").split(",")
LOCALE = {"en": "en-US", "es": "es-US", "fr": "fr-FR"}     # FLEURS es_419: Latin American Spanish
HOP_MS = 10.0
VAD_SILENCE_MS = 500

from huggingface_hub import hf_hub_download, list_repo_files
import nemo.collections.asr as nemo_asr
from nemo.collections.asr.parts.utils.streaming_utils import CacheAwareStreamingAudioBuffer
from silero_vad import load_silero_vad, get_speech_timestamps

nemo_file = [f for f in list_repo_files(MODEL, revision=REV) if f.endswith(".nemo")][0]
path = hf_hub_download(MODEL, nemo_file, revision=REV)
torch.cuda.reset_peak_memory_stats()
asr = nemo_asr.models.ASRModel.restore_from(path, map_location="cuda")
asr.eval()
weights_gb = torch.cuda.memory_allocated() / 1e9
asr.encoder.set_default_att_context_size(att_context_size=ATT)
prompted = hasattr(asr, "set_inference_prompt")
dec = asr.cfg.decoding
dec.strategy = "greedy_batch"
asr.change_decoding_strategy(dec)
vad = load_silero_vad()


def turn_ends(wav):
    """(speech start ms, decision ms) per turn: Silero speech segments, 500 ms of silence ends one."""
    ts = get_speech_timestamps(torch.tensor(wav), vad, sampling_rate=16000, min_silence_duration_ms=VAD_SILENCE_MS,
                               speech_pad_ms=0)
    return [(t["start"] / 16.0, t["end"] / 16.0, t["end"] / 16.0 + VAD_SILENCE_MS) for t in ts]


def run(pattern, lang, save=True):
    wavp = os.path.join(ROOT, f"clips_{pattern}", f"{lang}.wav")
    wav, sr = sf.read(wavp, dtype="float32")
    assert sr == 16000
    if prompted:
        asr.set_inference_prompt(LOCALE[lang])
        asr.decoding.set_strip_lang_tags(True)
    buf = CacheAwareStreamingAudioBuffer(model=asr, online_normalization=False, pad_and_drop_preencoded=False)
    buf.append_audio_file(wavp, stream_id=-1)
    cfg = buf.streaming_cfg
    first = lambda v: v[0] if isinstance(v, list) else v
    later = lambda v: v[1] if isinstance(v, list) else v
    cc, ct, cl = asr.encoder.get_initial_cache_state(batch_size=1)
    prev_hyp, pred_out = None, None
    clock, compute, steps = 0.0, 0.0, 0
    turns = turn_ends(wav)
    ti, words_at_final = 0, 0
    partials, finals = [], []
    it = iter(buf)
    step = 0
    last_text = ""
    while True:
        idx = buf.buffer_idx
        try:
            chunk, lens = next(it)
        except StopIteration:
            break
        size = first(cfg.chunk_size) if idx == 0 else later(cfg.chunk_size)
        audio_end = min(buf.buffer.size(-1), idx + size) * HOP_MS
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.inference_mode():
            pred_out, texts, cc, ct, cl, prev_hyp = asr.conformer_stream_step(
                processed_signal=chunk, processed_signal_length=lens, cache_last_channel=cc, cache_last_time=ct,
                cache_last_channel_len=cl, keep_all_outputs=buf.is_buffer_empty(), previous_hypotheses=prev_hyp,
                previous_pred_out=pred_out, drop_extra_pre_encoded=(0 if step == 0 else asr.encoder.streaming_cfg.drop_extra_pre_encoded),
                return_transcription=True)
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) * 1000
        compute += dt
        step += 1
        start = max(audio_end, clock)
        clock = start + dt
        t = round(clock, 1)
        h = texts[0]
        text = h.text if hasattr(h, "text") else str(h)
        words = text.split()
        seg = words[words_at_final:]
        if " ".join(seg) != last_text and seg:
            partials.append({"t": t, "text": " ".join(seg), "offsetMs": turns[ti][0] if ti < len(turns) else audio_end,
                             "stable": max(0, len(seg) - 1)})
            last_text = " ".join(seg)
        while ti < len(turns) and (audio_end >= turns[ti][2] or buf.is_buffer_empty()):
            if seg:
                a, b = turns[ti][0], turns[ti][1]
                finals.append({"t": t, "text": " ".join(seg), "offsetMs": a, "durationMs": max(1, b - a)})
                words_at_final = len(words)
                seg, last_text = [], ""
            ti += 1
    if words[words_at_final:]:
        finals.append({"t": t, "text": " ".join(words[words_at_final:]), "offsetMs": turns[-1][0] if turns else 0,
                       "durationMs": 1})
    secs = len(wav) / 16000
    if not save:
        return compute / 1000, secs
    json.dump({"lang": lang, "model": f"{MODEL}@{REV}", "att_context_size": ATT, "err": "", "partials": partials,
               "finals": finals, "steps": step, "compute_ms": round(compute), "rtf": round(compute / 1000 / secs, 4)},
              open(os.path.join(OUT, f"{TAG}_{pattern}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(TAG, pattern, lang, len(partials), "partials", len(finals), "finals", "rtf", round(compute / 1000 / secs, 4), flush=True)
    return compute / 1000, secs


# warm-up: one whole pass (kernel selection, allocator), not kept
run("reg", LANGS[0], save=False)
torch.cuda.reset_peak_memory_stats()
tot_c = tot_s = 0.0
for pattern in ["reg", "irr"]:
    for lang in LANGS:
        c, s = run(pattern, lang)
        tot_c += c
        tot_s += s
json.dump({"model": MODEL, "revision": REV, "att_context_size": ATT, "chunk_ms": (ATT[1] + 1) * 80,
           "weights_gb": round(weights_gb, 2), "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
           "rtf_one_stream": round(tot_c / tot_s, 4), "gpu": torch.cuda.get_device_name(0)},
          open(os.path.join(OUT, f"{TAG}_cost.json"), "w"), indent=1)
print("done", flush=True)
