# Runs every condition x direction x route once (../harness/run_route.ts in
# the scratch LT copy), with limits on what runs at once: Gemini Live
# Translate one session at a time (it fell behind under concurrency in the
# languages round), at most 3 Foundry sessions (~36 requests/min), at most 2
# omni-stt sessions, at most 6 sessions in all. Conditions go in the order
# below, so hall-reverb (the first to drop on budget) runs last.
#
#   python3 run_all.py <scratch LT dir> <degraded clips dir> <runs dir> [condition ...]
#
# A Gemini Live Translate session that stalls (stall() below) is kept as
# stalled-<name>.json and rerun once; the rerun is the one analysed.
import json, os, shutil, subprocess, sys, threading, time

LIMITS = {"foundry": 3, "omni": 2, "gemini": 1, "all": 6}
FOUNDRY = {"azure-foundry", "omni-foundry", "ht-exception"}
OMNI = {"omni-foundry", "ht-exception"}
uses = lambda r: {"all"} | ({"foundry"} if r in FOUNDRY else set()) | ({"omni"} if r in OMNI else set()) | ({"gemini"} if r == "gemini-lt" else set())
busy = {k: 0 for k in LIMITS}
lock = threading.Lock()


def stall(path):
    """Gemini LT fell behind or went silent: a voiced-audio gap of 15 s or more
    while the clip is still playing, last voice more than 15 s before the
    clip's last sentence ends, or a reconnect."""
    run = json.load(open(path))
    ev = [e for e in run["events"] if e.get("t") is not None]
    end = run["marks"][-1]["end"] * 1000
    v = [e["t"] for e in ev if e["kind"] == "audio" and "on" in e]
    if not v:
        return "no voiced audio"
    gaps = [b - a for a, b in zip([0] + v, v) if a < end]
    why = []
    if max(gaps) >= 15000:
        why.append(f"gap {max(gaps) / 1000:.0f} s")
    if v[-1] < end - 15000:
        why.append(f"silent from {v[-1] / 1000:.0f} s")
    rec = [e for e in ev if e["kind"] == "recovery"]
    if rec:
        why.append(f"{len(rec)} recovery: {rec[0]['action']}")
    return "; ".join(why)


def run(job):
    c, r, s, t = job
    d = os.path.join(OUT, c)
    os.makedirs(d, exist_ok=True)
    name = f"r1-{r}-{s}-{t}"
    out = os.path.join(d, f"{name}.json")
    if os.path.exists(out):
        return
    for attempt in (1, 2):
        with open(os.path.join(d, f"{name}.log"), "w") as log:
            p = subprocess.run(["npx", "tsx", "harness/run_route.ts", r, s, t, os.path.join(CLIPS, c), out], cwd=LT, stdout=log, stderr=log)
        why = stall(out) if (r == "gemini-lt" and p.returncode == 0 and os.path.exists(out)) else ""
        print(time.strftime("%H:%M:%S"), c, name, "exit", p.returncode, f"STALL ({why})" if why else "", flush=True)
        if not why or attempt == 2:
            break
        shutil.move(out, os.path.join(d, f"stalled-{name}.json"))
        shutil.move(os.path.join(d, f"{name}.log"), os.path.join(d, f"stalled-{name}.log"))


def main():
    global LT, CLIPS, OUT
    LT, CLIPS, OUT = sys.argv[1:4]
    CONDS = sys.argv[4:] or ["clean", "room-mic", "noise-10dB", "bt-narrowband", "hall-reverb"]
    ROUTES = ["azure", "azure-foundry", "omni-foundry", "gemini-lt"]
    DIRS = ["en-es", "es-en", "en-ja", "km-en"]
    JOBS = []
    for c in CONDS:
        for d in DIRS:
            for r in ROUTES:
                JOBS.append((c, r, *d.split("-")))
        # Haitian Creole: Azure has no Haitian recogniser; LT's exception route instead.
        JOBS += [(c, "ht-exception", "ht", "en"), (c, "gemini-lt", "ht", "en")]
    threads = []
    pending = list(JOBS)
    while pending or threads:
        threads = [th for th in threads if th.is_alive()]
        with lock:
            for job in list(pending):
                need = uses(job[1])
                if all(busy[k] < LIMITS[k] for k in need):
                    for k in need:
                        busy[k] += 1
                    pending.remove(job)

                    def go(job=job, need=need):
                        try:
                            run(job)
                        finally:
                            with lock:
                                for k in need:
                                    busy[k] -= 1
                    th = threading.Thread(target=go)
                    th.start()
                    threads.append(th)
                    time.sleep(3)  # stagger connects
        time.sleep(2)
    print("ALLDONE", flush=True)


if __name__ == "__main__":
    main()
