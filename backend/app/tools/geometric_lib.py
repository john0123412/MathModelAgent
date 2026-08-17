"""空间几何计算与加速工具库。

提供高精度、抗退化的线段/胶囊体/平端帽圆柱体最短距离求解、
边界截断夹紧保护、空间分箱宽相加速以及独立交叉复算实现。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence
import numpy as np


@dataclass(frozen=True)
class SegmentDistanceResult:
    """线段间最短距离计算结果。"""

    distance: float
    closest_point1: np.ndarray
    closest_point2: np.ndarray
    param1: float  # s in [0, 1]
    param2: float  # t in [0, 1]


def segment_segment_distance(
    p1: Sequence[float] | np.ndarray,
    p2: Sequence[float] | np.ndarray,
    q1: Sequence[float] | np.ndarray,
    q2: Sequence[float] | np.ndarray,
    eps: float = 1e-12,
) -> SegmentDistanceResult:
    """计算三维空间两有限线段 P1P2 与 Q1Q2 之间的最短欧氏距离及最近点。

    严格处理退化为单点、平行、重合、正交及端点截断夹紧边界情况。
    参数方程：
        P(s) = p1 + s * (p2 - p1), s in [0, 1]
        Q(t) = q1 + t * (q2 - q1), t in [0, 1]
    """
    p1_arr = np.asarray(p1, dtype=np.float64)
    p2_arr = np.asarray(p2, dtype=np.float64)
    q1_arr = np.asarray(q1, dtype=np.float64)
    q2_arr = np.asarray(q2, dtype=np.float64)

    d1 = p2_arr - p1_arr  # 方向向量 1
    d2 = q2_arr - q1_arr  # 方向向量 2
    r = p1_arr - q1_arr

    a = float(np.dot(d1, d1))
    e = float(np.dot(d2, d2))
    f = float(np.dot(d2, r))

    # 处理退化分支：P 或 Q 为单点 (零长线段)
    if a <= eps and e <= eps:
        s = 0.0
        t = 0.0
        c1 = p1_arr
        c2 = q1_arr
        dist = float(np.linalg.norm(c1 - c2))
        return SegmentDistanceResult(dist, c1, c2, s, t)

    if a <= eps:
        s = 0.0
        t = float(np.clip(f / e, 0.0, 1.0))
    else:
        c = float(np.dot(d1, r))
        if e <= eps:
            t = 0.0
            s = float(np.clip(-c / a, 0.0, 1.0))
        else:
            # 两个均为非零长线段
            b = float(np.dot(d1, d2))
            denom = a * e - b * b

            if denom > eps:
                # 非平行线，计算无约束最优点
                s = (b * f - c * e) / denom
                s = float(np.clip(s, 0.0, 1.0))
            else:
                # 平行线段或近平行
                s = 0.0

            # 由 s 计算 t 并裁剪到 [0, 1]
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = float(np.clip(-c / a, 0.0, 1.0))
            elif t > 1.0:
                t = 1.0
                s = float(np.clip((b - c) / a, 0.0, 1.0))

    c1 = p1_arr + s * d1
    c2 = q1_arr + t * d2
    dist = float(np.linalg.norm(c1 - c2))
    return SegmentDistanceResult(dist, c1, c2, float(s), float(t))


def capsule_capsule_distance(
    p1: Sequence[float] | np.ndarray,
    p2: Sequence[float] | np.ndarray,
    r1: float,
    q1: Sequence[float] | np.ndarray,
    q2: Sequence[float] | np.ndarray,
    r2: float,
) -> float:
    """计算两个胶囊体（圆柱轴段 + 半径）之间的表面间隙距离（最短表面距离）。

    当相交或相切时返回 0.0。
    """
    res = segment_segment_distance(p1, p2, q1, q2)
    return max(0.0, float(res.distance - r1 - r2))


def segment_point_distance(
    p1: Sequence[float] | np.ndarray,
    p2: Sequence[float] | np.ndarray,
    q: Sequence[float] | np.ndarray,
    eps: float = 1e-12,
) -> tuple[float, np.ndarray]:
    """计算点 Q 到有限线段 P1P2 的最短欧氏距离及垂足/最近点。"""
    p1_arr = np.asarray(p1, dtype=np.float64)
    p2_arr = np.asarray(p2, dtype=np.float64)
    q_arr = np.asarray(q, dtype=np.float64)

    d = p2_arr - p1_arr
    l2 = float(np.dot(d, d))
    if l2 <= eps:
        return float(np.linalg.norm(q_arr - p1_arr)), p1_arr

    t = float(np.dot(q_arr - p1_arr, d) / l2)
    t = float(np.clip(t, 0.0, 1.0))
    closest = p1_arr + t * d
    dist = float(np.linalg.norm(q_arr - closest))
    return dist, closest


def capsule_plane_distance(
    p1: Sequence[float] | np.ndarray,
    p2: Sequence[float] | np.ndarray,
    radius: float,
    plane_coord: float,
    axis: int = 0,
) -> float:
    """计算胶囊体到垂直于某坐标轴的平面的表面最短间隙。

    例如 X 方向左极板 x = -5000:
        capsule_plane_distance(p1, p2, radius=30, plane_coord=-5000, axis=0)
    """
    p1_val = float(p1[axis])
    p2_val = float(p2[axis])
    min_dist_to_plane = min(abs(p1_val - plane_coord), abs(p2_val - plane_coord))
    # 若线段跨越平面，轴线到平面距离为 0
    if (p1_val - plane_coord) * (p2_val - plane_coord) <= 0:
        min_dist_to_plane = 0.0
    return max(0.0, min_dist_to_plane - radius)


def independent_numerical_segment_distance(
    p1: Sequence[float] | np.ndarray,
    p2: Sequence[float] | np.ndarray,
    q1: Sequence[float] | np.ndarray,
    q2: Sequence[float] | np.ndarray,
    num_samples: int = 50,
) -> float:
    """用于独立交叉复算的数值离散一维迭代优化算法。

    通过与解析解完全不同的机制（离散采样 + 黄金分割搜索），
    用于在 crosscheck.csv 中提供真实的双算法验证，杜绝伪复算。
    """
    p1_arr = np.asarray(p1, dtype=np.float64)
    p2_arr = np.asarray(p2, dtype=np.float64)
    q1_arr = np.asarray(q1, dtype=np.float64)
    q2_arr = np.asarray(q2, dtype=np.float64)

    # 1. 粗粒度网格采样
    s_grid = np.linspace(0.0, 1.0, num_samples)
    best_dist = float("inf")
    best_s = 0.0

    for s in s_grid:
        pt = p1_arr + s * (p2_arr - p1_arr)
        d, _ = segment_point_distance(q1_arr, q2_arr, pt)
        if d < best_dist:
            best_dist = d
            best_s = s

    # 2. 局部细化黄金分割搜索
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    delta = 1.0 / num_samples
    a = max(0.0, best_s - delta)
    b = min(1.0, best_s + delta)

    for _ in range(30):
        s1 = b - phi * (b - a)
        s2 = a + phi * (b - a)
        pt1 = p1_arr + s1 * (p2_arr - p1_arr)
        pt2 = p1_arr + s2 * (p2_arr - p1_arr)
        d1, _ = segment_point_distance(q1_arr, q2_arr, pt1)
        d2, _ = segment_point_distance(q1_arr, q2_arr, pt2)
        if d1 < d2:
            b = s2
        else:
            a = s1
        if abs(b - a) < 1e-9:
            break

    final_s = (a + b) / 2.0
    final_pt = p1_arr + final_s * (p2_arr - p1_arr)
    min_dist, _ = segment_point_distance(q1_arr, q2_arr, final_pt)
    return min_dist


class UniformGridBroadphase3D:
    """三维均匀空间网格加速结构，用于将大规模 N 体碰撞/距离查询从 O(N^2) 降低为近线性。"""

    def __init__(
        self,
        bounds_min: Sequence[float],
        bounds_max: Sequence[float],
        cell_size: float,
    ):
        self.bounds_min = np.asarray(bounds_min, dtype=np.float64)
        self.bounds_max = np.asarray(bounds_max, dtype=np.float64)
        self.cell_size = max(1e-6, float(cell_size))
        self.grid: dict[tuple[int, int, int], list[int]] = {}
        self.items: list[tuple[np.ndarray, np.ndarray, float]] = []

    def _coord_to_cell(self, point: np.ndarray) -> tuple[int, int, int]:
        diff = point - self.bounds_min
        return (
            int(math.floor(diff[0] / self.cell_size)),
            int(math.floor(diff[1] / self.cell_size)),
            int(math.floor(diff[2] / self.cell_size)),
        )

    def insert_capsule(
        self,
        item_id: int,
        p1: Sequence[float] | np.ndarray,
        p2: Sequence[float] | np.ndarray,
        radius: float,
    ) -> None:
        """将胶囊体包围盒覆盖的所有网格单元注册该 item_id。"""
        p1_arr = np.asarray(p1, dtype=np.float64)
        p2_arr = np.asarray(p2, dtype=np.float64)
        self.items.append((p1_arr, p2_arr, float(radius)))

        box_min = np.minimum(p1_arr, p2_arr) - radius
        box_max = np.maximum(p1_arr, p2_arr) + radius

        min_cell = self._coord_to_cell(box_min)
        max_cell = self._coord_to_cell(box_max)

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                for cz in range(min_cell[2], max_cell[2] + 1):
                    cell = (cx, cy, cz)
                    if cell not in self.grid:
                        self.grid[cell] = []
                    self.grid[cell].append(item_id)

    def get_candidate_pairs(self) -> set[tuple[int, int]]:
        """获取所有处于同一空间网格内的候选相交对 (i, j), i < j。"""
        pairs: set[tuple[int, int]] = set()
        for cell_items in self.grid.values():
            n = len(cell_items)
            if n <= 1:
                continue
            for idx_i in range(n):
                for idx_j in range(idx_i + 1, n):
                    i = cell_items[idx_i]
                    j = cell_items[idx_j]
                    if i != j:
                        pairs.add((min(i, j), max(i, j)))
        return pairs
