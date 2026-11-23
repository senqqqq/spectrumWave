import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

from spectrum_wave import CARD_RATE, main, prepare_waveform


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

    def test_dry_run_cli_works_without_driver(self):
        argv = ["spectrum-wave", str(EXAMPLE), "--scheme", "pi", "--dry-run"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.dict(sys.modules, spcm=None), redirect_stdout(output):
            main()
        self.assertIn("6250", output.getvalue())


if __name__ == "__main__":
    unittest.main()
