"""Sweep the stack's turn rules per language, offline: the cutting loop of
handle_room (utterance mode, with QuietBoost) over each clip, then each piece
through the stack's recognisers. Pieces that come out the same in several
settings are recognised once. Runs where the stack runs (a GPU, `server/`):

    SERVER_DIR=/opt/stack/server python3 sweep.py <clips> <out.json> <configs.json> en es ...

configs.json is {"name": cfg, ...}; cfg keys (missing = the stack's flags):
  endpoint_ms   pause that ends a turn (900)
  long_s        past this much audio a shorter pause will do (5)
  long_ms       ...this one (280)
  max_s         forced cut (12), after the last sentence end heard
  min_speech_ms a pause ends a turn only once it holds this much speech ...
  hold_ms       ... unless the quiet lasts this long (default 1500)
  keep_ms       trailing pause handed over with the speech (250)

Each piece records where it starts and ends in the clip, how it was cut, and
`t`, the clip time at which the cut was decided (for latency)."""
import copy, json, os, sys, time, wave
import numpy as np
CL, OUT, CFGS = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), json.load(open(sys.argv[3]))
LANGS = sys.argv[4:]
sys.path.insert(0, os.environ.get("SERVER_DIR", "/opt/stack/server"))
os.chdir(os.environ.get("SERVER_DIR", "/opt/stack/server"))
import torch  # noqa: E402
import server as SV  # noqa: E402
import audio_in as AI  # noqa: E402
from audio_in import BLOCK, vad_block  # noqa: E402
from engines.base import Context  # noqa: E402
from engines.manager import EngineSet  # noqa: E402

R = 16000
vad_model = torch.hub.load(f"{SV.MODELS['vad']['repo']}:{SV.MODELS['vad']['ref']}", "silero_vad",
                           trust_repo=True)[0]
opts = dict(xeng=True, clone_ref=None, omni=True, mms=False, asr_model="large-v3",
            asr_multi_model="large-v3", asr_revision=None, asr_multi_revision=None,
            mt_model="google/madlad400-3b-mt", mt_ct2=None, kokoro=False, coqui=False, voices_dir=None,
            hymt=None, voxcpm=None, voxcpm_langs=None, edition="nonprofit", voxcpm_max_inflight=None,
            espeak=False, licence_review={}, voxcpm_shared={})
ctx = Context(device="cuda", devices={}, models=SV.MODELS, table=copy.deepcopy(SV.LANG_CONFIG), tables=SV._T,
              langs=["en"], srcs=LANGS, options=opts)
ES = EngineSet(ctx)
ES.load(["whisper", "omni"])


class P:  # what Pipeline.sentence_cut needs
    engines = ES


def segments(x, cfg, lang, probs):
    ep, long_s, long_ms = cfg.get("endpoint_ms", 900), cfg.get("long_s", 5), cfg.get("long_ms", 280)
    max_s, min_sp, hold = cfg.get("max_s", 12), cfg.get("min_speech_ms", 0), cfg.get("hold_ms", 1500)
    out, buf, quiet, seen = [], np.zeros(0, dtype=np.float32), 0.0, False
    for k, i in enumerate(range(0, len(x) - BLOCK + 1, BLOCK)):
        b = x[i:i + BLOCK]
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
            trail = int(R * max(0.0, quiet - cfg.get("keep_ms", 250)) / 1000)
            u = buf[:-trail] if 0 < trail < len(buf) else buf
            out.append((o, o + len(u), "end", u, pos))
            buf, quiet = np.zeros(0, dtype=np.float32), 0.0
        seen = forced
    return out


res = {name: {} for name in CFGS}
for lang in LANGS:
    with wave.open(os.path.join(CL, f"{lang}.wav")) as w:
        assert w.getframerate() == R
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    # The VAD doesn't depend on the turn rules: one pass, as the room sees it (QuietBoost).
    vad = copy.deepcopy(vad_model)
    vad.reset_states()
    boost = AI.QuietBoost()
    probs = [vad_block(vad, boost(x[i:i + BLOCK])) for i in range(0, len(x) - BLOCK + 1, BLOCK)]
    memo, t0 = {}, time.time()
    for name, cfg in CFGS.items():
        pieces = []
        for a, e, how, u, at in segments(x, cfg, lang, probs):
            if (a, e) not in memo:
                memo[(a, e)] = ES.transcribe(u, lang)
            pieces.append({"a": round(a / R, 2), "e": round(e / R, 2), "how": how, "t": round(at / R, 2), "text": memo[(a, e)]})
        res[name][lang] = pieces
    print(lang, len(CFGS), "settings,", len(memo), "pieces recognised,", round(time.time() - t0, 1), "s", flush=True)
json.dump({"cfgs": CFGS, "res": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
