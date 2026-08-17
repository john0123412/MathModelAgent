"""Unit tests for geometric_lib.py."""

from __future__ import annotations

import unittest
import numpy as np

from app.tools.geometric_lib import (
    SegmentDistanceResult,
    capsule_capsule_distance,
    capsule_plane_distance,
    independent_numerical_segment_distance,
    segment_point_distance,
    segment_segment_distance,
    UniformGridBroadphase3D,
)


class TestGeometricLib(unittest.TestCase):
    """Test geometric distance functions, protections, and spatial acceleration."""

    def test_segment_segment_distance_skew(self) -> None:
        """Test standard skewed non-intersecting segments."""
        # P along X axis from (0, 0, 0) to (10, 0, 0)
        # Q along Y axis from (5, -5, 2) to (5, 5, 2)
        p1 = [0.0, 0.0, 0.0]
        p2 = [10.0, 0.0, 0.0]
        q1 = [5.0, -5.0, 2.0]
        q2 = [5.0, 5.0, 2.0]

        res = segment_segment_distance(p1, p2, q1, q2)
        self.assertIsInstance(res, SegmentDistanceResult)
        self.assertAlmostEqual(res.distance, 2.0, places=6)
        np.testing.assert_allclose(res.closest_point1, [5.0, 0.0, 0.0], atol=1e-6)
        np.testing.assert_allclose(res.closest_point2, [5.0, 0.0, 2.0], atol=1e-6)
        self.assertAlmostEqual(res.param1, 0.5, places=6)
        self.assertAlmostEqual(res.param2, 0.5, places=6)

    def test_segment_segment_distance_parallel(self) -> None:
        """Test parallel segments."""
        p1 = [0.0, 0.0, 0.0]
        p2 = [10.0, 0.0, 0.0]
        q1 = [0.0, 3.0, 4.0]
        q2 = [10.0, 3.0, 4.0]

        res = segment_segment_distance(p1, p2, q1, q2)
        # sqrt(3^2 + 4^2) = 5
        self.assertAlmostEqual(res.distance, 5.0, places=6)

    def test_segment_segment_distance_degenerate_points(self) -> None:
        """Test degenerate zero-length segments."""
        p1 = [1.0, 2.0, 3.0]
        p2 = [1.0, 2.0, 3.0]
        q1 = [4.0, 6.0, 3.0]
        q2 = [4.0, 6.0, 3.0]

        res = segment_segment_distance(p1, p2, q1, q2)
        # sqrt((4-1)^2 + (6-2)^2) = 5
        self.assertAlmostEqual(res.distance, 5.0, places=6)

        # One point, one segment
        q3 = [4.0, 10.0, 3.0]
        res2 = segment_segment_distance(p1, p2, q1, q3)
        self.assertAlmostEqual(res2.distance, 5.0, places=6)

    def test_segment_segment_clamped_endpoints(self) -> None:
        """Test that segment points outside infinite lines are properly clamped to endpoints."""
        p1 = [0.0, 0.0, 0.0]
        p2 = [2.0, 0.0, 0.0]
        q1 = [5.0, 4.0, 0.0]
        q2 = [10.0, 4.0, 0.0]

        res = segment_segment_distance(p1, p2, q1, q2)
        # Closest on P is (2, 0, 0), on Q is (5, 4, 0)
        # Distance = sqrt((5-2)^2 + 4^2) = 5
        self.assertAlmostEqual(res.distance, 5.0, places=6)
        np.testing.assert_allclose(res.closest_point1, [2.0, 0.0, 0.0], atol=1e-6)
        np.testing.assert_allclose(res.closest_point2, [5.0, 4.0, 0.0], atol=1e-6)

    def test_capsule_capsule_distance(self) -> None:
        """Test surface gap between capsules."""
        p1 = [0.0, 0.0, 0.0]
        p2 = [10.0, 0.0, 0.0]
        r1 = 30.0

        # Non-intersecting capsule
        q1 = [5.0, 100.0, 0.0]
        q2 = [5.0, 200.0, 0.0]
        r2 = 30.0
        gap = capsule_capsule_distance(p1, p2, r1, q1, q2, r2)
        # Segment distance = 100, gap = 100 - 30 - 30 = 40
        self.assertAlmostEqual(gap, 40.0, places=6)

        # Intersecting capsule (gap should be 0.0)
        q3 = [5.0, 50.0, 0.0]
        q4 = [5.0, 150.0, 0.0]
        gap_intersect = capsule_capsule_distance(p1, p2, r1, q3, q4, r2)
        self.assertEqual(gap_intersect, 0.0)

    def test_segment_point_distance(self) -> None:
        """Test point to segment distance."""
        p1 = [0.0, 0.0, 0.0]
        p2 = [10.0, 0.0, 0.0]
        q = [5.0, 12.0, 0.0]

        dist, pt = segment_point_distance(p1, p2, q)
        self.assertAlmostEqual(dist, 12.0, places=6)
        np.testing.assert_allclose(pt, [5.0, 0.0, 0.0], atol=1e-6)

        # Clamped beyond end
        q_past = [15.0, 12.0, 0.0]
        dist_past, pt_past = segment_point_distance(p1, p2, q_past)
        # sqrt(5^2 + 12^2) = 13
        self.assertAlmostEqual(dist_past, 13.0, places=6)
        np.testing.assert_allclose(pt_past, [10.0, 0.0, 0.0], atol=1e-6)

    def test_capsule_plane_distance(self) -> None:
        """Test distance from capsule to plane."""
        p1 = [-4000.0, 100.0, 200.0]
        p2 = [-3000.0, 100.0, 200.0]
        radius = 30.0
        plane_coord = -5000.0

        # Min dist on x is abs(-4000 - (-5000)) = 1000, gap = 1000 - 30 = 970
        gap = capsule_plane_distance(p1, p2, radius, plane_coord, axis=0)
        self.assertAlmostEqual(gap, 970.0, places=6)

    def test_independent_numerical_crosscheck(self) -> None:
        """Test that independent numerical 1D optimization matches analytical solver."""
        p1 = np.array([123.4, 567.8, -910.1])
        p2 = np.array([987.6, -543.2, 101.2])
        q1 = np.array([456.7, -890.1, 234.5])
        q2 = np.array([-123.4, 678.9, -345.6])

        res_analytical = segment_segment_distance(p1, p2, q1, q2)
        dist_numerical = independent_numerical_segment_distance(p1, p2, q1, q2, num_samples=60)

        self.assertAlmostEqual(res_analytical.distance, dist_numerical, places=4)

    def test_uniform_grid_broadphase_3d(self) -> None:
        """Test spatial partitioning acceleration."""
        grid = UniformGridBroadphase3D(
            bounds_min=[-5000.0, -5000.0, -5000.0],
            bounds_max=[5000.0, 5000.0, 5000.0],
            cell_size=500.0,
        )

        # Two nearby capsules in the center
        grid.insert_capsule(0, [0.0, 0.0, 0.0], [100.0, 0.0, 0.0], 30.0)
        grid.insert_capsule(1, [50.0, 50.0, 0.0], [50.0, 150.0, 0.0], 30.0)

        # One far-away capsule
        grid.insert_capsule(2, [4000.0, 4000.0, 4000.0], [4100.0, 4000.0, 4000.0], 30.0)

        pairs = grid.get_candidate_pairs()
        self.assertIn((0, 1), pairs)
        self.assertNotIn((0, 2), pairs)
        self.assertNotIn((1, 2), pairs)


if __name__ == "__main__":
    unittest.main()
