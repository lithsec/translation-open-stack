"""Offline replay of the stack's cutting loop (handle_room, utterance mode) with
QuietBoost variants: which audio the VAD sees, and optionally which audio the
recogniser hears. Pieces are recognised by the stack's own recognisers.

    SERVER_DIR=<this branch>/server python3 replay.py <clips dir> <out.json> en es ...

Variants: base (main: 1.5 s half-life, VAD copy only), f25 / f50 (forget faster,
0.25 / 0.5 s half-life, while a block peaks 20 dB under the level), f25asr (f25,
and the recogniser hears the boosted audio), asr (main's boost, recogniser too).
Turn rules per language as on main: en es fr pt the flags (900 ms, 280 ms past
5 s, cut at 12 s); ja km lo ht 900 ms, 500 ms past 8 s, 15 s, 2.5 s min speech."""
import copy, json, os, sys, time, wave
import numpy as np
CL, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
LANGS = sys.argv[3:]
sys.path.insert(0, os.environ.get("SERVER_DIR", "/opt/stack/server"))
os.chdir(os.environ.get("SERVER_DIR", "/opt/stack/server"))
import torch  # noqa: E402
import server as SV  # noqa: E402
import audio_in as AI  # noqa: E402
from audio_in import BLOCK, vad_block  # noqa: E402
from engines.base import Context  # noqa: E402
from engines.manager import EngineSet  # noqa: E402

R = 16000
VARIANTS = {"base": (0.0, False), "f25": (0.25, False), "f25asr": (0.25, True)}
FLAGS = {"endpoint_ms": 900, "long_s": 5, "long_ms": 280, "max_s": 12, "min_speech_ms": 0}
LONG = {"endpoint_ms": 900, "long_s": 8, "long_ms": 500, "max_s": 15, "min_speech_ms": 2500}
RULES = {l: (LONG if l in ("ja", "km", "lo", "ht") else FLAGS) for l in ("en", "es", "fr", "pt", "ja", "km", "lo", "ht")}

vad_model = torch.hub.load(f"{SV.MODELS['vad']['repo']}:{SV.MODELS['vad']['ref']}", "silero_vad",
                           trust_repo=True)[0]
opts = dict(xeng=True, clone_ref=None, omni=True, mms=False, asr_model="large-v3",
            asr_multi_model="large-v3", asr_revision=None, asr_multi_revision=None,
            mt_model="google/madlad400-3b-mt", mt_ct2=None, kokoro=False, coqui=False, voices_dir=None,
            hymt=None, voxcpm=None, voxcpm_langs=None, edition="nonprofit", voxcpm_max_inflight=None,
            espeak=False, licence_review={}, voxcpm_shared={})
ctx = Context(device="cuda", devices={}, models=SV.MODELS, table=copy.deepcopy(SV.LANG_CONFIG), tables=SV._T,
              langs=["en"], srcs=[l.split("_")[0] for l in LANGS], options=opts)
ES = EngineSet(ctx)
ES.load(["whisper", "omni"])


class P:  # what Pipeline.sentence_cut needs
    engines = ES


def segments(x, heard, cfg, lang, probs):
    ep, long_s, long_ms = cfg["endpoint_ms"], cfg["long_s"], cfg["long_ms"]
    max_s, min_sp, hold = cfg["max_s"], cfg["min_speech_ms"], 1500
    out, buf, quiet, seen = [], np.zeros(0, dtype=np.float32), 0.0, False
    for k, i in enumerate(range(0, len(x) - BLOCK + 1, BLOCK)):
        b = heard[i:i + BLOCK]
        pos = i + BLOCK
        buf = np.concatenate([buf, b])
        if probs[k] > 0.5:
            seen, quiet = True, 0.0
        else:
            quiet += BLOCK / R * 1000
        if not seen:
            buf = buf[-(R // 2):]
            continue
        bs = len(buf) / R
        need = ep if bs < long_s else long_ms
        forced = bs >= max_s
        if not forced and (quiet < need or len(buf) < R):
            continue
        if not forced and (bs - quiet / 1000) * 1000 < min_sp and quiet < max(need, hold):
            continue
        o = pos - len(buf)
        if forced:
            f = SV.Pipeline.sentence_cut(P, buf.copy(), lang)
            cut, how = (f[0], f[1]) if f else (SV.quietest_cut(buf), "quietest")
            out.append((o, o + cut, how, buf[:cut], pos))
            buf, quiet = buf[cut:], 0.0
        else:
            trail = int(R * max(0.0, quiet - 250) / 1000)
            u = buf[:-trail] if 0 < trail < len(buf) else buf
            out.append((o, o + len(u), "end", u, pos))
            buf, quiet = np.zeros(0, dtype=np.float32), 0.0
        seen = forced
    return out


res = {v: {} for v in VARIANTS}
for clip in LANGS:
    lang = clip.split("_")[0]
    with wave.open(os.path.join(CL, f"{clip}.wav")) as w:
        assert w.getframerate() == R
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    t0, n = time.time(), 0
    for name, (fast, asr) in VARIANTS.items():
        AI.QUIET_FAST_HALF_LIFE_S = fast
        vad = copy.deepcopy(vad_model)
        vad.reset_states()
        boost = AI.QuietBoost()
        probs, heard = [], []
        for i in range(0, len(x) - BLOCK + 1, BLOCK):
            loud = boost(x[i:i + BLOCK])
            probs.append(vad_block(vad, loud))
            heard.append(loud if asr else x[i:i + BLOCK])
        heard = np.concatenate(heard)
        pieces = []
        for a, e, how, u, at in segments(x, heard, RULES[lang], lang, probs):
            pieces.append({"a": round(a / R, 2), "e": round(e / R, 2), "how": how, "t": round(at / R, 2),
                           "text": ES.transcribe(u, lang)})
            n += 1
        res[name][clip] = pieces
    print(clip, n, "pieces recognised,", round(time.time() - t0, 1), "s", flush=True)
    json.dump({"variants": {k: list(v) for k, v in VARIANTS.items()}, "res": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
json.dump({"variants": {k: list(v) for k, v in VARIANTS.items()}, "res": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
