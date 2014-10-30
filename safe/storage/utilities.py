# coding=utf-8
"""**Utilities for storage module**
"""

import os
import re
import copy
import numpy
import math
from ast import literal_eval
from osgeo import ogr

from geometry import Polygon

from safe.common.numerics import ensure_numeric
from safe.common.utilities import verify
from safe.common.exceptions import (
    BoundingBoxError, InaSAFEError, ReadMetadataError)


# Default attribute to assign to vector layers
from safe.common.utilities import ugettext as tr
from safe.storage.metadata_utilities import (
    write_iso_metadata, read_iso_metadata)

DEFAULT_ATTRIBUTE = 'inapolygon'

# Spatial layer file extensions that are recognised in Risiko
# FIXME: Perhaps add '.gml', '.zip', ...
LAYER_TYPES = ['.shp', '.asc', '.tif', '.tiff', '.geotif', '.geotiff']

# Map between extensions and ORG drivers
DRIVER_MAP = {'.sqlite': 'SQLITE',
              '.shp': 'ESRI Shapefile',
              '.gml': 'GML',
              '.tif': 'GTiff',
              '.asc': 'AAIGrid'}

# Map between Python types and OGR field types
# FIXME (Ole): I can't find a double precision type for OGR
TYPE_MAP = {type(None): ogr.OFTString,  # What else should this be?
            type(''): ogr.OFTString,
            type(True): ogr.OFTInteger,
            type(0): ogr.OFTInteger,
            type(0.0): ogr.OFTReal,
            type(numpy.array([0.0])[0]): ogr.OFTReal,  # numpy.float64
            type(numpy.array([[0.0]])[0]): ogr.OFTReal}  # numpy.ndarray

# Map between verbose types and OGR geometry types
INVERSE_GEOMETRY_TYPE_MAP = {'point': ogr.wkbPoint,
                             'line': ogr.wkbLineString,
                             'polygon': ogr.wkbPolygon}


# Miscellaneous auxiliary functions
def _keywords_to_string(keywords, sublayer=None):
    """Create a string from a keywords dict.

    Args:
        * keywords: A required dictionary containing the keywords to stringify.
        * sublayer: str optional group marker for a sub layer.

    Returns:
        str: a String containing the rendered keywords list

    Raises:
        Any exceptions are propogated.

    .. note: Only simple keyword dicts should be passed here, not multilayer
       dicts.

    For example you pass a dict like this::

        {'datatype': 'osm',
         'category': 'exposure',
         'title': 'buildings_osm_4326',
         'subcategory': 'building',
         'purpose': 'dki'}

    and the following string would be returned:

        datatype: osm
        category: exposure
        title: buildings_osm_4326
        subcategory: building
        purpose: dki

    If sublayer is provided e.g. _keywords_to_string(keywords, sublayer='foo'),
    the following:

        [foo]
        datatype: osm
        category: exposure
        title: buildings_osm_4326
        subcategory: building
        purpose: dki
    """

    # Write
    result = ''
    if sublayer is not None:
        result = '[%s]\n' % sublayer
    for k, v in keywords.items():
        # Create key
        msg = ('Key in keywords dictionary must be a string. '
               'I got %s with type %s' % (k, str(type(k))[1:-1]))
        verify(isinstance(k, basestring), msg)

        key = k
        msg = ('Key in keywords dictionary must not contain the ":" '
               'character. I got "%s"' % key)
        verify(':' not in key, msg)

        # Create value
        msg = ('Value in keywords dictionary must be convertible to a string. '
               'For key %s, I got %s with type %s'
               % (k, v, str(type(v))[1:-1]))
        try:
            val = str(v)
        except:
            raise Exception(msg)

        # Store
        result += '%s: %s\n' % (key, val)
    return result


def write_keywords(keywords, filename, sublayer=None):
    """Write keywords dictonary to file

    :param keywords: Dictionary of keyword, value pairs
    :type keywords: dict

    :param filename: Name of keywords file. Extension expected to be .keywords
    :type filename: str

    :param sublayer: Optional sublayer applicable only to multilayer formats
        such as sqlite or netcdf which can potentially hold more than
        one layer. The string should map to the layer group as per the
        example below. **If the keywords file contains sublayer
        definitions but no sublayer was defined, keywords file content
        will be removed and replaced with only the keywords provided
        here.**
    :type sublayer: str

    A keyword file with sublayers may look like this:

        [osm_buildings]
        datatype: osm
        category: exposure
        subcategory: building
        purpose: dki
        title: buildings_osm_4326

        [osm_flood]
        datatype: flood
        category: hazard
        subcategory: building
        title: flood_osm_4326

    Keys must be strings not containing the ":" character
    Values can be anything that can be converted to a string (using
    Python's str function)

    Surrounding whitespace is removed from values, but keys are unmodified
    The reason being that keys must always be valid for the dictionary they
    came from. For values we have decided to be flexible and treat entries like
    'unit:m' the same as 'unit: m', or indeed 'unit: m '.
    Otherwise, unintentional whitespace in values would lead to surprising
    errors in the application.
    """

    # Input checks
    basename, ext = os.path.splitext(filename)

    msg = ('Unknown extension for file %s. '
           'Expected %s.keywords' % (filename, basename))
    verify(ext == '.keywords', msg)

    # First read any keywords out of the file so that we can retain
    # keywords for other sublayers
    existing_keywords = read_keywords(filename, all_blocks=True)

    first_value = None
    if len(existing_keywords) > 0:
        first_value = existing_keywords[existing_keywords.keys()[0]]
    multilayer_flag = type(first_value) == dict

    handle = file(filename, 'w')

    if multilayer_flag:
        if sublayer is not None and sublayer != '':
            #replace existing keywords / add new for this layer
            existing_keywords[sublayer] = keywords
            for key, value in existing_keywords.iteritems():
                handle.write(_keywords_to_string(value, sublayer=key))
                handle.write('\n')
        else:
            # It is currently a multilayer but we will replace it with
            # a single keyword block since the user passed no sublayer
            handle.write(_keywords_to_string(keywords))
    else:
        #currently a simple layer so replace it with our content
        handle.write(_keywords_to_string(keywords, sublayer=sublayer))

    handle.close()

    write_iso_metadata(filename)


def read_keywords(keyword_filename, sublayer=None, all_blocks=False):
    """Read keywords dictionary from file

    :param keyword_filename: Name of keywords file. Extension expected to be .keywords
        The format of one line is expected to be either
        string: string or string
    :type keyword_filename: str

    :param sublayer: Optional sublayer applicable only to multilayer formats
        such as sqlite or netcdf which can potentially hold more than
        one layer. The string should map to the layer group as per the
        example below. If the keywords file contains sublayer definitions
        but no sublayer was defined, the first layer group will be
        returned.
    :type sublayer: str

    :param all_blocks: Optional, defaults to False. If True will return
        a dict of dicts, where the top level dict entries each represent
        a sublayer, and the values of that dict will be dicts of keyword
        entries.
    :type all_blocks: bool

    :returns: keywords: Dictionary of keyword, value pairs

    A keyword layer with sublayers may look like this:

        [osm_buildings]
        datatype: osm
        category: exposure
        subcategory: building
        purpose: dki
        title: buildings_osm_4326

        [osm_flood]
        datatype: flood
        category: hazard
        subcategory: building
        title: flood_osm_4326

    Whereas a simple keywords file would look like this

        datatype: flood
        category: hazard
        subcategory: building
        title: flood_osm_4326

    If filename does not exist, an empty dictionary is returned
    Blank lines are ignored
    Surrounding whitespace is removed from values, but keys are unmodified
    If there are no ':', then the keyword is treated as a key with no value
    """

    metadata = False

    # Input checks
    basename, ext = os.path.splitext(keyword_filename)

    msg = ('Unknown extension for file %s. '
           'Expected %s.keywords' % (keyword_filename, basename))
    verify(ext == '.keywords', msg)

    try:
        metadata = read_iso_metadata(keyword_filename)
    except IOError:
        pass
    except ReadMetadataError:
        pass

    # we have no valid xml metadata nor a keyword file
    if not metadata and not os.path.isfile(keyword_filename):
        return {}

    if metadata:
        lines = metadata['keywords']
    else:
        # Read all entries
        with open(keyword_filename, 'r') as fid:
            lines = fid.readlines()

    blocks = {}
    keywords = {}
    current_block = None
    first_keywords = None

    for line in lines:
        # Remove trailing (but not preceeding!) whitespace
        # FIXME: Can be removed altogether
        text = line.rstrip()

        # Ignore blank lines
        if text == '':
            continue

        # Check if it is an ini style group header
        block_flag = re.search(r'^\[.*]$', text, re.M | re.I)

        if block_flag:
            # Write the old block if it exists - must have a current
            # block to prevent orphans
            if len(keywords) > 0 and current_block is not None:
                blocks[current_block] = keywords
            if first_keywords is None and len(keywords) > 0:
                first_keywords = keywords
            # Now set up for a new block
            current_block = text[1:-1]
            # Reset the keywords each time we encounter a new block
            # until we know we are on the desired one
            keywords = {}
            continue

        if ':' not in text:
            key = text.strip()
            val = None
        else:
            # Get splitting point
            idx = text.find(':')

            # Take key as everything up to the first ':'
            key = text[:idx]

            # Take value as everything after the first ':'
            textval = text[idx + 1:].strip()
            try:
                # Take care of python structures like
                # booleans, None, lists, dicts etc
                val = literal_eval(textval)
            except (ValueError, SyntaxError):
                val = textval

        # Add entry to dictionary
        keywords[key] = val

    # Write our any unfinalised block data
    if len(keywords) > 0 and current_block is not None:
        blocks[current_block] = keywords
    if first_keywords is None:
        first_keywords = keywords

    # Ok we have generated a structure that looks like this:
    # blocks = {{ 'foo' : { 'a': 'b', 'c': 'd'},
    #           { 'bar' : { 'd': 'e', 'f': 'g'}}
    # where foo and bar are sublayers and their dicts are the sublayer keywords
    if all_blocks:
        return blocks
    if sublayer is not None:
        if sublayer in blocks:
            return blocks[sublayer]
    else:
        return first_keywords


# noinspection PyExceptionInherit
def check_geotransform(geotransform):
    """Check that geotransform is valid

    :param geotransform: GDAL geotransform (6-tuple).
        (top left x, w-e pixel resolution, rotation,
        top left y, rotation, n-s pixel resolution).
        See e.g. http://www.gdal.org/gdal_tutorial.html
    :type geotransform: tuple

    .. note::
       This assumes that the spatial reference uses geographic coordinates,
       so will not work for projected coordinate systems.
    """

    msg = ('Supplied geotransform must be a tuple with '
           '6 numbers. I got %s' % str(geotransform))
    verify(len(geotransform) == 6, msg)

    for x in geotransform:
        try:
            float(x)
        except TypeError:
            raise InaSAFEError(msg)

    # Check longitude
    msg = ('Element in 0 (first) geotransform must be a valid '
           'longitude. I got %s' % geotransform[0])
    verify(-180 <= geotransform[0] <= 180, msg)

    # Check latitude
    msg = ('Element 3 (fourth) in geotransform must be a valid '
           'latitude. I got %s' % geotransform[3])
    verify(-90 <= geotransform[3] <= 90, msg)

    # Check cell size
    msg = ('Element 1 (second) in geotransform must be a positive '
           'number. I got %s' % geotransform[1])
    verify(geotransform[1] > 0, msg)

    msg = ('Element 5 (sixth) in geotransform must be a negative '
           'number. I got %s' % geotransform[1])
    verify(geotransform[5] < 0, msg)


def geotransform_to_bbox(geotransform, columns, rows):
    """Convert geotransform to bounding box

    :param geotransform: GDAL geotransform (6-tuple).
        (top left x, w-e pixel resolution, rotation,
        top left y, rotation, n-s pixel resolution).
        See e.g. http://www.gdal.org/gdal_tutorial.html
    :type geotransform: tuple

    :param columns: Number of columns in grid
    :type columns: int

    :param rows: Number of rows in grid
    :type rows: int

    :returns: bbox: Bounding box as a list of geographic coordinates
        [west, south, east, north]

    .. note::
        Rows and columns are needed to determine eastern and northern bounds.
        FIXME: Not sure if the pixel vs gridline registration issue is observed
        correctly here. Need to check against gdal > v1.7
    """

    x_origin = geotransform[0]  # top left x
    y_origin = geotransform[3]  # top left y
    x_res = geotransform[1]     # w-e pixel resolution
    y_res = geotransform[5]     # n-s pixel resolution
    x_pix = columns
    y_pix = rows

    min_x = x_origin
    max_x = x_origin + (x_pix * x_res)
    min_y = y_origin + (y_pix * y_res)
    max_y = y_origin

    return [min_x, min_y, max_x, max_y]


def geotransform_to_resolution(geotransform, isotropic=False):
    """Convert geotransform to resolution

    :param geotransform: GDAL geotransform (6-tuple).
        (top left x, w-e pixel resolution, rotation,
        top left y, rotation, n-s pixel resolution).
        See e.g. http://www.gdal.org/gdal_tutorial.html
    :type geotransform: tuple

    :param isotropic: If True, return the average (dx + dy) / 2
    :type isotropic: bool

    :returns: resolution: grid spacing (res_x, res_y) in (positive) decimal
        degrees ordered as longitude first, then latitude.
        or (res_x + res_y) / 2 (if isotropic is True)
    """

    res_x = geotransform[1]   # w-e pixel resolution
    res_y = -geotransform[5]  # n-s pixel resolution (always negative)

    if isotropic:
        return (res_x + res_y) / 2
    else:
        return res_x, res_y


def raster_geometry_to_geotransform(longitudes, latitudes):
    """Convert vectors of longitudes and latitudes to geotransform

    Note:
        This is the inverse operation of Raster.get_geometry().

    :param longitudes: Vectors of geographic coordinates
    :type longitudes:

    :param latitudes: Vectors of geographic coordinates
    :type latitudes:

    :returns: geotransform: 6-tuple (top left x, w-e pixel resolution,
        rotation, top left y, rotation, n-s pixel resolution)
    """

    nx = len(longitudes)
    ny = len(latitudes)

    msg = ('You must specify more than 1 longitude to make geotransform: '
           'I got %s' % str(longitudes))
    verify(nx > 1, msg)

    msg = ('You must specify more than 1 latitude to make geotransform: '
           'I got %s' % str(latitudes))
    verify(ny > 1, msg)

    dx = float(longitudes[1] - longitudes[0])  # Longitudinal resolution
    dy = float(latitudes[0] - latitudes[1])  # Latitudinal resolution (neg)

    # Define pixel centers along each directions
    # This is to achieve pixel registration rather
    # than gridline registration
    dx2 = dx / 2
    dy2 = dy / 2

    geotransform = (longitudes[0] - dx2,  # Longitude of upper left corner
                    dx,                   # w-e pixel resolution
                    0,                    # rotation
                    latitudes[-1] - dy2,  # Latitude of upper left corner
                    0,                    # rotation
                    dy)                   # n-s pixel resolution

    return geotransform


# noinspection PyExceptionInherit
def bbox_intersection(*args):
    """Compute intersection between two or more bounding boxes

    :param args: two or more bounding boxes.
        Each is assumed to be a list or a tuple with
        four coordinates (W, S, E, N)

    :returns: The minimal common bounding box
    """

    msg = 'Function bbox_intersection must take at least 2 arguments.'
    verify(len(args) > 1, msg)

    result = [-180, -90, 180, 90]
    for a in args:
        if a is None:
            continue

        msg = ('Bounding box expected to be a list of the '
               'form [W, S, E, N]. '
               'Instead i got "%s"' % str(a))

        try:
            box = list(a)
        except:
            raise Exception(msg)

        if not len(box) == 4:
            raise BoundingBoxError(msg)

        msg = ('Western boundary must be less than or equal to eastern. '
               'I got %s' % box)
        if not box[0] <= box[2]:
            raise BoundingBoxError(msg)

        msg = ('Southern boundary must be less than or equal to northern. '
               'I got %s' % box)
        if not box[1] <= box[3]:
            raise BoundingBoxError(msg)

        # Compute intersection

        # West and South
        for i in [0, 1]:
            result[i] = max(result[i], box[i])

        # East and North
        for i in [2, 3]:
            result[i] = min(result[i], box[i])

    # Check validity and return
    if result[0] <= result[2] and result[1] <= result[3]:
        return result
    else:
        return None


def minimal_bounding_box(bbox, min_res, eps=1.0e-6):
    """Grow bounding box to exceed specified resolution if needed

    :param bbox: Bounding box with format [W, S, E, N]
    :type bbox: list

    :param min_res: Minimal acceptable resolution to exceed
    :type min_res: float

    :param eps: Optional tolerance that will be applied to 'buffer' result
    :type eps: float

    :returns: Adjusted bounding box guaranteed to exceed specified resolution
    """

    # FIXME (Ole): Probably obsolete now

    bbox = copy.copy(list(bbox))

    delta_x = bbox[2] - bbox[0]
    delta_y = bbox[3] - bbox[1]

    if delta_x < min_res:
        dx = (min_res - delta_x) / 2 + eps
        bbox[0] -= dx
        bbox[2] += dx

    if delta_y < min_res:
        dy = (min_res - delta_y) / 2 + eps
        bbox[1] -= dy
        bbox[3] += dy

    return bbox


def buffered_bounding_box(bbox, resolution):
    """Grow bounding box with one unit of resolution in each direction

    Note:
        This will ensure there are enough pixels to robustly provide
        interpolated values without having to painstakingly deal with
        all corner cases such as 1 x 1, 1 x 2 and 2 x 1 arrays.

        The border will also make sure that points that would otherwise fall
        outside the domain (as defined by a tight bounding box) get assigned
        values.

    :param bbox: Bounding box with format [W, S, E, N]
    :type bbox: list

    :param resolution: (resx, resy) - Raster resolution in each direction.
        res - Raster resolution in either direction
        If resolution is None bbox is returned unchanged.
    :type resolution: tuple

    :returns: Adjusted bounding box

    Note:
        Case in point: Interpolation point O would fall outside this domain
                       even though there are enough grid points to support it

    ::

        --------------
        |            |
        |   *     *  | *    *
        |           O|
        |            |
        |   *     *  | *    *
        --------------

    """

    bbox = copy.copy(list(bbox))

    if resolution is None:
        return bbox

    try:
        resx, resy = resolution
    except TypeError:
        resx = resy = resolution

    bbox[0] -= resx
    bbox[1] -= resy
    bbox[2] += resx
    bbox[3] += resy

    return bbox


def get_geometry_type(geometry, geometry_type):
    """Determine geometry type based on data

    :param geometry: A list of either point coordinates [lon, lat] or polygons
        which are assumed to be numpy arrays of coordinates
    :type geometry: list

    :param geometry_type: Optional type - 'point', 'line', 'polygon' or None
    :type geometry_type: str, None

    :returns: geometry_type: Either ogr.wkbPoint, ogr.wkbLineString or
        ogr.wkbPolygon

    Note:
        If geometry type cannot be determined an Exception is raised.

        There is no consistency check across all entries of the
        geometry list, only the first element is used in this determination.
    """

    # FIXME (Ole): Perhaps use OGR's own symbols
    msg = ('Argument geometry_type must be either "point", "line", '
           '"polygon" or None')
    verify(geometry_type is None or
           geometry_type in [1, 2, 3] or
           geometry_type.lower() in ['point', 'line', 'polygon'], msg)

    if geometry_type is not None:
        if isinstance(geometry_type, basestring):
            return INVERSE_GEOMETRY_TYPE_MAP[geometry_type.lower()]
        else:
            return geometry_type
        # FIXME (Ole): Should add some additional checks to see if choice
        #              makes sense

    msg = 'Argument geometry must be a sequence. I got %s ' % type(geometry)
    verify(is_sequence(geometry), msg)

    if len(geometry) == 0:
        # Default to point if there is no data
        return ogr.wkbPoint

    msg = ('The first element in geometry must be a sequence of length > 2. '
           'I got %s ' % str(geometry[0]))
    verify(is_sequence(geometry[0]), msg)
    verify(len(geometry[0]) >= 2, msg)

    if len(geometry[0]) == 2:
        try:
            float(geometry[0][0])
            float(geometry[0][1])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            # This geometry appears to be point data
            geometry_type = ogr.wkbPoint
    elif len(geometry[0]) > 2:
        try:
            x = numpy.array(geometry[0])
        except ValueError:
            pass
        else:
            # This geometry appears to be polygon data
            if x.shape[0] > 2 and x.shape[1] == 2:
                geometry_type = ogr.wkbPolygon

    if geometry_type is None:
        msg = 'Could not determine geometry type'
        raise Exception(msg)

    return geometry_type


def is_sequence(x):
    """Determine if x behaves like a true sequence but not a string

    :param x: Sequence like object
    :type x: object

    :returns: Test result
    :rtype: bool

    Note:
        This will for example return True for lists, tuples and numpy arrays
        but False for strings and dictionaries.
    """

    if isinstance(x, basestring):
        return False

    try:
        list(x)
    except TypeError:
        return False
    else:
        return True


def array_to_line(A, geometry_type=ogr.wkbLinearRing):
    """Convert coordinates to linear_ring

    :param A: Nx2 Array of coordinates representing either a polygon or a line.
        A can be either a numpy array or a list of coordinates.
    :type A: numpy.ndarray, list

    :param geometry_type: A valid OGR geometry type.
        Default type ogr.wkbLinearRing
    :type geometry_type: ogr.wkbLinearRing, include ogr.wkbLineString

    Returns:
        * ring: OGR line geometry

    Note:
    Based on http://www.packtpub.com/article/working-geospatial-data-python
    """

    try:
        A = ensure_numeric(A, numpy.float)
    except Exception, e:
        msg = ('Array (%s) could not be converted to numeric array. '
               'I got type %s. Error message: %s'
               % (A, str(type(A)), e))
        raise Exception(msg)

    msg = 'Array must be a 2d array of vertices. I got %s' % (str(A.shape))
    verify(len(A.shape) == 2, msg)

    msg = 'A array must have two columns. I got %s' % (str(A.shape[0]))
    verify(A.shape[1] == 2, msg)

    N = A.shape[0]  # Number of vertices

    line = ogr.Geometry(geometry_type)
    for i in range(N):
        line.AddPoint(A[i, 0], A[i, 1])

    return line


def rings_equal(x, y, rtol=1.0e-6, atol=1.0e-8):
    """Compares to linear rings as numpy arrays

    :param x: A 2d array of the first ring
    :type x: numpy.ndarray

    :param y: A 2d array of the second ring
    :type y: numpy.ndarray

    :param rtol: The relative tolerance parameter
    :type rtol: float

    :param atol: The relative tolerance parameter
    :type rtol: float

    Returns:
        * True if x == y or x' == y (up to the specified tolerance)

        where x' is x reversed in the first dimension. This corresponds to
        linear rings being seen as equal irrespective of whether they are
        organised in clock wise or counter clock wise order
    """

    x = ensure_numeric(x, numpy.float)
    y = ensure_numeric(y, numpy.float)

    msg = 'Arrays must a 2d arrays of vertices. I got %s and %s' % (x, y)
    verify(len(x.shape) == 2 and len(y.shape) == 2, msg)

    msg = 'Arrays must have two columns. I got %s and %s' % (x, y)
    verify(x.shape[1] == 2 and y.shape[1] == 2, msg)

    if (numpy.allclose(x, y, rtol=rtol, atol=atol) or
            numpy.allclose(x, y[::-1], rtol=rtol, atol=atol)):
        return True
    else:
        return False


# FIXME (Ole): We can retire this messy function now
#              Positive: Delete it :-)
def array_to_wkt(A, geom_type='POLYGON'):
    """Convert coordinates to wkt format

    :param A: Nx2 Array of coordinates representing either a polygon or a line.
        A can be either a numpy array or a list of coordinates.
    :type A: numpy.array

    :param geom_type: Determines output keyword 'POLYGON' or 'LINESTRING'
    :type geom_type: str

    :returns: wkt: geometry in the format known to ogr: Examples

    Note:
        POLYGON((1020 1030,1020 1045,1050 1045,1050 1030,1020 1030))
        LINESTRING(1000 1000, 1100 1050)
    """

    try:
        A = ensure_numeric(A, numpy.float)
    except Exception, e:
        msg = ('Array (%s) could not be converted to numeric array. '
               'I got type %s. Error message: %s'
               % (geom_type, str(type(A)), e))
        raise Exception(msg)

    msg = 'Array must be a 2d array of vertices. I got %s' % (str(A.shape))
    verify(len(A.shape) == 2, msg)

    msg = 'A array must have two columns. I got %s' % (str(A.shape[0]))
    verify(A.shape[1] == 2, msg)

    if geom_type == 'LINESTRING':
        # One bracket
        n = 1
    elif geom_type == 'POLYGON':
        # Two brackets (tsk tsk)
        n = 2
    else:
        msg = 'Unknown geom_type: %s' % geom_type
        raise Exception(msg)

    wkt_string = geom_type + '(' * n

    N = len(A)
    for i in range(N):
        # Works for both lists and arrays
        wkt_string += '%f %f, ' % tuple(A[i])

    return wkt_string[:-2] + ')' * n

# Map of ogr numerical geometry types to their textual representation
# FIXME (Ole): Some of them don't exist, even though they show up
# when doing dir(ogr) - Why?:
geometry_type_map = {ogr.wkbPoint: 'Point',
                     ogr.wkbPoint25D: 'Point25D',
                     ogr.wkbPolygon: 'Polygon',
                     ogr.wkbPolygon25D: 'Polygon25D',
                     #ogr.wkbLinePoint: 'LinePoint',  # ??
                     ogr.wkbGeometryCollection: 'GeometryCollection',
                     ogr.wkbGeometryCollection25D: 'GeometryCollection25D',
                     ogr.wkbLineString: 'LineString',
                     ogr.wkbLineString25D: 'LineString25D',
                     ogr.wkbLinearRing: 'LinearRing',
                     ogr.wkbMultiLineString: 'MultiLineString',
                     ogr.wkbMultiLineString25D: 'MultiLineString25D',
                     ogr.wkbMultiPoint: 'MultiPoint',
                     ogr.wkbMultiPoint25D: 'MultiPoint25D',
                     ogr.wkbMultiPolygon: 'MultiPolygon',
                     ogr.wkbMultiPolygon25D: 'MultiPolygon25D',
                     ogr.wkbNDR: 'NDR',
                     ogr.wkbNone: 'None',
                     ogr.wkbUnknown: 'Unknown'}


def geometry_type_to_string(g_type):
    """Provides string representation of numeric geometry types

    :param g_type: geometry type:
    :type g_type: ogr.wkb*, None

    FIXME (Ole): I can't find anything like this in ORG. Why?
    """

    if g_type in geometry_type_map:
        return geometry_type_map[g_type]
    elif g_type is None:
        return 'No geometry type assigned'
    else:
        return 'Unknown geometry type: %s' % str(g_type)


# FIXME: Move to common numerics area along with polygon.py
def calculate_polygon_area(polygon, signed=False):
    """Calculate the signed area of non-self-intersecting polygon

    :param polygon: Numeric array of points (longitude, latitude). It is
        assumed to be closed, i.e. first and last points are identical
    :type polygon: numpy.ndarray

    :param signed: Optional flag deciding whether returned area retains its
     sign:

            If points are ordered counter clockwise, the signed area
            will be positive.

            If points are ordered clockwise, it will be negative
            Default is False which means that the area is always
            positive.

    :type signed: bool

    :returns: area: Area of polygon (subject to the value of argument signed)
    :rtype: numpy.ndarray

    Note:
        Sources
            http://paulbourke.net/geometry/polyarea/
            http://en.wikipedia.org/wiki/Centroid
    """

    # Make sure it is numeric
    P = numpy.array(polygon)

    msg = ('Polygon is assumed to consist of coordinate pairs. '
           'I got second dimension %i instead of 2' % P.shape[1])
    verify(P.shape[1] == 2, msg)

    x = P[:, 0]
    y = P[:, 1]

    # Calculate 0.5 sum_{i=0}^{N-1} (x_i y_{i+1} - x_{i+1} y_i)
    a = x[:-1] * y[1:]
    b = y[:-1] * x[1:]

    A = numpy.sum(a - b) / 2.

    if signed:
        return A
    else:
        return abs(A)


def calculate_polygon_centroid(polygon):
    """Calculate the centroid of non-self-intersecting polygon

    :param polygon: Numeric array of points (longitude, latitude). It is
        assumed to be closed, i.e. first and last points are identical
    :type polygon: numpy.ndarray

    :returns: calculated centroid
    :rtype: numpy.ndarray

    .. note::
        Sources
            http://paulbourke.net/geometry/polyarea/
            http://en.wikipedia.org/wiki/Centroid

    """

    # Make sure it is numeric
    P = numpy.array(polygon)

    # Normalise to ensure numerical accurracy.
    # This requirement in backed by tests in test_io.py and without it
    # centroids at building footprint level may get shifted outside the
    # polygon!
    P_origin = numpy.amin(P, axis=0)
    P = P - P_origin

    # Get area. This calculation could be incorporated to save time
    # if necessary as the two formulas are very similar.
    A = calculate_polygon_area(polygon, signed=True)

    x = P[:, 0]
    y = P[:, 1]

    # Calculate
    # Cx = sum_{i=0}^{N-1} (x_i + x_{i+1})(x_i y_{i+1} - x_{i+1} y_i)/(6A)
    # Cy = sum_{i=0}^{N-1} (y_i + y_{i+1})(x_i y_{i+1} - x_{i+1} y_i)/(6A)
    a = x[:-1] * y[1:]
    b = y[:-1] * x[1:]

    cx = x[:-1] + x[1:]
    cy = y[:-1] + y[1:]

    Cx = numpy.sum(cx * (a - b)) / (6. * A)
    Cy = numpy.sum(cy * (a - b)) / (6. * A)

    # Translate back to real location
    C = numpy.array([Cx, Cy]) + P_origin
    return C


def points_between_points(point1, point2, delta):
    """Creates an array of points between two points given a delta

    :param point1: The first point
    :type point1: numpy.ndarray

    :param point2: The second point
    :type point2: numpy.ndarray

    :param delta: The increment between inserted points
    :type delta: float

    :returns: Array of points.
    :rtype: numpy.ndarray

    Note:
        u = (x1-x0, y1-y0)/L, where
        L=sqrt( (x1-x0)^2 + (y1-y0)^2).
        If r is the resolution, then the
        points will be given by
        (x0, y0) + u * n * r for n = 1, 2, ....
        while len(n*u*r) < L
    """
    x0, y0 = point1
    x1, y1 = point2
    L = math.sqrt(math.pow((x1 - x0), 2) + math.pow((y1 - y0), 2))
    pieces = int(L / delta)
    uu = numpy.array([x1 - x0, y1 - y0]) / L
    points = [point1]
    for nn in range(pieces):
        point = point1 + uu * (nn + 1) * delta
        points.append(point)
    return numpy.array(points)


def points_along_line(line, delta):
    """Calculate a list of points along a line with a given delta

    :param line: Numeric array of points (longitude, latitude).
    :type line: numpy.ndarray

    :param delta: Decimal number to be used as step
    :type delta: float

    :returns: Numeric array of points (longitude, latitude).
    :rtype: numpy.ndarray

    Note:
        Sources
            http://paulbourke.net/geometry/polyarea/
            http://en.wikipedia.org/wiki/Centroid
    """

    # Make sure it is numeric
    P = numpy.array(line)
    points = []
    for i in range(len(P) - 1):
        pts = points_between_points(P[i], P[i + 1], delta)
        # If the first point of this list is the same
        # as the last one recorded, do not use it
        if len(points) > 0:
            if numpy.allclose(points[-1], pts[0]):
                pts = pts[1:]
        points.extend(pts)
    C = numpy.array(points)
    return C


def combine_polygon_and_point_layers(layers):
    """Combine polygon and point layers

    :param layers: List of vector layers of type polygon or point
    :type layers: list

    :returns: One point layer with all input point layers and centroids from
        all input polygon layers.
    :rtype: numpy.ndarray
    :raises: InaSAFEError (in case attribute names are not the same.)
    """

    # This is to implement issue #276
    print layers


def get_ring_data(ring):
    """Extract coordinates from OGR ring object

    :param ring: OGR ring object
    :type ring:

    :returns: Nx2 numpy array of vertex coordinates (lon, lat)
    :rtype: numpy.array
    """

    N = ring.GetPointCount()
    # noinspection PyTypeChecker
    A = numpy.zeros((N, 2), dtype='d')

    # FIXME (Ole): Is there any way to get the entire data vectors?
    for j in range(N):
        A[j, :] = ring.GetX(j), ring.GetY(j)

    # Return ring as an Nx2 numpy array
    return A


def get_polygon_data(G):
    """Extract polygon data from OGR geometry

    :param G: OGR polygon geometry
    :return: List of InaSAFE polygon instances
    """

    # Get outer ring, then inner rings
    # http://osgeo-org.1560.n6.nabble.com/
    # gdal-dev-Polygon-topology-td3745761.html
    number_of_rings = G.GetGeometryCount()

    # Get outer ring
    outer_ring = get_ring_data(G.GetGeometryRef(0))

    # Get inner rings if any
    inner_rings = []
    if number_of_rings > 1:
        for i in range(1, number_of_rings):
            inner_ring = get_ring_data(G.GetGeometryRef(i))
            inner_rings.append(inner_ring)

    # Return Polygon instance
    return Polygon(outer_ring=outer_ring,
                   inner_rings=inner_rings)


def safe_to_qgis_layer(layer):
    """Helper function to make a QgsMapLayer from a safe read_layer layer.

    :param layer: Layer object as provided by InaSAFE engine.
    :type layer: read_layer

    :returns: A validated QGIS layer or None. Returns None when QGIS is not
        available.
    :rtype: QgsMapLayer, QgsVectorLayer, QgsRasterLayer, None

    :raises: Exception if layer is not valid.
    """
    try:
        from qgis.core import QgsVectorLayer, QgsRasterLayer
    except ImportError:
        return None

    # noinspection PyUnresolvedReferences
    message = tr(
        'Input layer must be a InaSAFE spatial object. I got %s'
    ) % (str(type(layer)))
    if not hasattr(layer, 'is_inasafe_spatial_object'):
        raise Exception(message)
    if not layer.is_inasafe_spatial_object:
        raise Exception(message)

    # Get associated filename and symbolic name
    filename = layer.get_filename()
    name = layer.get_name()

    qgis_layer = None
    # Read layer
    if layer.is_vector:
        qgis_layer = QgsVectorLayer(filename, name, 'ogr')
    elif layer.is_raster:
        qgis_layer = QgsRasterLayer(filename, name)

    # Verify that new qgis layer is valid
    if qgis_layer.isValid():
        return qgis_layer
    else:
        # noinspection PyUnresolvedReferences
        message = tr('Loaded impact layer "%s" is not valid') % filename
        raise Exception(message)
