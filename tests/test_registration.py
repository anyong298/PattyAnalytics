import numpy as np
import pcl

from patty import conversions
from patty.registration import registration
from patty.utils import BoundingBox
from scripts.registration import registrationPipeline

from nose.tools import assert_true
from numpy.testing import (assert_array_equal, assert_array_almost_equal,
                           assert_array_less)
from sklearn.utils.extmath import cartesian
import unittest


class TestPolygon(unittest.TestCase):

    def setUp(self):
        self.poly = [[0., 0.], [1., 0.], [0.4, 0.4], [1., 1.], [0., 1.]]
        self.points = [[0., 0.], [0.5, 0.2], [1.1, 1.1], [0.2, 1.1]]

    def testInPolygon(self):
        ''' Test whether the point_in_polygon2d behaves as expected. '''
        in_polygon = registration.point_in_polygon2d(self.points, self.poly)
        assert_array_equal(in_polygon, [False, True, False, False],
                           "points expected in polygon not matched")

    def testScalePolygon(self):
        ''' Test whether scaling up the polygon works '''
        newpoly = registration.scale_points(self.poly, 1.3)
        self.assertEqual(len(newpoly), len(self.poly),
                         "number of polygon points is altered when scaling")
        assert_array_equal(self.poly[0], [.0, .0],
                           "original polygon is altered when scaling")
        assert_array_less(newpoly[0], self.poly[0],
                          "small polygon points do not shrink when scaling up")
        assert_array_less(newpoly[3], self.poly[3],
                          "large polygon points do not grow when scaling up")
        in_scaled_polygon = registration.point_in_polygon2d(
            self.points, newpoly)
        assert_true(np.all(in_scaled_polygon),
                    "not all points are in polygon when scaling up")


class TestCutoutPointCloud(unittest.TestCase):

    def setUp(self):
        self.footprint = [[0., 0.], [1., 0.], [0.4, 0.4], [1., 1.], [0., 1.]]
        self.offset = [-0.01, -0.01, -0.01]
        points = np.array([[0., 0.], [0.5, 0.2], [1.1, 1.1], [0.2, 1.1]])
        data = np.zeros((4, 6), dtype=np.float32)
        data[:, :2] = points
        self.pc = pcl.PointCloudXYZRGB(data)
        conversions.register(self.pc, offset=self.offset)

    def testCutOutFromFootprint(self):
        ''' Test whether a cutout from a pointcloud gets the right points '''
        pc_fp = registration.intersect_polgyon2d(self.pc, self.footprint)
        self.assertEqual(pc_fp.size, 1,
                         "number of points expected in polygon not matched")
        assert_array_almost_equal(pc_fp[0], [0.5, 0.2, 0., 0., 0., 0.],
                                  "point that should be matched was modified")
        assert_array_equal(pc_fp.offset, self.offset,
                           "offset changed by intersection with polygon")


class TestCenter(unittest.TestCase):

    def setUp(self):
        data = np.array(
            [[1, 1, 1, 1, 1, 1], [3, 3, 3, 1, 1, 1]], dtype=np.float32)
        self.pc = pcl.PointCloudXYZRGB(data)

    def testCenter(self):
        ''' test whether pointcloud can be centered around zero '''
        # Baseline: original center
        bb = BoundingBox(points=np.asarray(self.pc))
        assert_array_equal(bb.center, [2., 2., 2.],
                           "original bounding box center"
                           " is not center of input")

        # New center
        registration.center_boundingbox(self.pc)
        bb_new = BoundingBox(points=np.asarray(self.pc))
        assert_array_equal(bb_new.center, np.zeros(3),
                           "after centering, BoundingBox center not in origin")
        assert_array_equal(self.pc.offset, bb.center,
                           "offset of centering operation not equal to"
                           " original center")
        assert_array_equal(bb.size, bb_new.size,
                           "bounding box size changed due to translation")


class TestBoundary(unittest.TestCase):

    def setUp(self):
        self.num_rows = 50
        self.max = 0.1
        self.num_points = self.num_rows * self.num_rows
        grid = np.zeros((self.num_points, 6))
        row = np.linspace(start=0.0, stop=self.max, num=self.num_rows)
        grid[:, 0:2] = cartesian((row, row))
        self.pc = pcl.PointCloudXYZRGB(grid.astype(np.float32))
        conversions.register(self.pc)
        self.footprint_boundary = np.array(
            [[0.0, 0.0], [0.0, self.max],
             [self.max, self.max], [self.max, 0.0]])

    def testBoundaries(self):
        boundary = registration.get_pointcloud_boundaries(self.pc)
        self.assertEqual(self.pc.size, self.num_points)
        self.assertLess(boundary.size, self.num_points)
        self.assertGreater(boundary.size, 0)

        small_footprint = registration.scale_points(
            self.footprint_boundary, 0.9)
        large_footprint = registration.scale_points(
            self.footprint_boundary, 1.1)

        self.assertEqual(
            np.sum(registration.point_in_polygon2d(boundary, small_footprint)),
            0)
        self.assertEqual(
            np.sum(registration.point_in_polygon2d(boundary, large_footprint)),
            boundary.size)
        self.assertGreater(
            np.sum(registration.point_in_polygon2d(self.pc, small_footprint)),
            0)
        self.assertEqual(
            np.sum(registration.point_in_polygon2d(self.pc, large_footprint)),
            self.pc.size)

    def testBoundariesTooSmallRadius(self):
        boundary = registration.get_pointcloud_boundaries(
            self.pc, search_radius=0.0001, normal_search_radius=0.0001)
        self.assertEqual(boundary.size, 0)


class TestRegistrationPipeline(unittest.TestCase):

    def setUp(self):
        self.drivemapLas = 'testDriveMap.las'
        self.sourceLas = 'testSource.las'
        self.footprintCsv = 'testFootprint.csv'
        self.foutLas = 'testOutput.las'

        self.min = -10
        self.max = 10
        self.num_rows = 20

        # Create plane with a box
        cubePct = 0.5
        cubeRows = np.round(self.num_rows * cubePct)
        cubeMin = self.min * cubePct
        cubeMax = self.max * cubePct
        cubeOffset = [0, 0, (cubeMax - cubeMin) / 2]
        denseCubeOffset = [3, 2, 1 + (cubeMax - cubeMin) / 2]

        plane_row = np.linspace(
            start=self.min, stop=self.max, num=self.num_rows)
        planePoints = cartesian((plane_row, plane_row, 0))

        cubePoints = self.buildCube(cubeMin, cubeMax, cubeRows, cubeOffset)

        allPoints = np.vstack([planePoints, cubePoints])

        plane_grid = np.zeros((allPoints.shape[0], 6))
        plane_grid[:, 0:3] = allPoints

        self.drivemap_pc = pcl.PointCloudXYZRGB(plane_grid.astype(np.float32))
        conversions.register(self.drivemap_pc)
        conversions.writeLas(self.drivemapLas, self.drivemap_pc)

        # Create a simple box
        denseCubePoints = self.buildCube(
            cubeMin, cubeMax, cubeRows * 4, denseCubeOffset)

        denseGrid = np.zeros((denseCubePoints.shape[0], 6))
        denseGrid[:, 0:3] = denseCubePoints

        self.source_pc = pcl.PointCloudXYZRGB(denseGrid.astype(np.float32))
        conversions.register(self.source_pc)
        conversions.writeLas(self.sourceLas, self.source_pc)

        # Create footprint of the box
        footprint = [
            [cubeMin, cubeMin, 0],
            [cubeMin, cubeMax, 0],
            [cubeMax, cubeMax, 0],
            [cubeMax, cubeMin, 0],
            [cubeMin, cubeMin, 0],
        ]
        np.savetxt(self.footprintCsv, footprint, fmt='%.3f', delimiter=',')

    def buildCube(self, cubeMin, cubeMax, cubeRows, cubeOffset):
        cube_row = np.linspace(start=cubeMin, stop=cubeMax, num=cubeRows)
        # cubePoints = cartesian((cube_row, cube_row, cube_row))
        cubeWall0 = cartesian((cube_row, cube_row, cubeMin))
        cubeWall1 = cartesian((cube_row, cube_row, cubeMax))
        cubeWall2 = cartesian((cube_row, cubeMin, cube_row))
        cubeWall3 = cartesian((cube_row, cubeMax, cube_row))
        cubeWall4 = cartesian((cubeMin, cube_row, cube_row))
        cubeWall5 = cartesian((cubeMax, cube_row, cube_row))

        cubePoints = np.vstack([cubeWall0, cubeWall1, cubeWall2,
                                cubeWall3, cubeWall4, cubeWall5])
        cubePoints += np.random.rand(
            cubePoints.shape[0], cubePoints.shape[1]) * 0.1

        for i, offset in enumerate(cubeOffset):
            cubePoints[:, i] += offset
        return cubePoints

    def testPipeline(self):
        # Register box on surface
        registrationPipeline(self.sourceLas, self.drivemapLas,
                             self.footprintCsv, self.foutLas)
        registered_pc = conversions.loadLas(self.foutLas)

        target = np.asarray(self.source_pc)
        actual = np.asarray(registered_pc)

        assert_array_almost_equal(target.min(axis=0), actual.min(axis=0),
                                  "Lower bound of registered cloud does not"
                                  " match expectation")
        assert_array_almost_equal(target.max(axis=0), actual.max(axis=0),
                                  "Upper bound of registered cloud does not"
                                  " match expectation")
        assert_array_almost_equal(target.mean(axis=0), actual.mean(axis=0),
                                  "Middle point of registered cloud does not"
                                  " match expectation")

if __name__ == "__main__":
    unittest.main()

# Commented out for slowness
# class TestRegistrationSite20(unittest.TestCase):
#     def testRegistrationFromFootprint(self):
#         fname = 'data/footprints/site20.pcd'
#         frefname = 'data/footprints/20.las'
#         fp_name = 'data/footprints/20.las_footprint.csv'
#         assert os.path.exists(fname)
#         assert os.path.exists(fp_name)
#         assert os.path.exists(frefname)
#         drivemap = conversions.loadLas(frefname)
#         footprint = conversions.loadCsvPolygon(fp_name)
# Shift footprint by (-1.579, 0.525) -- value estimated manually
#         footprint[:,0] += -1.579381346780
#         footprint[:,1] += 0.52519696509
#         pointcloud = pcl.load(fname,loadRGB=True)
#         conversions.register(pointcloud)
#         registration.register_from_footprint(pointcloud, footprint)
#         conversions.writeLas(pointcloud, 'tests/20.testscale.las')
