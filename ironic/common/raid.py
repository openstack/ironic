# Copyright 2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime

import jsonschema
from jsonschema import exceptions as json_schema_exc

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils


def _check_and_return_root_volumes(raid_config):
    """Returns root logical disks after validating RAID config.

    This method checks if multiple logical disks had 'is_root_volume'
    set to True and raises an exception if it is True. Otherwise,
    returns the root logical disk mentioned in the RAID config.

    :param raid_config: target RAID configuration or current RAID
        configuration.
    :returns: the dictionary for the root logical disk if it is
        present, otherwise None.
    :raises: InvalidParameterValue, if there were more than one
        root volume specified in the RAID configuration.
    """
    logical_disks = raid_config['logical_disks']
    root_logical_disks = [x for x in logical_disks if x.get('is_root_volume')]
    if len(root_logical_disks) > 1:
        msg = _("Raid config cannot have more than one root volume. "
                "%d root volumes were specified") % len(root_logical_disks)
        raise exception.InvalidParameterValue(msg)

    if root_logical_disks:
        return root_logical_disks[0]


def validate_configuration(raid_config, raid_config_schema):
    """Validates the RAID configuration passed using JSON schema.

    This method validates a RAID configuration against a RAID configuration
    schema.

    :param raid_config: A dictionary containing RAID configuration information
    :param raid_config_schema: A dictionary which is the schema to be used for
        validation.
    :raises: InvalidParameterValue, if validation of the RAID configuration
        fails.
    """
    try:
        jsonschema.validate(raid_config, raid_config_schema)
    except json_schema_exc.ValidationError as e:
        # NOTE: Even though e.message is deprecated in general, it is said
        # in jsonschema documentation to use this still.
        msg = _("RAID config validation error: %s") % e.message
        raise exception.InvalidParameterValue(msg)

    # Check if there are multiple root volumes specified.
    _check_and_return_root_volumes(raid_config)


def get_logical_disk_properties(raid_config_schema):
    """Get logical disk properties from RAID configuration schema.

    This method reads the logical properties and their textual description
    from the schema that is passed.

    :param raid_config_schema: A dictionary which is the schema to be used for
        getting properties that may be specified for the logical disk.
    :returns: A dictionary containing the logical disk properties as keys
        and a textual description for them as values.
    """
    logical_disk_schema = raid_config_schema['properties']['logical_disks']
    properties = logical_disk_schema['items']['properties']
    return {prop: prop_dict['description']
            for prop, prop_dict in properties.items()}


def update_raid_info(node, raid_config):
    """Update the node's information based on the RAID config.

    This method updates the node's information to make use of the configured
    RAID for scheduling purposes (through properties['capabilities'] and
    properties['local_gb']) and deploying purposes (using
    properties['root_device']).

    :param node: a node object
    :param raid_config: The dictionary containing the current RAID
        configuration.
    :raises: InvalidParameterValue, if 'raid_config' has more than
        one root volume or if node.properties['capabilities'] is malformed.
    """
    current = raid_config.copy()
    current['last_updated'] = str(datetime.datetime.utcnow())
    node.raid_config = current

    # Current RAID configuration can have 0 or 1 root volumes. If there
    # are > 1 root volumes, then it's invalid.  We check for this condition
    # while accepting target RAID configuration, but this check is just in
    # place, if some drivers pass > 1 root volumes to this method.
    root_logical_disk = _check_and_return_root_volumes(raid_config)
    if root_logical_disk:
        # Update local_gb and root_device_hint
        properties = node.properties
        properties['local_gb'] = root_logical_disk['size_gb']
        try:
            properties['root_device'] = (
                root_logical_disk['root_device_hint'])
        except KeyError:
            pass
        properties['capabilities'] = utils.get_updated_capabilities(
            properties.get('capabilities', ''),
            {'raid_level': root_logical_disk['raid_level']})
        node.properties = properties

    node.save()
