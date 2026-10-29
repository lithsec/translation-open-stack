# ../2026-10-complete-thought-endpointing/stream_partials.py, unchanged, with Korean (ko-KR) and Persian (fa-IR) added
# to its locale table. Every partial and final is kept, the clip streamed at real time, the locale pinned.
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=... [MODEL=mai-transcribe-2-streaming] \
#     <venv with azure-cognitiveservices-speech==1.52.0>/bin/python -I stream.py CLIPS OUT TAG lang...
import importlib.util, os, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "stream_partials", os.path.join(HERE, "..", "2026-10-complete-thought-endpointing", "stream_partials.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.LOCALE.update({"ko": "ko-KR", "fa": "fa-IR"})
ts = [threading.Thread(target=m.run, args=(l,)) for l in sys.argv[4:]]
for t in ts:
    t.start()
for t in ts:
    t.join()
