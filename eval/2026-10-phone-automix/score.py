# Scores run_methods.mts outputs two ways.
#   time    from the ground truth: of each phone's owner-speech frames, how many reached the mix;
#           of frames where only OTHER people (or only the PA) were sounding, how many did; how many
#           turns reached the mix from a second phone (a duplicate); how many owner turns lost
#           their first 0.5 s.
#   words   Azure fast transcription (en-US) of each phone's contribution, aligned to the turns
#           that overlap each recognised phrase: owner words recalled, other talkers' and PA words
#           that leaked, first words of owner turns kept.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I score.py ROOM OUT RESULTS.json
# Transcripts are cached in OUT/<scene>/<method>/asr_phone<i>.json (keyed by the audio's hash).
import difflib, hashlib, io, json, os, re, sys, time, urllib.request, uuid, wave
import concurrent.futures as cf
import numpy as np

ROOM, OUT, RES = sys.argv[1], sys.argv[2], sys.argv[3]
NOASR = os.environ.get("NOASR") == "1"  # time-based metrics only (tuning)
KEY, REGION = os.environ.get("AZURE_SPEECH_KEY", "").strip(), os.environ.get("AZURE_SPEECH_REGION", "eastus").strip()
URL = f"https://{REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
R, FR = 24000, 2400


def read(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768


def frame_rms(x):
    n = len(x) // FR
    return np.sqrt(np.mean(x[: n * FR].reshape(n, FR) ** 2, axis=1) + 1e-12)


def words(t):
    t = t.lower().replace("’", "'")
    t = re.sub(r"[^\w' ]+", " ", t)
    return [w for w in t.split() if w]


def transcribe(path, cache):
    b = open(path, "rb").read()
    h = hashlib.sha1(b).hexdigest()
    if os.path.exists(cache):
        c = json.load(open(cache))
        if c.get("hash") == h:
            return c["phrases"]
    bd = uuid.uuid4().hex
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"p.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + b + \
           (f"\r\n--{bd}\r\nContent-Disposition: form-data; name=\"definition\"\r\n\r\n"
            + json.dumps({"locales": ["en-US"]}) + f"\r\n--{bd}--\r\n").encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, data=body, headers={
                "Ocp-Apim-Subscription-Key": KEY, "Content-Type": f"multipart/form-data; boundary={bd}"})
            j = json.load(urllib.request.urlopen(req, timeout=300))
            ph = [{"t0": p["offsetMilliseconds"] / 1000, "t1": (p["offsetMilliseconds"] + p["durationMilliseconds"]) / 1000,
                   "text": p.get("text", "")} for p in j.get("phrases", [])]
            json.dump({"hash": h, "phrases": ph}, open(cache, "w"))
            return ph
        except Exception as e:  # 429 / transient
            err = str(e)[:100]
            time.sleep(3 + 5 * attempt)
    raise RuntimeError(f"transcription failed: {err}")


def match_count(hyp, ref):
    """Words of ref matched in hyp, in order (difflib blocks of 2+ words, or 1 word if ref is short)."""
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks() if b.size >= 2 or (b.size == 1 and len(ref) <= 3))


results = {}
for scene in [x for x in ("nopa", "pa20", "pa10", "pa0") if os.path.isdir(os.path.join(OUT, x))]:
    meta = json.load(open(os.path.join(ROOM, scene, "meta.json")))
    turns = meta["turns"]
    pa = meta["pa"]
    nF = len(read(os.path.join(ROOM, scene, "phone0.wav"))) // FR

    def active(intervals):
        a = np.zeros(nF, bool)
        for s, e in intervals:
            a[int(s * 10):int(np.ceil(e * 10))] = True
        return a
    talk = [active([(t["start"], t["end"]) for t in turns if t["src"] == s]) for s in range(4)]
    pa_on = active([(p["start"], p["end"] + 0.4) for p in pa]) if pa else np.zeros(nF, bool)
    for method in sorted(os.listdir(os.path.join(OUT, scene))):
        d = os.path.join(OUT, scene, method)
        if not os.path.isdir(d):
            continue
        st = json.load(open(os.path.join(d, "stats.json")))
        outs = [read(os.path.join(d, f"phone{p}.wav")) for p in range(4)]
        passed = [frame_rms(o)[:nF] > 1e-4 for o in outs]
        # ---- time-based ---------------------------------------------------------------------
        own, oth, paonly, clip, own_turns = [], [], [], 0, 0
        dup = 0
        for p in range(4):
            others = np.any([talk[s] for s in range(4) if s != p], axis=0)
            own.append(passed[p][talk[p]].mean())
            m_oth = others & ~talk[p]
            oth.append(passed[p][m_oth].mean() if m_oth.any() else 0)
            m_pa = pa_on & ~np.any(talk, axis=0)
            paonly.append(passed[p][m_pa].mean() if m_pa.any() else 0)
        for t in turns:
            a, b = int(t["start"] * 10), int(np.ceil(t["end"] * 10))
            s = t["src"]
            own_turns += 1
            if passed[s][a:a + 5].mean() < 0.6 and passed[s][a:b].mean() > 0.3:
                clip += 1
            # The turn counts again when another phone, with the talker otherwise silent there, sent
            # a third of it.
            for p in range(4):
                if p != s and passed[p][a:b][~talk[p][a:b]].mean() > 0.33 if (~talk[p][a:b]).any() else False:
                    dup += 1
                    break
        # ---- words ------------------------------------------------------------------------------
        if NOASR:
            r = {"owner_speech_passed": round(float(np.mean(own)), 4), "others_only_passed": round(float(np.mean(oth)), 4),
                 "pa_only_passed": round(float(np.mean(paonly)), 4) if pa else None, "turns_duplicated": dup,
                 "turns_first_0.5s_clipped": clip}
            results.setdefault(scene, {})[method] = r
            print(scene, method, json.dumps(r), flush=True)
            continue
        with cf.ThreadPoolExecutor(4) as ex:
            asr = list(ex.map(lambda p: transcribe(os.path.join(d, f"phone{p}.wav"), os.path.join(d, f"asr_phone{p}.json")), range(4)))
        own_ref = own_hit = oth_hit = pa_hit = first_ref = first_hit = 0
        oth_total = sum(len(words(t["text"])) for t in turns) * 3  # each turn could leak into 3 phones
        pa_total = sum(len(words(x["text"])) for x in pa) * 4
        for p in range(4):
            got = {("t", i): 0 for i in range(len(turns))}
            got.update({("p", i): 0 for i in range(len(pa))})
            hyp_by_turn = {}
            for ph in asr[p]:
                hw = words(ph["text"])
                if not hw:
                    continue
                cands = [("t", i, t) for i, t in enumerate(turns) if t["start"] - 1.0 < ph["t1"] and t["end"] + 1.0 > ph["t0"]]
                cands += [("p", i, x) for i, x in enumerate(pa) if x["start"] - 1.0 < ph["t1"] and x["end"] + 1.5 > ph["t0"]]
                # Give the phrase's words to every overlapping source they match (a phrase can span two).
                for kind, i, src in cands:
                    c = match_count(hw, words(src["text"]))
                    if c:
                        got[(kind, i)] += c
                        hyp_by_turn.setdefault((kind, i), []).extend(hw)
            for i, t in enumerate(turns):
                n = len(words(t["text"]))
                k = min(n, got[("t", i)])
                if t["src"] == p:
                    own_ref += n
                    own_hit += k
                    fw = words(t["text"])[:2]
                    first_ref += 1
                    hw = hyp_by_turn.get(("t", i), [])
                    if hw and match_count(hw[:6], fw) >= 2:
                        first_hit += 1
                else:
                    oth_hit += k
            for i, x in enumerate(pa):
                pa_hit += min(len(words(x["text"])), got[("p", i)])
        r = {
            "owner_speech_passed": round(float(np.mean(own)), 4),
            "others_only_passed": round(float(np.mean(oth)), 4),
            "pa_only_passed": round(float(np.mean(paonly)), 4) if pa else None,
            "turns_duplicated": dup, "turns": own_turns, "turns_first_0.5s_clipped": clip,
            "owner_words_lost": round(1 - own_hit / own_ref, 4),
            "first_words_lost": round(1 - first_hit / first_ref, 4),
            "other_talker_words_leaked": round(oth_hit / oth_total, 4),
            "pa_words_leaked": round(pa_hit / pa_total, 4) if pa else None,
            "frames_sent": st["sent"], "pa_dropped": st["paDropped"], "mix_closed": st["mixClosed"],
            "pa_lag_ms": st["lags"],
            "cpu_ms_per_audio_s": {"pa_per_phone": round(st["cpu_ms_per_audio_s_pa"] / 4, 3),
                                   "automix_room_of_4": round(st["cpu_ms_per_audio_s_mix"], 3)},
        }
        results.setdefault(scene, {})[method] = r
        print(scene, method, json.dumps({k: v for k, v in r.items() if k not in ("pa_lag_ms",)}), flush=True)
json.dump(results, open(RES, "w"), indent=1)
