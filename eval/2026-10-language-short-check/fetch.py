# Short per-language check: 20 read sentences per language from FLEURS
# (google/fleurs, CC BY 4.0), test split, each with its English text by FLEURS id
# (the same FLoRes sentence read in English), so English is the reference meaning
# for X->en and the language's own text is the reference for en->X.
#
#   python3 -I fetch.py WORK
#
# Streams each language's test.tar.gz only until 20 usable recordings have come
# by (a few tens of MB, not the whole archive). Writes WORK/audio/<lang>/<n>.wav
# (16 kHz mono) and WORK/sentences.json. Audio stays out of the repository.
import json, os, random, subprocess, sys, tarfile, tempfile, urllib.request

WORK = sys.argv[1]
N, MAX_S = 20, 20
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CFG = {"vi": "vi_vn", "fa": "fa_ir", "kea": "kea_cv", "zh": "cmn_hans_cn", "yue": "yue_hant_hk",
       "ar": "ar_eg", "sw": "sw_ke", "fil": "fil_ph", "uk": "uk_ua"}


def tsv(cfg):
    """file -> (id, transcription) for recordings of at most MAX_S seconds."""
    out = {}
    for line in urllib.request.urlopen(f"{HF}/{cfg}/test.tsv", timeout=120).read().decode("utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 7 and f[5].isdigit() and int(f[5]) / 16000 <= MAX_S:
            out[f[1]] = (f[0], f[2])
    return out


def main():
    en = {}
    for fid, text in tsv("en_us").values():
        en.setdefault(fid, text)
    sentences = {}
    for lang, cfg in CFG.items():
        rows = tsv(cfg)
        d = os.path.join(WORK, "audio", lang)
        os.makedirs(d, exist_ok=True)
        got, seen_ids = [], set()
        resp = urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=300)
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                name = os.path.basename(m.name)
                if not m.isfile() or name not in rows:
                    continue
                fid, text = rows[name]
                if fid in seen_ids or fid not in en:
                    continue
                raw = tar.extractfile(m).read()
                out = os.path.join(d, f"{len(got):02d}.wav")
                with tempfile.NamedTemporaryFile(suffix=".wav") as t:
                    t.write(raw); t.flush()
                    subprocess.run(["sox", "-V1", t.name, "-r", "16000", "-c", "1", "-b", "16", out], check=True)
                seen_ids.add(fid)
                got.append({"n": len(got), "id": fid, "text": text, "en": en[fid]})
                if len(got) == N:
                    break
        resp.close()
        sentences[lang] = got
        print(lang, len(got), flush=True)
    json.dump(sentences, open(os.path.join(WORK, "sentences.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
