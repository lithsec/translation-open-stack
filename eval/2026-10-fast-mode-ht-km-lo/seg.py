# Cuts each system's spoken stream into the read (or said) English sentences with the
# anchor method of ../2026-10-simultaneous-phrases/seg_all.py (a Gemini call names where
# each sentence's translation starts, copied verbatim; the stream is only divided, never
# changed), with Haitian Creole, Khmer and Lao added to its language names.
#
#   GEMINI_API_KEY=... python3 -I seg.py ROOT WORK
# ROOT holds clips_reg/ clips_irr/ (the unseen clips) and clips_conv/en.txt.json (the AMI
# excerpt's "what was said" sentences).
import concurrent.futures as cf
import glob, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT, WORK = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("seg_all", os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "seg_all.py"))
S = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0], ROOT, WORK]
spec.loader.exec_module(S)
S.NAMES.update({"ht": "Haitian Creole", "km": "Khmer", "lo": "Lao"})

if __name__ == "__main__":
    paths = sorted(glob.glob(os.path.join(WORK, "sim", "*", "*.json")))
    with cf.ThreadPoolExecutor(6) as ex:
        for p, msg in ex.map(S.one, paths):
            print(os.path.relpath(p, WORK), msg, flush=True)
