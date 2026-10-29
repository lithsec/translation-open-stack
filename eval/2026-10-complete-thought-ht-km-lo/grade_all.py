# ../2026-10-complete-thought-endpointing/grade_all.py with Haitian Creole, Khmer and Lao in the language names. That file:
# ../2026-10-llm-commit-policy-bedrock-de-hi-tr/grade_all.py, unchanged. That file:
# The cut, the grade and the contradiction count of the earlier runs, unchanged, with German,
# Hindi and Turkish added to their language names, and gemini-flash-latest as the default for
# both GRADER and SEGMENTER (as ../2026-10-llm-commit-policy-bedrock):
#   ../2026-10-simultaneous-phrases/seg_all.py       (cut each spoken stream into the read sentences)
#   ../2026-10-es-pt-live-compare/grade.py           (blind side-by-side grade, one call per direction)
#   ../2026-10-simultaneous-phrases/contradictions.py (chunks the finished sentence contradicts)
#
#   GEMINI_API_KEY=... python3 -I grade_all.py seg CLIPS_ROOT WORK
#   GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs.json WORK/grades.json
#   GEMINI_API_KEY=... python3 -I grade_all.py contra WORK/contra_jobs.json WORK/contra.json
import concurrent.futures as cf
import glob, importlib.util, os, sys

os.environ.setdefault("GRADER", "gemini-flash-latest")
os.environ.setdefault("SEGMENTER", "gemini-flash-latest")
HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.join(HERE, "..")
ADD = {"ht": "Haitian Creole", "km": "Khmer", "lo": "Lao", "en": "English"}


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(EVAL, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


mode = sys.argv[1]
if mode == "seg":
    ROOT, WORK = sys.argv[2], sys.argv[3]
    sys.argv = [sys.argv[0], ROOT, WORK]
    seg_all = load("seg_all", "2026-10-simultaneous-phrases/seg_all.py")
    seg_all.NAMES.update(ADD)
    paths = sorted(glob.glob(os.path.join(WORK, "sim", "*", "*.json")))
    with cf.ThreadPoolExecutor(4) as ex:
        for p, msg in ex.map(seg_all.one, paths):
            print(os.path.relpath(p, WORK), msg, flush=True)
elif mode == "grade":
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    g = load("grade", "2026-10-es-pt-live-compare/grade.py")
    g.NAMES.update(ADD)
    g.main()
elif mode == "contra":
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    c = load("contradictions", "2026-10-simultaneous-phrases/contradictions.py")
    c.G.NAMES.update(ADD)
    c.main()
