#!/usr/bin/env python3
"""
频谱到波形转换模块 (Spectrum to Waveform Conversion)

从SPECTRUM类型的波形数据中，通过IFFT（逆快速傅里叶变换）重建时域波形。
这是INS前端orbit-algo.js中spectrum2Wave函数的Python实现。
"""

import numpy as np
from typing import Dict, List, Tuple, Optional


def spectrum_to_wave(wave_data: Dict) -> Optional[np.ndarray]:
    """
    从频谱数据重建时域波形（IFFT反变换）

    Args:
        wave_data: 解析后的波形数据字典，包含:
            - spectrum: {index: [], amp: [], ph: []}
            - freq: 采样频率
            - samples: 采样点数

    Returns:
        重建的时域波形数组，如果失败则返回None
    """
    spectrum = wave_data.get('spectrum')
    if not spectrum or not isinstance(spectrum, dict):
        return None

    freq = wave_data.get('freq')
    samples = wave_data.get('samples')

    if not freq or not samples:
        return None

    index = spectrum.get('index', [])
    amp = spectrum.get('amp', [])
    ph = spectrum.get('ph', [])

    if not index or not amp or not ph:
        return None

    # 步骤1: 将稀疏频谱转换为完整FFT数组（spectrum2Arr）
    line_count = samples // 2
    FFT_Amplitude = np.zeros(line_count)
    FFT_Phase = np.zeros(line_count)

    interval = freq / samples

    for i in range(len(index)):
        f = index[i] * freq / samples  # 计算实际频率
        line = int(f / interval + interval * 0.01)  # 频率bin索引

        if line < samples // 2:
            FFT_Amplitude[line] = amp[i]
            FFT_Phase[line] = np.pi * (ph[i] / 180.0)  # 度转弧度

    # 步骤2: IFFT反变换重建波形（initWaveByFFT）
    wave = ifft_to_wave(FFT_Amplitude, FFT_Phase)

    return wave


def ifft_to_wave(fft_amplitude: np.ndarray, fft_phase: np.ndarray) -> np.ndarray:
    """
    通过IFFT从频谱幅值/相位重建时域波形

    这是orbit-algo.js中initWaveByFFT函数的Python实现。

    Args:
        fft_amplitude: FFT幅值数组
        fft_phase: FFT相位数组（弧度）

    Returns:
        重建的时域波形数组
    """
    # 计算长度（2的幂次）
    mi = np.log2(len(fft_amplitude) * 2)
    length = int(2 ** mi)
    half = length // 2

    # 初始化复数数组
    complex_spectrum = np.zeros(length, dtype=complex)

    # 填充频谱数据（幅值/相位 → 复数）
    for i in range(len(fft_amplitude)):
        pp = fft_amplitude[i] / 4.0
        phase = fft_phase[i]

        # 实部和虚部
        real = pp * np.sin(phase)
        imag = -pp * np.cos(phase)

        complex_spectrum[i] = complex(real, imag)

    # 镜像对称填充（满足IFFT要求）
    for i in range(1, half):
        complex_spectrum[length - i] = np.conj(complex_spectrum[i])

    # IFFT反变换
    wave = np.fft.ifft(complex_spectrum).real

    return wave


def extract_time_domain_wave(wave_data: Dict) -> Optional[np.ndarray]:
    """
    从波形数据中提取时域波形

    优先级：
    1. 如果是SHIFT类型，直接从waveDataShift.wave获取
    2. 如果是SPECTRUM类型，通过IFFT重建

    Args:
        wave_data: 解析后的波形数据字典

    Returns:
        时域波形数组，失败返回None
    """
    wave_type = wave_data.get('waveType', 'UNKNOWN')

    # 优先：SHIFT类型有原始时域数据
    if wave_type == 'SHIFT' and 'waveDataShift' in wave_data:
        wave_data_shift = wave_data['waveDataShift']
        if isinstance(wave_data_shift, dict) and 'wave' in wave_data_shift:
            wave = wave_data_shift['wave']
            if isinstance(wave, list) and len(wave) > 0:
                return np.array(wave)

    # 如果是SPECTRUM类型，通过IFFT重建
    if wave_type == 'SPECTRUM' or 'spectrum' in wave_data:
        return spectrum_to_wave(wave_data)

    # COMPLEX类型（包含多种波形）
    if 'complex' in wave_data:
        complex_data = wave_data['complex']

        # 优先尝试SHIFT
        if isinstance(complex_data, dict) and 'waveDataShift' in complex_data:
            wave_data_shift = complex_data['waveDataShift']
            if isinstance(wave_data_shift, dict) and 'wave' in wave_data_shift:
                wave = wave_data_shift['wave']
                if isinstance(wave, list) and len(wave) > 0:
                    return np.array(wave)

        # 尝试从频谱重建
        if isinstance(complex_data, dict) and 'spectrum' in complex_data:
            # 构建临时字典用于spectrum_to_wave
            temp_data = {
                'spectrum': complex_data['spectrum'],
                'freq': wave_data.get('freq'),
                'samples': wave_data.get('samples')
            }
            return spectrum_to_wave(temp_data)

    return None


def get_orbit_points(x_wave: np.ndarray, y_wave: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    从X/Y时域波形合成轨迹点

    Args:
        x_wave: X通道时域波形
        y_wave: Y通道时域波形

    Returns:
        (orbit_points, x_wave, y_wave)
        - orbit_points: 轨迹点数组 [[x1,y1], [x2,y2], ...]
        - x_wave: X波形（可能经过处理）
        - y_wave: Y波形（可能经过处理）
    """
    # 确保长度一致
    min_len = min(len(x_wave), len(y_wave))
    x_wave = x_wave[:min_len]
    y_wave = y_wave[:min_len]

    # 合成轨迹点
    orbit_points = np.column_stack((x_wave, y_wave))

    # 旋转45度（与INS前端保持一致）
    angle = np.pi / 4
    rotation_matrix = np.array([
        [np.cos(angle), -np.sin(angle)],
        [np.sin(angle), np.cos(angle)]
    ])

    orbit_points = np.dot(orbit_points, rotation_matrix.T)

    return orbit_points, x_wave, y_wave
