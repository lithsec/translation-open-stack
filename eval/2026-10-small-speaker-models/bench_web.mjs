// onnxruntime-web (WASM backend, 1 thread, SIMD) timing of each model on one 1.0 s and one 1.5 s
// window of features (100 / 150 frames x 80), as a phone browser would run it.
//   node bench_web.mjs MODEL_DIR name [name ...]
import * as ort from "onnxruntime-web";
import fs from "node:fs";
ort.env.wasm.numThreads = Number(process.env.THREADS || 1);
const dir = process.argv[2];
const out = {};
for (const name of process.argv.slice(3)) {
  const p = `${dir}/${name}.onnx`;
  if (!fs.existsSync(p)) continue;
  try {
    const s = await ort.InferenceSession.create(fs.readFileSync(p), { executionProviders: ["wasm"] });
    const inp = s.inputNames[0];
    out[name] = {};
    for (const T of [100, 150]) {
      const x = new ort.Tensor("float32", Float32Array.from({ length: T * 80 }, () => Math.random() - 0.5), [1, T, 80]);
      for (let i = 0; i < 3; i++) await s.run({ [inp]: x });
      const t = [];
      for (let i = 0; i < 15; i++) { const a = performance.now(); await s.run({ [inp]: x }); t.push(performance.now() - a); }
      t.sort((a, b) => a - b);
      out[name][`ms_${T / 100}s`] = Math.round(t[7] * 100) / 100;
    }
  } catch (e) { out[name] = { error: String(e).slice(0, 200) }; }
  console.log(name, JSON.stringify(out[name]));
}
fs.writeFileSync(`${dir}/../web_bench_t${process.env.THREADS || 1}.json`, JSON.stringify(out, null, 1));
