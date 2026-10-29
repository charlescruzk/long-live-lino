"""Analyze the song: tempo, beats, bars, energy, and section boundaries -> build/song.json"""
import json, sys
import numpy as np, librosa

path = sys.argv[1]
y, sr = librosa.load(path, sr=22050, mono=True)
dur = len(y) / sr
tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="frames", tightness=120)
beat_t = librosa.frames_to_time(beats, sr=sr)
onset = librosa.onset.onset_strength(y=y, sr=sr)
# downbeat phase: pick the 4/4 phase whose beats carry the most low-end onset energy
S = np.abs(librosa.stft(y))
low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[:40]), sr=sr)
scores = [low[beats[p::4]].mean() for p in range(4)]
phase = int(np.argmax(scores))
bar_t = beat_t[phase::4]

rms = librosa.feature.rms(y=y)[0]
rms_t = librosa.times_like(rms, sr=sr)
# energy per bar
bar_energy = []
for a, b in zip(bar_t, list(bar_t[1:]) + [dur]):
    m = (rms_t >= a) & (rms_t < b)
    bar_energy.append(float(rms[m].mean()) if m.any() else 0.0)

# sections: novelty on beat-synced chroma+mfcc, agglomerative
chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
feat = np.vstack([librosa.util.normalize(chroma, axis=1), librosa.util.normalize(mfcc, axis=1)])
feat_b = librosa.util.sync(feat, beats, aggregate=np.median)
k = 9
bounds = librosa.segment.agglomerative(feat_b, k)
bound_t = sorted(set([0.0] + [float(beat_t[min(b, len(beat_t) - 1)]) for b in bounds if b > 0]))

out = dict(duration=dur, tempo=float(np.atleast_1d(tempo)[0]), beats=beat_t.tolist(),
           downbeat_phase=phase, bars=bar_t.tolist(), bar_energy=bar_energy, sections=bound_t)
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(f"duration {dur:.2f}s  tempo {out['tempo']:.1f} bpm  beats {len(beat_t)}  bars {len(bar_t)}  first beat {beat_t[0]:.2f}s")
print("bar length %.3fs" % np.median(np.diff(bar_t)))
print("sections:", [f"{t:.1f}" for t in bound_t])
e = np.array(bar_energy); e = e / e.max()
print("energy per bar (x = 0.1):")
for i, (t, v) in enumerate(zip(bar_t, e)):
    print(f"  bar {i+1:3d} {t:6.2f}s {'#' * int(v * 30)}")
