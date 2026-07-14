"""Reproducible solver for 2019 CUMCM A, problem 1.

It follows the source problem's mm–mg–ms–MPa units and the MATLAB baseline's
mass-balance model, but calibrates every valve-open duration against explicit
numerical objectives instead of copying a reference-paper value.  The script is
intended for a task work directory containing ``附件3-弹性模量与压力.xlsx``.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numba import njit
from scipy.integrate import solve_ivp
from scipy.interpolate import CubicSpline


plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


DT_MS = 0.01
C = 0.85
PIPE_VOLUME_MM3 = 500.0 * np.pi * 5.0**2
INLET_AREA_MM2 = np.pi * 0.7**2
INITIAL_DENSITY = 0.85


@dataclass(frozen=True)
class ModelData:
    density_grid: np.ndarray
    pressure_grid: np.ndarray
    supply_density: float


@njit(cache=True)
def _pressure_from_density(
    density: float, density_grid: np.ndarray, pressure_grid: np.ndarray
) -> float:
    return float(np.interp(density, density_grid, pressure_grid))


@njit(cache=True)
def _density_derivative(
    time_ms: float,
    density: float,
    open_duration_ms: float,
    density_grid: np.ndarray,
    pressure_grid: np.ndarray,
    supply_density: float,
) -> float:
    pressure = _pressure_from_density(density, density_grid, pressure_grid)
    valve_phase = time_ms % (open_duration_ms + 10.0)
    valve_open = 1.0 if valve_phase <= open_duration_ms else 0.0
    injection_phase = time_ms % 100.0
    if injection_phase < 0.2:
        injection_flow = 100.0 * injection_phase
    elif injection_phase < 2.2:
        injection_flow = 20.0
    elif injection_phase <= 2.4:
        injection_flow = 240.0 - 100.0 * injection_phase
    else:
        injection_flow = 0.0
    inlet_mass_flow = (
        valve_open
        * C
        * INLET_AREA_MM2
        * np.sqrt(max(0.0, 2.0 * supply_density * (160.0 - pressure)))
    )
    return (inlet_mass_flow - density * injection_flow) / PIPE_VOLUME_MM3


@njit(cache=True)
def _simulate_summary(
    open_duration_ms: float,
    duration_ms: float,
    initial_density: float,
    density_grid: np.ndarray,
    pressure_grid: np.ndarray,
    supply_density: float,
) -> tuple[float, float, float, float]:
    """Fixed-step RK4 simulation; summary is taken from the last 100 ms."""
    density = initial_density
    steps = int(round(duration_ms / DT_MS))
    window_start = max(0.0, duration_ms - 100.0)
    pressure_sum = 0.0
    pressure_min = 1.0e9
    pressure_max = -1.0e9
    count = 0
    for step in range(steps):
        time_ms = step * DT_MS
        k1 = _density_derivative(
            time_ms, density, open_duration_ms, density_grid, pressure_grid, supply_density
        )
        k2 = _density_derivative(
            time_ms + DT_MS / 2.0,
            density + DT_MS * k1 / 2.0,
            open_duration_ms,
            density_grid,
            pressure_grid,
            supply_density,
        )
        k3 = _density_derivative(
            time_ms + DT_MS / 2.0,
            density + DT_MS * k2 / 2.0,
            open_duration_ms,
            density_grid,
            pressure_grid,
            supply_density,
        )
        k4 = _density_derivative(
            time_ms + DT_MS,
            density + DT_MS * k3,
            open_duration_ms,
            density_grid,
            pressure_grid,
            supply_density,
        )
        density += DT_MS * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        if time_ms + DT_MS >= window_start:
            pressure = _pressure_from_density(density, density_grid, pressure_grid)
            pressure_sum += pressure
            pressure_min = min(pressure_min, pressure)
            pressure_max = max(pressure_max, pressure)
            count += 1
    end_pressure = _pressure_from_density(density, density_grid, pressure_grid)
    return pressure_sum / count, pressure_max - pressure_min, end_pressure, density


@njit(cache=True)
def _simulate_trace(
    first_open_duration_ms: float,
    first_duration_ms: float,
    second_open_duration_ms: float,
    second_duration_ms: float,
    initial_density: float,
    density_grid: np.ndarray,
    pressure_grid: np.ndarray,
    supply_density: float,
    sample_every_steps: int,
) -> tuple[np.ndarray, np.ndarray]:
    total_steps = int(round((first_duration_ms + second_duration_ms) / DT_MS))
    points = total_steps // sample_every_steps + 1
    times = np.empty(points)
    pressures = np.empty(points)
    density = initial_density
    point = 0
    for step in range(total_steps):
        time_ms = step * DT_MS
        if time_ms < first_duration_ms:
            open_duration = first_open_duration_ms
            local_time = time_ms
        else:
            open_duration = second_open_duration_ms
            local_time = time_ms - first_duration_ms
        k1 = _density_derivative(local_time, density, open_duration, density_grid, pressure_grid, supply_density)
        k2 = _density_derivative(local_time + DT_MS / 2.0, density + DT_MS * k1 / 2.0, open_duration, density_grid, pressure_grid, supply_density)
        k3 = _density_derivative(local_time + DT_MS / 2.0, density + DT_MS * k2 / 2.0, open_duration, density_grid, pressure_grid, supply_density)
        k4 = _density_derivative(local_time + DT_MS, density + DT_MS * k3, open_duration, density_grid, pressure_grid, supply_density)
        density += DT_MS * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        if step % sample_every_steps == 0:
            times[point] = time_ms + DT_MS
            pressures[point] = _pressure_from_density(density, density_grid, pressure_grid)
            point += 1
    return times[:point], pressures[:point]


def _build_model_data(elasticity_path: Path) -> ModelData:
    raw = pd.read_excel(elasticity_path)
    pressure_values = raw.iloc[:, 0].to_numpy(dtype=float)
    modulus_values = raw.iloc[:, 1].to_numpy(dtype=float)
    elasticity = CubicSpline(pressure_values, modulus_values, extrapolate=True)
    lower = solve_ivp(
        lambda density, pressure: elasticity(float(pressure[0])) / density,
        (0.85, 0.80),
        [100.0],
        dense_output=True,
        rtol=1e-10,
        atol=1e-11,
    )
    upper = solve_ivp(
        lambda density, pressure: elasticity(float(pressure[0])) / density,
        (0.85, 0.89),
        [100.0],
        dense_output=True,
        rtol=1e-10,
        atol=1e-11,
    )
    density_grid = np.linspace(0.80, 0.89, 90_001)
    pressure_grid = np.where(
        density_grid < 0.85,
        lower.sol(density_grid)[0],
        upper.sol(density_grid)[0],
    )
    supply_density = float(np.interp(160.0, pressure_grid, density_grid))
    return ModelData(density_grid, pressure_grid, supply_density)


def _bisect_duration(objective, low: float, high: float, *, iterations: int = 20) -> float:
    lower_value = objective(low)
    upper_value = objective(high)
    if lower_value > 0.0 or upper_value < 0.0:
        raise ValueError("阀门开启时长的搜索区间未夹住目标压力。")
    for _ in range(iterations):
        middle = (low + high) / 2.0
        if objective(middle) < 0.0:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def solve(work_dir: Path) -> pd.DataFrame:
    model = _build_model_data(work_dir / "附件3-弹性模量与压力.xlsx")
    # Trigger JIT compilation before repeated calibration calls.
    _simulate_summary(0.3, 10.0, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)

    steady_horizon_ms = 8_000.0
    steady_100 = _bisect_duration(
        lambda duration: _simulate_summary(duration, steady_horizon_ms, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)[0] - 100.0,
        0.20,
        0.40,
    )
    steady_150 = _bisect_duration(
        lambda duration: _simulate_summary(duration, steady_horizon_ms, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)[0] - 150.0,
        0.60,
        0.90,
    )
    rows: list[dict[str, float | str]] = []
    for label, target, duration in (("100MPa稳态", 100.0, steady_100), ("150MPa稳态", 150.0, steady_150)):
        mean, peak_to_peak, end_pressure, _ = _simulate_summary(duration, steady_horizon_ms, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)
        rows.append({"工况": label, "开启时长(ms)": duration, "目标压力(MPa)": target, "控制时长(ms)": steady_horizon_ms, "目标时刻压力(MPa)": end_pressure, "末100ms均值(MPa)": mean, "末100ms峰峰值(MPa)": peak_to_peak, "目标误差(MPa)": abs(mean - target), "切回稳态开启时长(ms)": duration})
    for transition_ms in (2_000.0, 5_000.0, 10_000.0):
        transition_duration = _bisect_duration(
            lambda duration: _simulate_summary(duration, transition_ms, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)[2] - 150.0,
            0.55,
            1.10,
        )
        _, _, end_pressure, end_density = _simulate_summary(transition_duration, transition_ms, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density)
        mean, peak_to_peak, _, _ = _simulate_summary(steady_150, 2_000.0, end_density, model.density_grid, model.pressure_grid, model.supply_density)
        rows.append({"工况": f"{int(transition_ms / 1000)}秒过渡至150MPa", "开启时长(ms)": transition_duration, "目标压力(MPa)": 150.0, "控制时长(ms)": transition_ms, "目标时刻压力(MPa)": end_pressure, "末100ms均值(MPa)": mean, "末100ms峰峰值(MPa)": peak_to_peak, "目标误差(MPa)": abs(end_pressure - 150.0), "切回稳态开启时长(ms)": steady_150})
    result = pd.DataFrame(rows)
    result.to_csv(work_dir / "ques1_verified_control_results.csv", index=False, encoding="utf-8-sig")

    transition = result.iloc[2]
    times, pressures = _simulate_trace(float(transition["开启时长(ms)"]), float(transition["控制时长(ms)"]), steady_150, 2_000.0, INITIAL_DENSITY, model.density_grid, model.pressure_grid, model.supply_density, 100)
    trace = pd.DataFrame({"时间(ms)": times, "油管压力(MPa)": pressures})
    trace.to_csv(work_dir / "ques1_verified_transition_2s.csv", index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=220)
    ax.plot(times / 1000.0, pressures, linewidth=1.2, color="#1f77b4")
    ax.axvline(float(transition["控制时长(ms)"]) / 1000.0, color="#d62728", linestyle="--", label="switch to 150 MPa steady control")
    ax.axhline(150.0, color="#555555", linestyle=":", label="150 MPa target")
    ax.set(xlabel="Time (s)", ylabel="Pressure (MPa)", title="Problem 1: 2-s transition and steady-state switch")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(work_dir / "ques1_verified_transition_2s.png")
    plt.close(fig)
    shutil.copyfile(Path(__file__), work_dir / "q1_verified_control.py")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="复算 2019 CUMCM A 题问题一单向阀控制策略")
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    result = solve(args.work_dir.resolve())
    print(result.to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
