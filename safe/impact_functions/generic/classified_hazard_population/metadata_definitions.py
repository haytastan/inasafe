# coding=utf-8
"""InaSAFE Disaster risk tool by Australian Aid - Metadata for generic Impact
function on Population for Classified Hazard.

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'lucernae'
__project_name__ = 'inasafe'
__filename__ = 'metadata_definitions'
__date__ = '24/03/15'
__copyright__ = 'lana.pcfre@gmail.com'

from safe.common.utilities import OrderedDict
from safe.defaults import default_minimum_needs, default_provenance
from safe.defaults import (
    default_gender_postprocessor,
    age_postprocessor,
    minimum_needs_selector)
from safe.utilities.i18n import tr
from safe.impact_functions.impact_function_metadata import \
    ImpactFunctionMetadata
from safe.new_definitions import (
    layer_mode_classified,
    layer_mode_continuous,
    layer_geometry_raster,
    hazard_all,
    hazard_category_hazard_zone,
    count_exposure_unit,
    all_raster_hazard_classes,
    exposure_population,
    hazard_category_hazard_scenario,
    density_exposure_unit
)


class ClassifiedHazardPopulationMetadata(ImpactFunctionMetadata):
    """Metadata for Classified Hazard Population Impact Function.

    .. versionadded:: 2.1

    We only need to re-implement as_dict(), all other behaviours
    are inherited from the abstract base class.
    """

    @staticmethod
    def as_dict():
        """Return metadata as a dictionary.

        This is a static method. You can use it to get the metadata in
        dictionary format for an impact function.

        :returns: A dictionary representing all the metadata for the
            concrete impact function.
        :rtype: dict
        """
        dict_meta = {
            'id': 'ClassifiedHazardPopulationFunction',
            'name': tr('Classified Hazard Population Function'),
            'impact': tr('Be impacted by each class'),
            'title': tr('Be affected by each hazard class'),
            'function_type': 'old-style',
            'author': 'Dianne Bencito',
            'date_implemented': 'N/A',
            'overview': tr(
                'To assess the impacts of classified hazards in raster '
                'format on population raster layer.'),
            'detailed_description': tr(
                'This function will use the class from the hazard layer '
                'that has been identified by the user which one is low, '
                'medium, or high from the parameter that user input. '
                'After that, this impact function will calculate the '
                'people will be affected per each class for class in the '
                'hazard layer. Finally, it will show the result and the '
                'total of people that will be affected for the hazard '
                'given.'),
            'hazard_input': tr(
                'A hazard raster layer where each cell represents the '
                'class of the hazard. There should be 3 classes: e.g. '
                '1, 2, and 3.'),
            'exposure_input': tr(
                'An exposure raster layer where each cell represent '
                'population count.'),
            'output': tr(
                'Map of population exposed to high class and a table with '
                'number of people in each class'),
            'actions': tr(
                'Provide details about how many people would likely be '
                'affected for each hazard class.'),
            'limitations': [tr('The number of classes is three.')],
            'citations': [],
            'layer_requirements': {
                'hazard': {
                    'layer_mode': layer_mode_classified,
                    'layer_geometries': [layer_geometry_raster],
                    'hazard_categories': [
                        hazard_category_hazard_zone,
                        hazard_category_hazard_scenario],
                    'hazard_types': hazard_all,
                    'continuous_hazard_units': [],
                    'vector_hazard_classifications': [],
                    'raster_hazard_classifications': all_raster_hazard_classes
                },
                'exposure': {
                    'layer_mode': layer_mode_continuous,
                    'layer_geometries': [layer_geometry_raster],
                    'exposure_types': [exposure_population],
                    'exposure_units': [
                        count_exposure_unit, density_exposure_unit]
                }
            },
            'parameters': OrderedDict([
                ('low_hazard_class', 1.0),
                ('medium_hazard_class', 2.0),
                ('high_hazard_class', 3.0),
                ('postprocessors', OrderedDict([
                    ('Gender', default_gender_postprocessor()),
                    ('Age', age_postprocessor()),
                    ('MinimumNeeds', minimum_needs_selector()),
                ])),
                ('minimum needs', default_minimum_needs()),
                ('provenance', default_provenance())
            ])
        }
        return dict_meta
