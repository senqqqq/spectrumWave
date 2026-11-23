# spectrumWave

在 Spectrum M4i.6631-x8 的 CH0 上回放自定义波形。程序接受 CSV 或 NumPy 数组，将波形转换为 1.25 GSa/s 的 16 位 DAC 采样，并通过 Spectrum 官方 `spcm` 接口上传到板载内存。支持软件触发、EXT0 上升沿触发、单次播放和循环播放。

## 安装与离线检查

在装有 [uv](https://docs.astral.sh/uv/) 的终端运行以下命令。项目选用 CPython 3.12，`uv.lock` 记录依赖版本。离线波形生成只需 NumPy 和 SciPy。

```sh
git clone https://github.com/senqqqq/spectrumWave.git
cd spectrumWave
uv sync --locked
uv run --locked spectrum-wave 10.2_waveforms.csv --scheme pi --dry-run
```

上述示例会生成 6250 个有效点，并在末尾补 22 个零点以满足板卡的 32 点对齐要求。每轮实际时长为 5.0176 µs，包含末尾补零。用 `--help` 可查看所有回放参数。

## 三条独立的示例波形

`10.2_waveforms.csv` 包含 `pi`、`mpp`、`pulse_shaped`。每次用 `--scheme` 选一条，独立计算时间轴与峰值。程序读取 `time_us`、`rabi_khz` 和 `phase_rad`，按下面的表达式生成单通道实信号，默认载频为 100 MHz。

```text
CH0(t) = 输出峰值 × [Rabi(t) / max(abs(Rabi))] × cos(2π × 载频 × t + phase(t))
```

同一时间戳的两行可以定义相位跳变。连续时间段按给定相位线性插值，跨越 2π 的连续扫描请提供展开后的相位。

## 上卡播放

先在板卡所在主机安装 [Spectrum 驱动](https://github.com/SpectrumInstrumentation/spcm#installation) 并确认 Spectrum Control Center 可识别 M4i.6631-x8。在仓库目录中执行：

```sh
uv sync --locked --extra hardware
uv run --locked --extra hardware spectrum-wave 10.2_waveforms.csv --scheme mpp
uv run --locked --extra hardware spectrum-wave 10.2_waveforms.csv --scheme pulse_shaped --trigger ext0 --trigger-mv 500 --loops 10
```

第一条回放命令通过软件触发播放一次。第二条在 EXT0 收到上升沿后连续播放十轮。默认设备为 `/dev/spcm0`，满量程为 50 Ω 负载下 ±100 mV。`--device`、`--amplitude-mv` 和 `--carrier-hz` 可调整设备、输出峰值和包络载频。`--loops 0` 持续播放，按 Ctrl+C 停止。

## 自定义输入

**原始采样 CSV** 每行一个 `[-1, 1]` 的数值，表头可省略，也可使用 `amplitude` 或 `ch0`。通过 `--sample-rate` 指定输入采样率，单位为 Sa/s。原始采样直接重采样并量化。

```sh
uv run --locked spectrum-wave raw.csv --sample-rate 250e6 --dry-run
```

**NumPy 数组** 可传形状为 `(N,)` 的原始采样，或形状为 `(N, 2)` 的幅相数据，两列依次为 Rabi 幅值与相位（弧度）。下面的例子可在项目的 Python 环境中离线运行。

```python
import numpy as np
from spectrum_wave import prepare_waveform

fs = 250e6
t = np.arange(1000) / fs
wave = 0.5 * np.sin(2 * np.pi * 10e6 * t)
codes, valid_samples = prepare_waveform(wave, sample_rate=fs)
```

在板卡主机上，可用 `play_waveform(wave, sample_rate=fs)` 上传并播放同一数组。它和 `prepare_waveform` 均位于 `spectrum_wave` 模块。

## 离线测试

```sh
uv run --locked python -m unittest discover -s tests -v
```
