# 20 ms RMS envelope of every bleed clip and enrolment file (pod), for the level gate.
#   python bleed_energy.py CLIPS OUT
import glob, os, sys
import numpy as np
import soundfile as sf

for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.wav"))):
    x, r = sf.read(f, dtype="float32")
    n = len(x) // 320 * 320
    e = np.sqrt(np.mean(x[:n].reshape(-1, 320) ** 2, axis=1) + 1e-12).astype(np.float32)
    np.save(os.path.join(sys.argv[2], os.path.basename(f)[:-4] + "_rms.npy"), e)
print("ok")
