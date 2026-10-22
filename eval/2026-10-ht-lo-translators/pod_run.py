# The open translators on one GPU pod (A100 80 GB), over out/inputs.json.
#   image vllm/vllm-openai:v0.31.0, SSH; /root/work holds this file and inputs.json.
#   python3 pod_run.py download            # every model at its pinned revision, in this order
#   /root/mtv/bin/python pod_run.py seq <name>   # MADLAD (CTranslate2 int8) and NLLB (transformers)
#   python3 pod_run.py llm <name>          # the LLMs, served by vLLM on 127.0.0.1:8001
# Writes /root/work/mt/<name>/<set>.json: {"out", "wall_s", "single_s", "tok_s"} and
# /root/work/mt/<name>/meta.json (VRAM, timings). Seq2seq models translate one sentence at a
# time; their single-stream figures are the same 10 sentences per direction as the LLMs'. LLMs run the full pass 8 requests
# in flight, then a single-stream pass over 10 sentences per direction (sample()).
import json, os, re, statistics, subprocess, sys, threading, time, urllib.request
import concurrent.futures as cf

W = "/root/work"
M = "/root/models"
NAMES = {"en": "English", "ht": "Haitian Creole", "lo": "Lao"}
NLLB_CODE = {"en": "eng_Latn", "ht": "hat_Latn", "lo": "lao_Laoo"}
SEQ = {
    "madlad-7b-int8": ("google/madlad400-7b-mt", "1ff63ce7ddd571a69d45cad9672c553428419671"),
    "nllb-200-3.3b": ("facebook/nllb-200-3.3B", "1a07f7d195896b2114afcb79b7b57ab512e7b43e"),
    "madlad-10b-int8": ("google/madlad400-10b-mt", "9f2797629c31e69617186dbe5f0ca43bf662f36d"),
    # CTranslate2's converter ran 10-17 minutes on 13 cores without writing anything for either
    # MADLAD on this pod, so both ran in bf16 under transformers instead (same prompt and beam).
    "madlad-10b-bf16": ("google/madlad400-10b-mt", "9f2797629c31e69617186dbe5f0ca43bf662f36d"),
    "madlad-7b-bf16": ("google/madlad400-7b-mt", "1ff63ce7ddd571a69d45cad9672c553428419671"),
}
LLM = {  # name -> (repo, revision, vllm args, kind)
    "qwen3.5-122b-a10b-int4": ("Qwen/Qwen3.5-122B-A10B-GPTQ-Int4", "30cd92cba9707a9aba09d1e490ed4b66b78e9606",
                               ["--language-model-only", "--quantization", "gptq_marlin", "--max-model-len", "4096",
                                "--gpu-memory-utilization", "0.94", "--max-num-seqs", "8",
                                "--speculative-config", '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'], "chat"),
    # The settings above leave no KV cache on an 80 GB card (72.4 GiB of weights): the most
    # that fits, without MTP, short context, two sequences.
    "qwen3.5-122b-a10b-int4-80gb": ("Qwen/Qwen3.5-122B-A10B-GPTQ-Int4", "30cd92cba9707a9aba09d1e490ed4b66b78e9606",
                                    ["--language-model-only", "--quantization", "gptq_marlin", "--max-model-len", "2048",
                                     "--gpu-memory-utilization", "0.98", "--max-num-seqs", "2"], "chat"),
    "gemma-4-31b-it": ("google/gemma-4-31B-it", "842da3794eaa0b77d5f08bae87a17459d91ff475",
                       ["--max-model-len", "4096", "--gpu-memory-utilization", "0.92", "--max-num-seqs", "8",
                        "--limit-mm-per-prompt", '{"image":0,"audio":0,"video":0}'], "chat"),
    "translategemma-27b": ("google/translategemma-27b-it", "7d10f0b72f89a2d0f268cea30727d8b77c0d25c2",
                           ["--max-model-len", "4096", "--gpu-memory-utilization", "0.92", "--max-num-seqs", "8",
                            "--limit-mm-per-prompt", '{"image":0}'], "tgemma"),
    "gpt-oss-120b@low": ("openai/gpt-oss-120b", "b5c939de8f754692c1647ca79fbf85e8c1e70f8a",
                         ["--reasoning-parser", "openai_gptoss", "--max-model-len", "8192",
                          "--gpu-memory-utilization", "0.92", "--max-num-seqs", "8"], "oss"),
    "milmmt-46-12b": ("xiaomi-research/MiLMMT-46-12B-v0.1", "7aaf496e72a69d97e8095f79c3e93565a82ce7a4",
                      ["--max-model-len", "4096", "--gpu-memory-utilization", "0.90", "--max-num-seqs", "8"], "milmmt"),
}
# Qwen3.5-122B and Gemma 4 31B are graded from OpenRouter (or_run.py); on the pod they run only
# the single-stream sample, for our own GPU's speed and memory ("llm <name> timing").
# (madlad-*-int8, the stack's CTranslate2 form, is kept for reference: its converter did not finish.)
ORDER = ["nllb-200-3.3b", "madlad-7b-bf16", "madlad-10b-bf16", "translategemma-27b", "milmmt-46-12b",
         "qwen3.5-122b-a10b-int4-80gb", "gemma-4-31b-it"]
IGNORE = ["original/*", "metal/*", "*.gguf", "*.md", "LICENSE", "USAGE_POLICY", "*.msgpack", "*.h5", "flax_model*", "tf_model*"]


def repo_of(name):
    return (SEQ.get(name) or LLM[name])[:2]


def download():
    from huggingface_hub import snapshot_download
    tok = open("/root/.hf_token").read().strip() if os.path.exists("/root/.hf_token") else None
    import shutil
    for name in ORDER:
        repo, rev = repo_of(name)
        while shutil.disk_usage(M).free < 100e9:  # 400 GB disk: run.sh deletes each model after its run
            time.sleep(20)
        t0 = time.time()
        for attempt in range(3):
            try:
                snapshot_download(repo, revision=rev, local_dir=f"{M}/{name}", ignore_patterns=IGNORE,
                                  max_workers=16, token=tok if "gemma" in repo else None)
                break
            except Exception as e:
                print(f"retry {name}: {e!r}"[:300], flush=True)
                time.sleep(10)
        open(f"{M}/{name}/.done", "w").write(str(time.time() - t0))
        print(f"downloaded {name} in {time.time() - t0:.0f}s", flush=True)


def wait_download(name):
    while not os.path.exists(f"{M}/{name}/.done"):
        time.sleep(10)


def gpu_used_mb():
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    return int(r.stdout.split()[0])


def sample(D):
    """Set -> sentence indices for the single-stream timing: 10 per direction, spread over its sets."""
    dirs = {}
    for k, v in D.items():
        dirs.setdefault(f"{v['src']}-{v['tgt']}", []).extend((k, i) for i in range(len(v["source"])))
    idx = {}
    for items in dirs.values():
        for k, i in items[::max(1, len(items) // 10)][:10]:
            idx.setdefault(k, []).append(i)
    return idx


def save(name, k, d):
    os.makedirs(f"{W}/mt/{name}", exist_ok=True)
    json.dump(d, open(f"{W}/mt/{name}/{k.replace(':', '_')}.json", "w"), ensure_ascii=False, indent=1)


def seq(name):
    import torch
    wait_download(name)
    D = json.load(open(f"{W}/inputs.json"))
    src_dir = f"{M}/{name}"
    peak = [0]
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            peak[0] = max(peak[0], gpu_used_mb())
            time.sleep(0.5)
    threading.Thread(target=watch, daemon=True).start()
    if name.startswith("madlad") and name.endswith("-bf16"):
        from transformers import T5ForConditionalGeneration, T5Tokenizer
        tok = T5Tokenizer.from_pretrained(src_dir)
        model = T5ForConditionalGeneration.from_pretrained(src_dir, dtype=torch.bfloat16).cuda().eval()

        def one(text, src, tgt):  # madlad.py's prompt and beam, in transformers
            enc = tok(f"<2{tgt}> {text}", return_tensors="pt").to("cuda")
            torch.cuda.synchronize()
            t0 = time.time()
            with torch.inference_mode():
                g = model.generate(**enc, num_beams=4, max_new_tokens=min(256, enc["input_ids"].shape[1] * 2 + 24))
            torch.cuda.synchronize()
            sec = time.time() - t0
            return tok.decode(g[0], skip_special_tokens=True).strip(), sec, int(g.shape[1])
    elif name.startswith("madlad"):
        import ctranslate2
        from transformers import T5Tokenizer
        out = f"/root/ct2/{name}"
        if not os.path.exists(os.path.join(out, "model.bin")):
            r = subprocess.run([os.path.join(os.path.dirname(sys.executable), "ct2-transformers-converter"), "--model", src_dir, "--quantization", "int8",
                                "--output_dir", out, "--low_cpu_mem_usage", "--force"], capture_output=True, text=True)
            print("ct2", r.returncode, (r.stdout + r.stderr)[-600:], flush=True)
        tok = T5Tokenizer.from_pretrained(src_dir)
        tr = ctranslate2.Translator(out, device="cuda", compute_type="int8_float16")

        def one(text, src, tgt):  # server/engines/madlad.py's settings
            ids = tok.encode(f"<2{tgt}> {text}")
            t0 = time.time()
            r = tr.translate_batch([tok.convert_ids_to_tokens(ids)], max_decoding_length=min(256, len(ids) * 2 + 24),
                                   beam_size=4, replace_unknowns=False)
            sec = time.time() - t0
            hyp = r[0].hypotheses[0]
            return tok.decode(tok.convert_tokens_to_ids(hyp), skip_special_tokens=True).strip(), sec, len(hyp)
    else:
        from transformers import AutoTokenizer
        from transformers.models.m2m_100.modeling_m2m_100 import M2M100ForConditionalGeneration
        tok = AutoTokenizer.from_pretrained(src_dir)
        model = M2M100ForConditionalGeneration.from_pretrained(src_dir, dtype=torch.bfloat16).cuda().eval()

        def one(text, src, tgt):
            tok.src_lang = NLLB_CODE[src]
            enc = tok(text, return_tensors="pt").to("cuda")
            torch.cuda.synchronize()
            t0 = time.time()
            with torch.inference_mode():
                g = model.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids(NLLB_CODE[tgt]),
                                   num_beams=4, max_new_tokens=400)
            torch.cuda.synchronize()
            sec = time.time() - t0
            return tok.decode(g[0], skip_special_tokens=True).strip(), sec, int(g.shape[1])
    one("Hello.", "en", "ht")  # warm-up
    for k, v in D.items():
        outs, secs, toks = [], [], []
        for s in v["source"]:
            o, sec, n = one(s, v["src"], v["tgt"])
            outs.append(o); secs.append(round(sec, 3)); toks.append(round(n / sec, 1) if sec else None)
        pick = sample(D).get(k, [])
        save(name, k, {"out": outs, "wall_s": secs, "single_s": [secs[i] for i in pick],
                       "tok_s": [toks[i] for i in pick]})
        print(name, k, f"median {statistics.median(secs):.2f}s", flush=True)
    stop.set()
    json.dump({"vram_peak_mb": peak[0]}, open(f"{W}/mt/{name}/meta.json", "w"))


def prompt(s, src, tgt):
    a, b = NAMES[src], NAMES[tgt]
    return (f"Translate this {a} sentence into natural {b}. Keep numbers, names and negation exact. "
            f"Output only the {b}.\nSentence: {s}")


def request(kind, s, src, tgt):
    a, b = NAMES[src], NAMES[tgt]
    if kind == "tgemma":  # the model card's template, rendered by hand (vLLM adds <bos>)
        p = (f"<start_of_turn>user\nYou are a professional {a} ({src}) to {b} ({tgt}) translator. Your goal is to "
             f"accurately convey the meaning and nuances of the original {a} text while adhering to {b} grammar, "
             f"vocabulary, and cultural sensitivities.\nProduce only the {b} translation, without any additional "
             f"explanations or commentary. Please translate the following {a} text into {b}:\n\n\n"
             f"{s.strip()}<end_of_turn>\n<start_of_turn>model\n")
        return "completions", {"prompt": p, "temperature": 0, "max_tokens": 600}
    if kind == "milmmt":  # the model card's prompt
        return "completions", {"prompt": f"Translate this from {a} to {b}:\n{a}: {s.strip()}\n{b}:",
                               "temperature": 0, "max_tokens": 600, "stop": ["\n"]}
    body = {"messages": [{"role": "user", "content": prompt(s, src, tgt)}], "max_tokens": 600}
    if kind == "oss":  # round 2's settings: the card's sampling, reasoning low
        body.update(temperature=1.0, top_p=1.0, reasoning_effort="low", max_tokens=4096)
    else:
        body.update(temperature=0, chat_template_kwargs={"enable_thinking": False})
    return "chat/completions", body


def call(kind, s, src, tgt):
    ep, body = request(kind, s, src, tgt)
    body["model"] = "m"
    req = urllib.request.Request(f"http://127.0.0.1:8001/v1/{ep}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    j = json.load(urllib.request.urlopen(req, timeout=600))
    sec = time.time() - t0
    c = j["choices"][0]
    text = c["text"] if ep == "completions" else (c["message"].get("content") or "")
    text = re.sub(r"(?s)^.*</think>", "", text).strip()
    return text, sec, (j.get("usage") or {}).get("completion_tokens")


def llm(name, timing_only=False):
    repo, rev, args, kind = LLM[name]
    wait_download(name)
    D = json.load(open(f"{W}/inputs.json"))
    if kind == "milmmt":  # Lao only (no Haitian Creole in its 46 languages)
        D = {k: v for k, v in D.items() if "lo" in (v["src"], v["tgt"])}
    log = open(f"{W}/vllm-{name}.log", "w")
    cmd = ["vllm", "serve", f"{M}/{name}", "--served-model-name", "m", "--host", "127.0.0.1", "--port", "8001"] + args
    print(" ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.time()
    while True:
        if proc.poll() is not None:
            raise SystemExit(f"vllm {name} exited {proc.returncode}; see {W}/vllm-{name}.log")
        try:
            urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5)
            break
        except Exception:
            time.sleep(5)
    load_s = time.time() - t0
    print(f"{name} ready in {load_s:.0f}s", flush=True)
    try:
        call(kind, "Hello.", "en", "ht")
        for k, v in ({} if timing_only else D).items():
            with cf.ThreadPoolExecutor(8) as ex:
                r = list(ex.map(lambda s: call(kind, s, v["src"], v["tgt"]), v["source"]))
            save(name, k, {"out": [x[0] for x in r], "wall_s": [round(x[1], 3) for x in r],
                           "completion_tokens": [x[2] for x in r]})
            print(name, k, flush=True)
        # Single stream: 10 sentences per direction (sample()), one at a time.
        for k, idx in sample(D).items():
            for i in idx:
                v = D[k]
                _, sec, n = call(kind, v["source"][i], v["src"], v["tgt"])
                p = f"{W}/mt/{name}/{k.replace(':', '_')}.json"
                os.makedirs(os.path.dirname(p), exist_ok=True)
                r = json.load(open(p)) if os.path.exists(p) else {}
                r.setdefault("single_s", []).append(round(sec, 3))
                r.setdefault("tok_s", []).append(round(n / sec, 1) if n and sec else None)
                json.dump(r, open(p, "w"), ensure_ascii=False, indent=1)
        used = gpu_used_mb()
        txt = open(f"{W}/vllm-{name}.log", errors="replace").read()
        m = re.findall(r"[Mm]odel (?:loading took|weights took) ([0-9.]+) ?Gi?B", txt)
        json.dump({"weights_gib": float(m[-1]) if m else None, "gpu_used_mb": used, "load_s": round(load_s)},
                  open(f"{W}/mt/{name}/meta.json", "w"))
    finally:
        os.killpg(proc.pid, 15)
        try:
            proc.wait(90)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
        time.sleep(5)


if __name__ == "__main__":
    {"download": lambda: download(), "seq": lambda: seq(sys.argv[2]), "llm": lambda: llm(sys.argv[2], sys.argv[3:] == ["timing"])}[sys.argv[1]]()
