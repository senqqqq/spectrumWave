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

同一时间戳的两行可以定义相位跳变。跨越 2π 的连续扫描请提供展开后的相位。

## 输入采样率与板卡回放网格

`--sample-rate`（Python 参数 `sample_rate`）表示**输入数据的等间隔采样率**，单位为 Sa/s。板卡回放固定为 **1.25 GSa/s**，相邻输出点间隔 **0.8 ns**。

- **幅相 CSV 含 `time_us`**：省略 `--sample-rate`。程序直接使用所选方案的时间戳，以首个时间戳为起点、最后一个时间戳为结束边界，允许相邻点的间隔不同。
- **等间隔 CSV 或 NumPy 数组没有时间列**：指定输入采样率。第 `i` 行对应时间 `i / sample_rate` 秒（从 0 开始）。例如，每隔 4 ns 采一个点，就传 `--sample-rate 250e6`。

| 输入数据 | 如何生成板卡采样点 |
| --- | --- |
| 原始波形，输入低于 1.25 GSa/s | 在相邻幅值间做线性插值，每 0.8 ns 取值；最后一个输入采样周期保持末值。 |
| 原始波形，输入等于 1.25 GSa/s | 直接量化原始采样。 |
| 原始波形，输入高于 1.25 GSa/s | 用 `scipy.signal.resample` 做傅里叶降采样，该算法将整段输入视为一个周期。 |
| Rabi 幅值与相位 | 在 0.8 ns 网格上分别对归一化幅值和相位做分段线性插值，再在每个输出时刻计算带载波的波形。 |

例如，`pulse_shaped` 的 991 个幅相控制点相隔约 **26.138 ns**，对应约 **38.26 MSa/s** 的包络采样率。CSV 已提供 `time_us`，因此下面的命令只需选择方案。程序每隔 0.8 ns 取一次幅值和相位，并在该时刻计算默认的 100 MHz 载波，得到 **32346 个有效 DAC 点**。

```sh
uv run --locked spectrum-wave 10.2_waveforms.csv --scheme pulse_shaped --dry-run
```

## 32 点对齐与循环播放周期

在本程序使用的标准回放模式下，板卡要求上传长度至少为 32 个 DAC 点，且为 32 的整数倍。程序在重采样完成后保留全部有效点，按需在**末尾自动补 0**，补齐后再上传。已经对齐的波形直接上传，输入 CSV 或 NumPy 数组无需手动补齐。

循环播放时，板卡每轮都会输出整段板载波形，**补零也计入循环周期**。以 `pulse_shaped` 为例，32346 个有效点末尾补 6 个零点，实际上传 32352 点。每点占 0.8 ns，因此每轮周期为 **32352 × 0.8 ns = 25.8816 µs**，其中最后 **4.8 ns** 为补零时段。

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

### 用 Python 定义并播放 NumPy 波形

在项目根目录运行 `my_wave.py`。默认示例使用 250 MSa/s 的输入采样率定义 10 MHz 正弦波。加 `--envelope` 可试用幅相数组，以平滑包络调制 100 MHz 载波。

```sh
uv run --locked python my_wave.py --dry-run
uv run --locked python my_wave.py --envelope --dry-run
```

在板卡主机上运行 `uv run --locked --extra hardware python my_wave.py`，即可将示例上传到 CH0 并播放一次。在自己的脚本中可直接调用同一个接口。

```python
import numpy as np
from spectrum_wave import play_waveform

fs = 250e6
t = np.arange(1000) / fs
wave = 0.5 * np.sin(2 * np.pi * 10e6 * t)
play_waveform(wave, sample_rate=fs, dry_run=True)
```

### 将 CSV 读成 NumPy 数组再编辑

`read_waveform_csv()` 返回可编辑的 `float64` 数组。列的顺序如下，`N` 为选中波形的行数。

| CSV 内容 | 数组形状和列顺序 | 回放时的时间轴 |
| --- | --- | --- |
| 单列原始波形 | `(N,)` 幅值 | 传 `sample_rate` |
| 幅相数据 | `(N, 2)`，依次为 `rabi_khz, phase_rad` | 传 `sample_rate` |
| 带时间戳的幅相数据 | `(N, 3)`，依次为 `time_us, rabi_khz, phase_rad` | 使用首列，省略 `sample_rate` |

例如，读出 `pulse_shaped` 后给整个脉冲增加 π/2 的相位。数组保留原始时间戳和幅相值，回放时才做归一化、插值和量化。

```python
import numpy as np
from spectrum_wave import play_waveform, read_waveform_csv

pulse = read_waveform_csv("10.2_waveforms.csv", scheme="pulse_shaped")
pulse[:, 2] += np.pi / 2
play_waveform(pulse, dry_run=True)
```

要查看将要上传的 DAC 数组及有效点数，也可调用 `codes, valid_samples = prepare_waveform(pulse)`，该函数位于 `spectrum_wave` 模块。

## 离线测试

```sh
uv run --locked python -m unittest discover -s tests -v
```
