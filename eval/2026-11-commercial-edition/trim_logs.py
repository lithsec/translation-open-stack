# live.sh saves the whole stack log after every run (runs/<dir>.log.json). Keep, per run, only the lines that
# run added (everything after the previous run's log, in the order the runs ran, across every e2e dir of
# that stack start), so analyze_e2e.py counts each run's own utterances and drops. The whole log stays
# in runs/<dir>.log.full.json.
#   python3 -I trim_logs.py WORK
import glob, json, os, sys
W = sys.argv[1]
full = []
for p in glob.glob(os.path.join(W, "e2e_*", "out", "runs", "*.log.json")):
    f = p[:-len(".log.json")] + ".log.full.json"
    if not os.path.exists(f):
        os.replace(p, f)
for f in glob.glob(os.path.join(W, "e2e_*", "out", "runs", "*.log.full.json")):
    full.append((os.path.getmtime(f), f))
by_stack = {}
for _, f in sorted(full):
    lines = json.load(open(f))["lines"]
    key = lines[0] if lines else ""
    prev = by_stack.get(key, [])
    # a new stack start writes a new log: if this log doesn't continue the previous one, start over
    n = len(prev) if lines[:len(prev)] == prev else 0
    json.dump({"lines": lines[n:]}, open(f[:-len(".log.full.json")] + ".log.json", "w"))
    by_stack[key] = lines
print("trimmed", len(full))
