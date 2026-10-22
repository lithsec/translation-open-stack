# Experiment B inputs: shootout real-voice directions (30) + e2e-stack directions (20).
import json, os, sys
SH = os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-translator-shootout/out")
E2E = sys.argv[1]; OUT = sys.argv[2]
HYMT = {"en", "zh", "fr", "es", "ja", "ru", "de", "uk", "km"}
I = json.load(open(f"{SH}/inputs.json"))
D = []
for k, v in I.items():
    if not k.startswith("real:"):
        continue
    s, t = k[5:].split("-")
    stack = "hymt2-7b-nf4" if s in HYMT and t in HYMT else "madlad-7b-int8"
    f = k.replace(":", "_")
    D.append({"id": k, "src": s, "tgt": t, "inputs": v["input"], "source": v["source"], "reference": v["reference"],
              "stack_name": stack, "stack": json.load(open(f"{SH}/mt/{stack}/{f}.json"))["out"],
              "sol": json.load(open(f"{SH}/mt/foundry-gpt-5.6-sol@low/{f}.json"))["out"]})
S = json.load(open(f"{E2E}/out/sentences.json"))
for d, v in S.items():
    s, t = d.split("-")
    D.append({"id": "e2e:" + d, "src": s, "tgt": t, "inputs": v["heard_per_sentence"], "source": v["source"],
              "stack_name": "stack-mt (e2e sidecar)",
              "stack": json.load(open(f"{E2E}/out/mt/stack-mt:transcript/{d}.json"))["out"],
              "sol": json.load(open(f"{E2E}/out/mt/sol:transcript/{d}.json"))["out"]})
for x in D:
    assert len(x["inputs"]) == len(x["stack"]) == len(x["sol"]) == len(x["source"]), x["id"]
json.dump(D, open(OUT, "w"), ensure_ascii=False, indent=1)
print(len(D), "directions", sum(len(x["inputs"]) for x in D), "sentences")
