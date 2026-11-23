import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from spectrum_wave import CARD_RATE, main, prepare_waveform, read_waveform_csv


EXAMPLE = Path(__file__).resolve().parents[1] / "10.2_waveforms.csv"


class WaveformTests(unittest.TestCase):
    def test_example_schemes_have_independent_durations(self):
        for scheme, expected in (("pi", 6250), ("mpp", 13241), ("pulse_shaped", 32346)):
            with self.subTest(scheme=scheme):
                codes, count = prepare_waveform(EXAMPLE, scheme=scheme)
                self.assertEqual(count, expected)
                self.assertEqual(codes.dtype, np.int16)
                self.assertEqual(len(codes), (count + 31) // 32 * 32)
                self.assertTrue(np.all(codes[count:] == 0))

        with self.assertRaises(ValueError):
            prepare_waveform(EXAMPLE)

    def test_pi_uses_default_carrier_and_mpp_preserves_phase_step(self):
        pi, _ = prepare_waveform(EXAMPLE, scheme="pi")
        first_cycle = np.cos(2 * np.pi * 100e6 * np.arange(13) / CARD_RATE)
        np.testing.assert_allclose(pi[:13], np.rint(32767 * first_cycle), atol=1)

        mpp, _ = prepare_waveform(EXAMPLE, scheme="mpp", carrier_hz=0)
        edge = int(np.ceil(1.929418454936187e-6 * CARD_RATE))
        np.testing.assert_array_equal(mpp[edge - 1:edge + 1], [32767, -32767])

    def test_numpy_envelope_normalizes_rabi_and_applies_phase(self):
        envelope = np.array([[25, 0], [50, np.pi], [0, 0]])
        codes, _ = prepare_waveform(envelope, CARD_RATE, carrier_hz=0)
        np.testing.assert_array_equal(codes[:3], [16384, -32767, 0])

    def test_raw_array_upsampling_preserves_input_amplitude(self):
        codes, count = prepare_waveform(np.array([0, 0.5]), CARD_RATE / 2)
        self.assertEqual(count, 4)
        np.testing.assert_array_equal(codes[:count], [0, 8192, 16384, 16384])

    def test_read_uniform_csv_returns_editable_samples_or_envelope(self):
        cases = [
            ("0.5\n-0.25\n", [0.5, -0.25]),
            ("amplitude\n0.5\n", [0.5]),
            ("phase_rad,rabi_khz\n0,25\n1,50\n", [[25, 0], [50, 1]]),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wave.csv"
            for content, expected in cases:
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    data = read_waveform_csv(path)
                    self.assertIsInstance(data, np.ndarray)
                    np.testing.assert_array_equal(data, expected)
                    codes, count = prepare_waveform(data, CARD_RATE)
                    direct, direct_count = prepare_waveform(path, CARD_RATE)
                    np.testing.assert_array_equal(codes, direct)
                    self.assertEqual(count, direct_count)

    def test_read_timed_schemes_preserves_replay_samples(self):
        for scheme, rows in (("pi", 3), ("mpp", 13), ("pulse_shaped", 991)):
            with self.subTest(scheme=scheme):
                data = read_waveform_csv(EXAMPLE, scheme=scheme)
                self.assertEqual(data.shape, (rows, 3))
                codes, valid = prepare_waveform(data)
                direct, direct_valid = prepare_waveform(EXAMPLE, scheme=scheme)
                np.testing.assert_array_equal(codes, direct)
                self.assertEqual(valid, direct_valid)

    def test_edit_phase_after_reading_timestamped_csv(self):
        data = read_waveform_csv(EXAMPLE, scheme="mpp")
        t_edge = 1.929418454936187
        np.testing.assert_allclose(data[1:3], [[t_edge, 100, 0], [t_edge, 100, np.pi]])
        edge_sample = int(np.ceil(t_edge * 1e-6 * CARD_RATE))
        before, _ = prepare_waveform(data, carrier_hz=0)
        data[:, 2] = 0
        after, _ = prepare_waveform(data, carrier_hz=0)
        self.assertEqual(before[edge_sample], -32767)
        self.assertEqual(after[edge_sample], 32767)

    def test_dry_run_cli_works_without_driver(self):
        argv = ["spectrum-wave", str(EXAMPLE), "--scheme", "pi", "--dry-run"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.dict(sys.modules, spcm=None), redirect_stdout(output):
            main()
        self.assertIn("6250", output.getvalue())


if __name__ == "__main__":
    unittest.main()
