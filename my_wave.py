"""在 Python 中定义 CH0 波形。加 --dry-run 可离线运行。"""

import argparse

import numpy as np

from spectrum_wave import play_waveform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", action="store_true", help="使用 Rabi 包络和相位生成 100 MHz 脉冲")
    parser.add_argument("--dry-run", action="store_true", help="仅检查波形")
    args = parser.parse_args()

    sample_rate = 250e6
    t = np.arange(1600) / sample_rate
    if args.envelope:
        rabi = np.hanning(t.size)
        phase_rad = np.linspace(0, np.pi, t.size)
        wave = np.column_stack((rabi, phase_rad))
    else:
        wave = 0.5 * np.sin(2 * np.pi * 10e6 * t)

    play_waveform(wave, sample_rate=sample_rate, amplitude_mv=100, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
