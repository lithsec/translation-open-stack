# The English meaning each clip is graded against (sentences/meaning_<lang>.json).
# FLEURS: the English FLoRes sentence with the same id (professional
# translation). Haitian Creole (CMU, no translations): Gemini 2.5 Pro writes
# them once, from the text the speakers read — a model-made reference, said so
# wherever these grades are reported.
#
#   GOOGLE_CLOUD_PROJECT=... python3 make_refs.py
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
SENT = os.path.join(HERE, "sentences")


def main():
    en = os.path.join(SENT, "en.json")
    if os.path.exists(en):
        english = json.load(open(en))
        for lang in ["en", "ja", "km", "lo"]:
            if os.path.exists(os.path.join(SENT, f"{lang}.json")):
                json.dump(english, open(os.path.join(SENT, f"meaning_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    ht = os.path.join(SENT, "ht.json")
    out = os.path.join(SENT, "meaning_ht.json")
    if os.path.exists(ht) and not os.path.exists(out):
        from vertex import gemini
        src = json.load(open(ht))
        res = gemini(
            "Translate each of these Haitian Creole sentences into accurate, natural English. They are read aloud "
            "from novels, newspapers, the Bible and literacy primers. Keep every number, name and negation exact; "
            f"do not explain. Return JSON: a list of exactly {len(src)} strings in the same order.\n\n"
            + json.dumps(src, ensure_ascii=False)
        )
        assert isinstance(res, list) and len(res) == len(src), (type(res), len(res))
        json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print("meaning files:", sorted(f for f in os.listdir(SENT) if f.startswith("meaning_")))


if __name__ == "__main__":
    main()
