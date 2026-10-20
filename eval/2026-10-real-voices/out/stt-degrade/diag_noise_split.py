# Diagnostic (2026-10-19): Azure en-US dropped 23 of 30 English sentences at
# 10 dB SNR. Is it the babble (competing speech) or the steady HVAC noise?
# Builds out/stt-degrade/audio/{en_hvac10,en_babble10}/en.wav (whole English
# clip, 10 dB SNR, one noise type each), same recipe as make_conditions.py.
# Then: ffmpeg -i audio/en_hvac10/en.wav -af "highpass=f=200:poles=2,highpass=f=200:poles=2"
#   audio/en_hvac10_hp200/en.wav, and LANGS=en azure_run.py en_hvac10 en_babble10 en_hvac10_hp200.
import importlib.util, os, sys
import numpy as np
spec = importlib.util.spec_from_file_location("mc", os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_conditions.py"))
mc = importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
clips = {l: mc.read(os.path.join(mc.HERE, "audio", f"{l}.wav")) for l in mc.BABBLE_POOL}
x = clips["en"]; s = mc.active_rms(x, "en")
for name, n in (("en_hvac10", mc.hvac(len(x))), ("en_babble10", mc.babble("en", len(x), clips))):
    mc.write(os.path.join(mc.OUT, name, "en.wav"), x + n / np.sqrt(np.mean(n ** 2)) * s / 10 ** 0.5)
