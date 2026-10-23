# Cuts the Gemini Live Translate runs (../2026-10-es-pt-live-compare/live_translate.mjs,
# re-run here on both unseen English clips) into the read sentences with that round's
# segment.py, for the four targets measured here.
#
#   GEMINI_API_KEY=... python3 -I seg_live.py CLIPS OUT
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("segment", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "segment.py"))
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)   # reads CLIPS and OUT from sys.argv
seg.NAMES = {k: seg.NAMES[k] for k in ("es", "pt", "fr", "ja")}
seg.main()
