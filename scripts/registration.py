#!/usr/bin/env python2.7
"""Registration script.

Usage:
  registration.py [-h] [-d <sample>] [-u <upfile>] <source> <drivemap> <footprint> <output>

Positional arguments:
  source       Source LAS file
  drivemap     Target LAS file to map source to
  footprint    Footprint for the source LAS file
  output       file to write output LAS to

Options:
  -d <sample>  Downsample source pointcloud to a maximum of <sample> points
               [default: -1].
  -u <upfile>  Json file containing the up vector relative to the pointcloud.
"""

from __future__ import print_function
from docopt import docopt

from pcl.registration import icp
import numpy as np
import time
import os
import sys
from patty.conversions import (load, save, load_csv_polygon,
                               copy_registration, extract_mask, BoundingBox)
from patty.registration import (get_pointcloud_boundaries, find_rotation, register_from_footprint,
                                register_offset_scale_from_ref, scale_points,
                                point_in_polygon2d, downsample_random, is_upside_down)
from patty.segmentation.dbscan import get_largest_dbscan_clusters
from patty.registration.stickscale import get_stick_scale



def log(*args, **kwargs):
    print(time.strftime("[%H:%M:%S]"), *args, **kwargs)


def find_largest_cluster(pointcloud, sample):
    log("Finding largest cluster")
    if sample != -1 and len(pointcloud) > sample:
        fraction = float(sample) / len(pointcloud)
        log("downsampling from %d to %d points (%d%%) for registration" % (

            len(pointcloud), sample, int(fraction * 100)))
        pc = downsample_random(pointcloud, fraction, random_seed=0)
    else:
        pc = pointcloud
    return get_largest_dbscan_clusters(pc, 0.7, .15, 250)


def cutout_edge(pointcloud, polygon2d, polygon_width):
    # FIXME: will give overflow in many cases
    pc_array = np.asarray(pointcloud) + pointcloud.offset

    slightly_large_polygon = scale_points(polygon2d, 1.05)
    in_polygon = point_in_polygon2d(pc_array, slightly_large_polygon)

    large_polygon = scale_points(polygon2d, polygon_width)
    in_large_polygon = point_in_polygon2d(pc_array, large_polygon)
    return extract_mask(pointcloud,
                        in_large_polygon & np.invert(in_polygon))


def registration_pipeline(sourcefile, drivemapfile, footprintcsv, f_out,
                          f_outdir, upfile=None, sample=-1):
    """Single function wrapping whole script, so it can be unit tested"""
    assert os.path.exists(sourcefile), sourcefile + ' does not exist'
    assert os.path.exists(drivemapfile), drivemapfile + ' does not exist'
    assert os.path.exists(footprintcsv), footprintcsv + ' does not exist'

    #####
    # Setup * the low-res drivemap
    #       * footprint
    #       * pointcloud

    log("reading drivemap ", drivemapfile)
    drivemap = load(drivemapfile)

    log("reading footprint ", footprintcsv )
    footprint = load_csv_polygon(footprintcsv)

    log("reading source", sourcefile)
    pointcloud = load(sourcefile)

    #####
    # set scale and offset of pointcloud and drivemap
    # as the pointcloud is unregisterd, the coordinate system is undefined,
    # and we lose nothing if we just copy it
    
    copy_registration(pointcloud, drivemap)

    #####
    # find all the points in the drivemap along the footprint
    # use bottom two meters of drivemap (not trees)

    drivemap_array = np.asarray(drivemap)
    bb = BoundingBox(points=drivemap_array)
    if bb.size[2] > bb.size[1] or bb.size[2] > bb.size[0]:
        drivemap = extract_mask(drivemap, drivemap_array[:, 2] < bb.min[2] + 2)

    footprint_boundary = cutout_edge(drivemap, footprint, 1.5)

    ###
    # find redstick scale, and use it if possible
    scale, confidence = get_stick_scale(pointcloud)
    log( "Red stick scale=%s confidence=%s" % (scale, confidence) ) 

    allow_scaling=True
    if (confidence > 0.5):
        log("Applying red stick scale" )
        pointcloud.scale( scale ) # dont care about origin of scaling
        allow_scaling=False
    else:
        log("Not applying red stick scale, confidence too low"  )
        allow_scaling=True
    
    ####
    # match the pointcloud boundary with the footprint boundary

    rot_matrix, rot_center, scale, translation = register_from_footprint(
                pointcloud, np.asarray(footprint_boundary),
                allow_scaling=allow_scaling,
                allow_rotation=True,
                allow_translation=True)

    log("Applying transforms to pointcloud" )
    pointcloud.rotate(rot_matrix, origin=rot_center )
    pointcloud.scale( scale, origin=rot_center )
    pointcloud.translate( translation )

    ####
    # do a ICP step

    log("ICP")
    converged, transf, estimate, fitness = icp( pointcloud, drivemap )

    log( "converged: %s" % converged )
    log( "transf : %s" % transf )
    log( "fitness: %s" % fitness )


    # construct output file dir/basename
    if f_outdir is None:
        f_out = os.path.abspath( f_out )
    else:
        f_out = os.path.join( f_outdir, f_out )

    save(pointcloud, f_out + ".before.icp.las" )

    pointcloud.transform( transf )
    save(pointcloud, f_out )


if __name__ == '__main__':
    args = docopt(__doc__)

    sourcefile = args['<source>']
    drivemapfile = args['<drivemap>']
    footprintcsv = args['<footprint>']
    foutLas = args['<output>']
    up_file = args['-u']
    sample = int(args['-d'])

    registration_pipeline(sourcefile, drivemapfile, footprintcsv, foutLas,
                          None, up_file, sample)
