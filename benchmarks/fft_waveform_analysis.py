#!/usr/bin/env python3
"""
FFT Waveform Analysis Benchmark
================================
Generates synthetic audio with known frequencies, runs FFT,
and extracts the original frequency components.
"""

import numpy as np

# === 1. Generate synthetic audio data ===
# Simulation parameters
SAMPLE_RATE = 44100       # 44.1 kHz (CD quality)
DURATION = 1.0            # 1 second of audio
NUM_SAMPLES = int(SAMPLE_RATE * DURATION)

# Known frequencies to embed (Hz) with amplitudes
FREQUENCIES = [440.0, 880.0, 1320.0]   # A4, A5, E6
AMPLITUDES  = [1.0,   0.5,   0.25]     # decreasing amplitude

print("=" * 60)
print("FFT Waveform Analysis")
print("=" * 60)
print(f"\nSample Rate:  {SAMPLE_RATE} Hz")
print(f"Duration:     {DURATION} s")
print(f"Num Samples:  {NUM_SAMPLES}")
print(f"\nEmbedded frequencies:")
for freq, amp in zip(FREQUENCIES, AMPLITUDES):
    print(f"  {freq:>8.1f} Hz  (amplitude {amp})")

# === 2. Create the waveform (treat as sound capture) ===
t = np.linspace(0, DURATION, NUM_SAMPLES, endpoint=False)

# Sum sine waves at known frequencies
signal = np.zeros(NUM_SAMPLES)
for freq, amp in zip(FREQUENCIES, AMPLITUDES):
    signal += amp * np.sin(2 * np.pi * freq * t)

# Scale to 16-bit range and add small noise
signal_16bit = signal / np.max(np.abs(signal)) * 32767
noise = np.random.normal(0, 50, NUM_SAMPLES)  # small noise floor
signal_16bit = np.clip(signal_16bit + noise, -32768, 32767).astype(np.int16)

print(f"\nSignal stats:")
print(f"  Min value:  {signal_16bit.min()}")
print(f"  Max value:  {signal_16bit.max()}")
print(f"  Dtype:      {signal_16bit.dtype}")

# === 3. Run FFT ===
print("\nRunning FFT...")
fft_result = np.fft.rfft(signal_16bit)
fft_magnitude = np.abs(fft_result) / NUM_SAMPLES  # normalize
fft_freqs = np.fft.rfftfreq(NUM_SAMPLES, d=1.0 / SAMPLE_RATE)

print(f"  FFT bins:   {len(fft_result)}")
print(f"  Freq range: {fft_freqs[0]:.1f} - {fft_freqs[-1]:.1f} Hz")

# === 4. Extract frequency peaks ===
# Find peaks: points where magnitude is higher than both neighbors
# and above a threshold
threshold = np.max(fft_magnitude) * 0.05  # 5% of max peak

peaks = []
for i in range(1, len(fft_magnitude) - 1):
    if (fft_magnitude[i] > fft_magnitude[i-1] and
        fft_magnitude[i] > fft_magnitude[i+1] and
        fft_magnitude[i] > threshold):
        peaks.append((fft_freqs[i], fft_magnitude[i]))

# Sort by magnitude (strongest first)
peaks.sort(key=lambda x: x[1], reverse=True)

# === 5. Report results ===
print("\n" + "=" * 60)
print("FREQUENCY SPECTRUM RESULTS")
print("=" * 60)
print(f"\n{'Rank':<6} {'Frequency (Hz)':<18} {'Magnitude':<14} {'Match?':<10}")
print("-" * 48)

for i, (freq, mag) in enumerate(peaks[:10], 1):
    # Check if this peak matches a known frequency (within 2 Hz)
    match = ""
    for known_freq in FREQUENCIES:
        if abs(freq - known_freq) < 2.0:
            match = f"<-- {known_freq:.0f} Hz"
            break
    print(f"{i:<6} {freq:<18.2f} {mag:<14.2f} {match}")

# === Verification ===
print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)

found_freqs = set()
for freq, mag in peaks[:10]:
    for known_freq in FREQUENCIES:
        if abs(freq - known_freq) < 2.0:
            found_freqs.add(known_freq)

print(f"\nExpected frequencies: {FREQUENCIES}")
print(f"Found frequencies:   {sorted(found_freqs)}")

all_found = all(
    any(abs(peak_freq - kf) < 2.0 for peak_freq, _ in peaks)
    for kf in FREQUENCIES
)

if all_found:
    print("\n[PASS] All embedded frequencies correctly identified!")
else:
    missing = [f for f in FREQUENCIES if f not in found_freqs]
    print(f"\n[FAIL] Missing frequencies: {missing}")

# Verify relative amplitudes make sense (440 > 880 > 1320)
peak_map = {}
for freq, mag in peaks:
    for kf in FREQUENCIES:
        if abs(freq - kf) < 2.0:
            peak_map[kf] = mag

if len(peak_map) == len(FREQUENCIES):
    amp_order = all(
        peak_map[FREQUENCIES[i]] > peak_map[FREQUENCIES[i+1]]
        for i in range(len(FREQUENCIES) - 1)
    )
    print(f"Amplitude ordering correct: {amp_order}")
    for kf in FREQUENCIES:
        print(f"  {kf:.0f} Hz -> magnitude {peak_map[kf]:.2f}")

print("\n" + "=" * 60)
print("BENCHMARK COMPLETE")
print("=" * 60)
