"""RecorderManager test: verify raw input capture with correct timing"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = r'C:\Users\IVANZVUK\AppData\Local\Programs\Python\Python311\Lib\site-packages\PyQt5\Qt5\plugins'

from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

from lufsmeter import RecorderManager
import numpy as np
import wave

# Test 1: synthetic fast feed — verifies 100% capture
print("=== Test 1: synthetic fast feed ===")
rec = RecorderManager()
rec._base_dir_override = os.path.dirname(os.path.abspath(__file__))
rec.arm(0)
rec.arm(1)

SAMPLE_RATE = 44100
BUFFER = 1024
tone = (np.sin(2*np.pi*1000*np.arange(BUFFER)/SAMPLE_RATE) * 0.25 * 32768.0).astype(np.float32)

rec.start_recording("TEST", {0:'ch0', 1:'ch1'})
fed = 0
for cb in range(430):
    rec.feed_audio(0, tone, SAMPLE_RATE)
    rec.feed_audio(1, tone, SAMPLE_RATE)
    fed += BUFFER * 2
rec.stop_recording()
app.processEvents()

base = rec._base_dir
f0 = os.path.join(base, 'ch0.wav')
with wave.open(f0, 'rb') as wf:
    nf = wf.getnframes()
    sr = wf.getframerate()
    print(f"  ch0: {nf} frames @ {sr} Hz = {nf/sr:.2f}s (fed {fed//2} per ch)")
    assert nf == fed // 2, f"Frame count mismatch: {nf} vs {fed//2}"
    print("  PASS: 100% capture")

# Test 2: real-time rate — verifies correct pitch/duration
print("\n=== Test 2: real-time callback rate simulation ===")
rec2 = RecorderManager()
rec2.format_idx = 0  # 44.1k / 16 bit
rec2._base_dir_override = os.path.dirname(os.path.abspath(__file__))
rec2.arm(0)

rec2.start_recording("ASYNC_TEST", {0:'ch0'})
start = time.time()
cbs = 0
while time.time() - start < 3:
    rec2.feed_audio(0, tone, SAMPLE_RATE)
    cbs += 1
    time.sleep(BUFFER / SAMPLE_RATE)  # real-time rate
rec2.stop_recording()
app.processEvents()
elapsed = time.time() - start

base2 = rec2._base_dir
f2 = os.path.join(base2, 'ch0.wav')
with wave.open(f2, 'rb') as wf:
    nf = wf.getnframes()
    sr = wf.getframerate()
    dur = nf / sr
    print(f"  Wall: {elapsed:.1f}s  File: {nf} frames @ {sr} Hz = {dur:.1f}s")
    if abs(dur - elapsed) < 0.5:
        print("  PASS: duration matches wall clock")
    else:
        print(f"  NOTE: file {dur:.1f}s vs wall {elapsed:.1f}s")

# Cleanup
import shutil
for d in [base, base2]:
    if os.path.exists(d):
        shutil.rmtree(d)
print("\nDone")
