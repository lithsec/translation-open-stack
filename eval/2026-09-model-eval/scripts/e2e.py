# End-to-end through the real stack server: same audio as Gemini heard. English into ten
# languages in ONE room (as a meeting would be), and each native clip into English.
import json, subprocess, os, concurrent.futures as cf
os.makedirs("e2e", exist_ok=True)
def run(clip, langs):
    env = dict(os.environ, WAIT=str(int((float(subprocess.check_output(["soxi","-D",f"audio24/{clip}.wav"], text=True)) + 25) * 1000)))
    out = subprocess.run(["node","../noise/stack/stack.mjs",f"audio24/{clip}.wav",langs,"0"], env=env, capture_output=True, text=True).stdout
    open(f"e2e/{clip}.json","w").write(out)
    j = json.loads(out)["out"]
    return clip + ": " + ", ".join(f"{l} {len(r['said'])}ch" for l, r in j.items())
jobs = [("en", "es,fr,de,pt,ru,uk,zh,ja,km,ht")] + [(c, "en") for c in ["es","fr","de","pt","ru","zh","ja","km","ht"]]
with cf.ThreadPoolExecutor(4) as ex:
    for line in ex.map(lambda j: run(*j), jobs): print(line, flush=True)
