"""Colour maths: sRGB (D65) -> CIE Lab and CIEDE2000, vectorised with numpy.

CIEDE2000 follows Sharma, Wu & Dalal (2005), "The CIEDE2000 colour-difference formula:
implementation notes, supplementary test data, and mathematical observations"; the 34 test
pairs from their Table 1 are in tests/test_color.py.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_M_RGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
)
_WHITE_D65 = np.array([0.95047, 1.0, 1.08883])


def srgb_to_lab(rgb: NDArray) -> FloatArray:
    """sRGB in [0, 1] (any shape (..., 3)) -> CIE Lab (D65)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    lin = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = lin @ _M_RGB_TO_XYZ.T / _WHITE_D65
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    lab_l = 116 * f[..., 1] - 16
    lab_a = 500 * (f[..., 0] - f[..., 1])
    lab_b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([lab_l, lab_a, lab_b], axis=-1)


def lab_to_srgb(lab: NDArray) -> FloatArray:
    """CIE Lab (D65) -> sRGB in [0, 1], clipped to gamut."""
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f**3 > eps, f**3, (116 * f - 16) / kappa)
    xyz[..., 1] = np.where(lab[..., 0] > kappa * eps, fy**3, lab[..., 0] / kappa)
    xyz = xyz * _WHITE_D65
    lin = xyz @ np.linalg.inv(_M_RGB_TO_XYZ).T
    lin = np.clip(lin, 0, 1)
    rgb = np.where(lin > 0.0031308, 1.055 * lin ** (1 / 2.4) - 0.055, 12.92 * lin)
    return np.clip(rgb, 0, 1)


def hex_to_rgb(h: str) -> FloatArray:
    h = h.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"not a #rrggbb colour: {h!r}")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)])


def rgb_to_hex(rgb: NDArray) -> str:
    vals = np.clip(np.rint(np.asarray(rgb, dtype=np.float64) * 255), 0, 255).astype(int)
    return "#{:02x}{:02x}{:02x}".format(*vals)


def hex_to_lab(h: str) -> FloatArray:
    return srgb_to_lab(hex_to_rgb(h))


def lab_to_hex(lab: NDArray) -> str:
    return rgb_to_hex(lab_to_srgb(lab))


def delta_e76(lab1: NDArray, lab2: NDArray) -> FloatArray:
    return np.linalg.norm(np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64), axis=-1)


def delta_e2000(
    lab1: NDArray, lab2: NDArray, kl: float = 1.0, kc: float = 1.0, kh: float = 1.0
) -> FloatArray:
    """CIEDE2000 between Lab arrays of shape (..., 3). Returns shape (...)."""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    c_bar7 = c_bar**7
    g = 0.5 * (1 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))
    a1p = (1 + g) * a1
    a2p = (1 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    h1p = np.where((a1p == 0) & (b1 == 0), 0.0, h1p)
    h2p = np.where((a2p == 0) & (b2 == 0), 0.0, h2p)

    d_lp = l2 - l1
    d_cp = c2p - c1p
    cprod = c1p * c2p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, dh)
    dh = np.where(dh < -180, dh + 360, dh)
    dh = np.where(cprod == 0, 0.0, dh)
    d_hp = 2 * np.sqrt(cprod) * np.sin(np.radians(dh / 2))

    l_bar_p = (l1 + l2) / 2
    c_bar_p = (c1p + c2p) / 2
    hsum = h1p + h2p
    h_bar_p = np.where(
        np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)
    )
    h_bar_p = np.where(cprod == 0, hsum, h_bar_p)

    t = (
        1
        - 0.17 * np.cos(np.radians(h_bar_p - 30))
        + 0.24 * np.cos(np.radians(2 * h_bar_p))
        + 0.32 * np.cos(np.radians(3 * h_bar_p + 6))
        - 0.20 * np.cos(np.radians(4 * h_bar_p - 63))
    )
    d_theta = 30 * np.exp(-(((h_bar_p - 275) / 25) ** 2))
    c_bar_p7 = c_bar_p**7
    r_c = 2 * np.sqrt(c_bar_p7 / (c_bar_p7 + 25.0**7))
    s_l = 1 + (0.015 * (l_bar_p - 50) ** 2) / np.sqrt(20 + (l_bar_p - 50) ** 2)
    s_c = 1 + 0.045 * c_bar_p
    s_h = 1 + 0.015 * c_bar_p * t
    r_t = -np.sin(np.radians(2 * d_theta)) * r_c

    tl = d_lp / (kl * s_l)
    tc = d_cp / (kc * s_c)
    th = d_hp / (kh * s_h)
    return np.sqrt(tl**2 + tc**2 + th**2 + r_t * tc * th)


def hex_delta_e2000(h1: str, h2: str) -> float:
    return float(delta_e2000(hex_to_lab(h1), hex_to_lab(h2)))
