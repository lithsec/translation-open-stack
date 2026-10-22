"""Replay the stack's utterance cutting (handle_room, utterance mode) on a clip,
offline and faster than real time, then recognise each piece with the stack's
own recognisers. Runs where the stack runs (a GPU; `server/` importable):

    SERVER_DIR=/opt/stack/server python3 replay.py <clips> <out.json> '<cfg>' en es ...

<clips>/<lang>.wav is 16 kHz mono PCM16. cfg (JSON) sets the cutting rules:
  endpoint_ms   pause that ends an utterance (scripts/run.sh: 900)
  long_s        past this much audio a shorter pause will do (default 5)
  long_ms       ...this one (280)
  max_s         forced cut (scripts/run.sh: 12), after the last sentence end
                the recogniser heard, else at the quietest point
  keep_ms       trailing pause handed over with the speech (250)
  vad_gain      1: the VAD sees audio_in.QuietBoost's copy (the fix), 0: the raw audio
  hl, gmax, target   override QUIET_HALF_LIFE_S, QUIET_MAX_GAIN, QUIET_TARGET

The loop is a copy of handle_room's, kept in step by hand: no websocket, no
translation, one 96 ms block at a time through the same Silero model. Each
piece records its start and end in the clip, how it was cut, and `t`, the clip
time at which the cut was decided.
"""
import copy, json, os, sys, time, wave
import numpy as np
CL, OUT, CFG = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), json.loads(sys.argv[3])
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


def segments(x, cfg, lang):
    vad = copy.deepcopy(vad_model)
    vad.reset_states()
    for k, name in (("hl", "QUIET_HALF_LIFE_S"), ("gmax", "QUIET_MAX_GAIN"), ("target", "QUIET_TARGET")):
        if k in cfg:
            setattr(AI, name, cfg[k])
    boost = AI.QuietBoost() if cfg.get("vad_gain") else (lambda z: z)
    out, buf, quiet, seen = [], np.zeros(0, dtype=np.float32), 0.0, False
    for i in range(0, len(x) - BLOCK + 1, BLOCK):
        b = x[i:i + BLOCK]
        pos = i + BLOCK
        buf = np.concatenate([buf, b])
        if vad_block(vad, boost(b)) > 0.5:
            seen, quiet = True, 0.0
        else:
            quiet += BLOCK / R * 1000
        if not seen:
            buf = buf[-(R // 2):]      # idle: half a second of pre-roll only
            continue
        bs = len(buf) / R
        need = cfg["endpoint_ms"] if bs < cfg.get("long_s", 5) else cfg.get("long_ms", 280)
        forced = bs >= cfg["max_s"]
        if not forced and (quiet < need or len(buf) < R):
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


res = {}
for lang in LANGS:
    with wave.open(os.path.join(CL, f"{lang}.wav")) as w:
        assert w.getframerate() == R
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    t0 = time.time()
    pieces = [{"a": round(a / R, 2), "e": round(e / R, 2), "how": how, "t": round(at / R, 2),
               "text": ES.transcribe(u, lang)} for a, e, how, u, at in segments(x, CFG, lang)]
    res[lang] = pieces
    print(lang, len(pieces), "pieces", round(time.time() - t0, 1), "s", flush=True)
json.dump({"cfg": CFG, "res": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
