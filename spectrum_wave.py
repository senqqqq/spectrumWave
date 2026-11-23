# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "scipy", "spcm>=1.13.4,<2"]
# ///
"""Spectrum M4i.6631-x8 单通道标准回放（CH0）。

uv run spectrum_wave.py 10.2_waveforms.csv --scheme pi --dry-run
uv run spectrum_wave.py 10.2_waveforms.csv --scheme mpp --trigger ext0
uv run spectrum_wave.py raw.csv --sample-rate 250e6 --loops 10

普通 CSV 每行一个归一化采样值，可有 amplitude 或 ch0 表头。
NumPy 输入为 (N,) 原始采样、(N, 2) 的 [Rabi 幅值, 相位(rad)]，
或 (N, 3) 的 [时间(µs), Rabi 幅值, 相位(rad)]。
等间隔输入需传 sample_rate (Sa/s)，最后一个采样占一个采样周期。
原始采样升采样用线性插值，末点保持；降采样按单周期做傅里叶重采样。
带 time_us 的包络以最后一个时间戳为结束边界。连续段之间线性插值，
相位按给定的弧度值插值；跨越 2π 的连续扫描请提供展开后的相位。
重复时间戳可定义瞬时跳变。每次回放只包含选中方案及其末尾的零填充。
"""

import argparse
import csv
import time
from pathlib import Path

import numpy as np


CARD_RATE = 1_250_000_000
DEFAULT_CARRIER = 100_000_000


def read_waveform_csv(path: str | Path, *, scheme: str | None = None) -> np.ndarray:
    """读取一个方案的原始数值，返回可编辑的 float64 数组。

    单列采样返回 (N,)；幅相列返回 (N, 2)，顺序为 rabi_khz、phase_rad。
    带时间戳时返回 (N, 3)，第一列为 time_us，保留重复时间戳与原始行序。
    """
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        header = [name.strip() for name in next(csv.reader(stream), [])]
        if {"rabi_khz", "phase_rad"}.issubset(header):
            rows = csv.DictReader(stream, fieldnames=header)
            if "scheme" in header:
                groups = {}
                for row in rows:
                    groups.setdefault(row["scheme"].strip(), []).append(row)
                if scheme not in groups:
                    scheme = {"mmp": "mpp", "pulsed_shaped": "pulse_shaped"}.get(scheme, scheme)
                if scheme not in groups:
                    raise ValueError("请选择一个独立波形，--scheme 可选 " + ", ".join(groups))
                records = groups[scheme]
            else:
                if scheme is not None:
                    raise ValueError("此 CSV 缺少 scheme 列")
                records = list(rows)
            if not records:
                raise ValueError("波形 CSV 缺少采样数据")
            columns = ["rabi_khz", "phase_rad"]
            if "time_us" in header:
                columns.insert(0, "time_us")
            try:
                return np.array([[float(r[col]) for col in columns] for r in records], dtype=np.float64)
            except (ValueError, TypeError) as exc:
                raise ValueError("请检查所选波形的幅值、相位和时间列，所有值都须为数字") from exc
        if scheme is not None:
            raise ValueError("--scheme 需要含 scheme、rabi_khz 和 phase_rad 列的 CSV")
        if header not in (["ch0"], ["amplitude"]):
            stream.seek(0)
        raw = np.loadtxt(stream, delimiter=",", ndmin=2)
        if raw.shape[1] != 1:
            raise ValueError("原始波形 CSV 需要单列 CH0 采样值")
        if not raw.size:
            raise ValueError("波形 CSV 缺少采样数据")
        return raw[:, 0]


def prepare_waveform(source, sample_rate=None, *, scheme=None, carrier_hz=DEFAULT_CARRIER):
    """返回 (补齐后的 int16 DAC 数组, 有效点数)，可独立于驱动使用。"""
    times = None
    if isinstance(source, (str, Path)):
        source = read_waveform_csv(source, scheme=scheme)
    elif scheme is not None:
        raise ValueError("只有带 scheme 列的 CSV 可选方案")
    data = np.asarray(source)
    if data.dtype.kind not in "iuf" or data.size == 0 or not np.isfinite(data).all():
        raise ValueError("波形必须是非空的有限实数数组")
    data = data.astype(np.float64, copy=False)
    if data.ndim == 2 and data.shape[1] == 3:
        times = data[:, 0] * 1e-6
        data = data[:, 1:]
    elif data.ndim == 2 and data.shape[1] == 1:
        data = data[:, 0]
    envelope = data.ndim == 2 and data.shape[1] == 2
    if data.ndim != 1 and not envelope:
        raise ValueError("需要原始采样 (N,)、幅相 (N, 2) 或带 time_us 的幅相 (N, 3)")

    if times is None:
        if sample_rate is None or not np.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("等间隔输入需要正的 sample_rate (Sa/s)")
        duration = len(data) / sample_rate
    else:
        if sample_rate is not None:
            raise ValueError("带 time_us 的波形已定义时间轴，请省略 sample_rate")
        if not np.isfinite(times).all() or np.any(np.diff(times) < 0):
            raise ValueError("所选方案内的 time_us 必须有限且单调不减")
        times = times - times[0]
        duration = times[-1]
    length = duration * CARD_RATE
    if not 0.5 <= length <= 2**31:
        raise ValueError("时长超出单段回放范围（按 1.25 GSa/s 取最近整数点）")
    count = int(np.floor(length + 0.5))

    if envelope:
        if not np.isfinite(carrier_hz) or not 0 <= carrier_hz < CARD_RATE / 2:
            raise ValueError("载频须在 0 至 625 MHz 之间（不含上限）")
        grid = np.arange(count) / CARD_RATE
        if times is None:
            times = np.arange(len(data)) / sample_rate
        # At an edge use the last value at that time. Approach it from the
        # left using the first value at that time, preserving phase steps.
        left = np.searchsorted(times, grid, side="right") - 1
        right = np.minimum(left + 1, len(times) - 1)
        dt = times[right] - times[left]
        weight = np.divide(grid - times[left], dt, out=np.zeros_like(grid), where=dt > 0)
        peak = np.max(np.abs(data[:, 0]))
        amplitude = data[:, 0] / peak if peak else data[:, 0]
        amp = amplitude[left] + weight * (amplitude[right] - amplitude[left])
        phase = data[left, 1] + weight * (data[right, 1] - data[left, 1])
        wave = amp * np.cos(2 * np.pi * carrier_hz * grid + phase)
    else:
        if np.max(np.abs(data)) > 1:
            raise ValueError("原始波形的采样值必须在 [-1, 1] 范围内")
        if sample_rate == CARD_RATE:
            wave = data
        elif sample_rate < CARD_RATE:
            wave = np.interp(np.arange(count) * (sample_rate / CARD_RATE), np.arange(len(data)), data)
        else:
            # Fourier downsampling removes out-of-band bins and treats the
            # record as one period. Leave headroom at discontinuities.
            from scipy.signal import resample
            wave = resample(data, count)
    if not np.isfinite(wave).all() or np.max(np.abs(wave)) > 1 + 1e-12:
        raise ValueError("重采样后超出 DAC 量程，请降低输入幅值并留出余量")
    codes = np.zeros((count + 31) // 32 * 32, dtype=np.int16)
    codes[:count] = np.rint(wave * 32767).astype(np.int16)
    return codes, count


def play_waveform(source, sample_rate=None, *, scheme=None, carrier_hz=DEFAULT_CARRIER,
                  amplitude_mv=100, loops=1, trigger="software", trigger_mv=500,
                  device="/dev/spcm0", dry_run=False):
    """生成 CH0 波形并阻塞至完成。loops=0 循环至 Ctrl+C，ext0 等待上升沿。"""
    if not isinstance(amplitude_mv, (int, np.integer)) or not 80 <= amplitude_mv <= 2000:
        raise ValueError("amplitude_mv 须为 80 至 2000 的整数（50 Ω 负载下的峰值）")
    if not isinstance(loops, (int, np.integer)) or not 0 <= loops <= 2**32 - 1:
        raise ValueError("loops 须为 0 至 2**32-1 的整数")
    if trigger not in ("software", "ext0"):
        raise ValueError("trigger 可选 software 或 ext0")
    codes, count = prepare_waveform(source, sample_rate, scheme=scheme, carrier_hz=carrier_hz)
    if scheme is not None:
        print(f"{scheme} | 载频 {carrier_hz / 1e6:g} MHz")
    print(f"CH0 | {CARD_RATE / 1e9:g} GSa/s | {count} 有效点 + {len(codes)-count} 补零点"
          f" | 每轮 {len(codes) / CARD_RATE * 1e6:.6f} µs | 满量程 ±{amplitude_mv} mV @ 50 Ω")
    if dry_run:
        return
    try:
        import spcm
    except (ImportError, OSError) as exc:
        raise RuntimeError("请安装 Spectrum 板卡驱动和 Python 包 spcm") from exc

    with spcm.Card(device) as card:
        if card.card_type() != spcm.TYP_M4I6631_X8:
            raise ValueError(f"{device} 不是 M4i.6631-x8")
        if codes.nbytes > card.get_i(spcm.SPC_PCIMEMSIZE):
            raise ValueError(f"波形需要 {codes.nbytes} 字节，超过板载内存")
        card.reset()
        card.card_mode(spcm.SPC_REP_STD_SINGLE)
        card.loops(loops)
        channel = spcm.Channels(card, card_enable=spcm.CHANNEL0)
        channel.amp(amplitude_mv)
        channel.stop_level(spcm.SPCM_STOPLVL_ZERO)
        channel.enable(True)
        clock = spcm.Clock(card)
        clock.mode(spcm.SPC_CM_INTPLL)
        if clock.sample_rate(CARD_RATE) != CARD_RATE:
            raise RuntimeError("无法设置 1.25 GSa/s 板卡时钟")
        trig = spcm.Trigger(card)
        if trigger == "ext0":
            trig.or_mask(spcm.SPC_TMASK_EXT0)
            trig.ext0_coupling(spcm.COUPLING_DC)
            trig.ext0_mode(spcm.SPC_TM_POS)
            trig.ext0_level0(trigger_mv)
        else:
            trig.or_mask(spcm.SPC_TMASK_SOFTWARE)

        transfer = spcm.DataTransfer(card)
        transfer.memory_size(len(codes))
        transfer.allocate_buffer(len(codes))
        transfer.buffer[0, :] = codes
        transfer.start_buffer_transfer(spcm.M2CMD_DATA_STARTDMA, spcm.M2CMD_DATA_WAITDMA)
        card.start(spcm.M2CMD_CARD_ENABLETRIGGER)
        print(f"已上传，触发源 {trigger}，播放次数 {loops or '连续'}。Ctrl+C 停止。", flush=True)
        while not card.status() & spcm.M2STAT_CARD_READY:
            time.sleep(0.02)
        # Card.__exit__ stops the card and DMA on completion or interruption.


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="波形 CSV")
    parser.add_argument("--scheme", help="从多方案 CSV 选择一个波形")
    parser.add_argument("--sample-rate", type=float, help="等间隔输入采样率 (Sa/s)")
    parser.add_argument("--carrier-hz", type=float, default=DEFAULT_CARRIER, help="包络载频，默认 100 MHz")
    parser.add_argument("--amplitude-mv", type=int, default=100, help="50 Ω 下峰值，默认 100 mV")
    parser.add_argument("--loops", type=int, default=1, help="1 为单次，正整数为有限循环，0 为连续")
    parser.add_argument("--trigger", choices=("software", "ext0"), default="software")
    parser.add_argument("--trigger-mv", type=int, default=500, help="EXT0 上升沿阈值，默认 500 mV")
    parser.add_argument("--device", default="/dev/spcm0")
    parser.add_argument("--dry-run", action="store_true", help="仅生成并检查波形")
    try:
        play_waveform(**vars(parser.parse_args()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
