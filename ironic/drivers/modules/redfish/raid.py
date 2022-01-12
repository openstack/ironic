# Copyright 2021 DMTF. All rights reserved.
# Copyright (c) 2021 Dell Inc. or its subsidiaries.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import math

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import importutils
from oslo_utils import units

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import raid
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)


# TODO(billdodd): double-check all these values
RAID_LEVELS = {
    '0': {
        'min_disks': 1,
        'max_disks': 1000,
        'type': 'simple',
        'volume_type': 'NonRedundant',
        'raid_type': 'RAID0',
        'overhead': 0
    },
    '1': {
        'min_disks': 2,
        'max_disks': 2,
        'type': 'simple',
        'volume_type': 'Mirrored',
        'raid_type': 'RAID1',
        'overhead': 1
    },
    '5': {
        'min_disks': 3,
        'max_disks': 1000,
        'type': 'simple',
        'volume_type': 'StripedWithParity',
        'raid_type': 'RAID5',
        'overhead': 1
    },
    '6': {
        'min_disks': 4,
        'max_disks': 1000,
        'type': 'simple',
        'volume_type': 'StripedWithParity',
        'raid_type': 'RAID6',
        'overhead': 2
    },
    '1+0': {
        'type': 'spanned',
        'volume_type': 'SpannedMirrors',
        'raid_type': 'RAID10',
        'span_type': '1'
    },
    '5+0': {
        'type': 'spanned',
        'volume_type': 'SpannedStripesWithParity',
        'raid_type': 'RAID50',
        'span_type': '5'
    },
    '6+0': {
        'type': 'spanned',
        'volume_type': 'SpannedStripesWithParity',
        'raid_type': 'RAID60',
        'span_type': '6'
    }
}

sushy = importutils.try_import('sushy')

if sushy:
    PROTOCOL_MAP = {
        sushy.PROTOCOL_TYPE_SAS: raid.SAS,
        sushy.PROTOCOL_TYPE_SATA: raid.SATA
    }


def convert_drive_units(logical_disks, node):
    """Convert size in logical_disks from gb to bytes"""
    for disk in logical_disks:
        if disk['size_gb'] == 'MAX' and 'physical_disks' not in disk:
            raise exception.InvalidParameterValue(
                _("create_configuration called with invalid "
                  "target_raid_configuration for node %(node_id)s. "
                  "'physical_disks' is missing from logical_disk while "
                  "'size_gb'='MAX' was requested: "
                  "%(logical_disk)s") % {'node_id': node.uuid,
                                         'logical_disk': disk})

        if disk['size_gb'] == 'MAX':
            disk['size_bytes'] = 'MAX'
        else:
            disk['size_bytes'] = disk['size_gb'] * units.Gi

        del disk['size_gb']


def get_physical_disks(node):
    """Get the physical drives of the node for RAID controllers.

    :param node: an ironic node object.
    :returns: a list of Drive objects from sushy
    :raises: RedfishConnectionError when it fails to connect to Redfish
    :raises: RedfishError if there is an error getting the drives via Redfish
    """
    system = redfish_utils.get_system(node)

    disks = []
    disk_to_storage = {}
    try:
        collection = system.storage
        for storage in collection.get_members():
            controller = (storage.storage_controllers[0]
                          if storage.storage_controllers else None)
            if controller and controller.raid_types == []:
                continue
            disks.extend(storage.drives)
            for drive in storage.drives:
                disk_to_storage[drive] = storage
    except sushy.exceptions.SushyError as exc:
        error_msg = _('Cannot get the list of physical disks for node '
                      '%(node_uuid)s. Reason: %(error)s.' %
                      {'node_uuid': node.uuid, 'error': exc})
        LOG.error(error_msg)
        raise exception.RedfishError(error=exc)
    return disks, disk_to_storage


def _raise_raid_level_not_supported(raid_level):
    """Helper function for the 'RAID level is not supported' error

    :param raid_level: RAID level of the virtual disk
    :raises: exception.RedfishError
    """
    reason = (_('RAID level %(raid_level)s is not supported by the '
                'driver. Supported RAID levels: %(supported_raid_levels)s')
              % {'raid_level': raid_level,
                 'supported_raid_levels': ', '.join(RAID_LEVELS)})
    raise exception.RedfishError(error=reason)


def _raid_level_overhead(raid_level, spans_count=1):
    """Calculate the drive overhead for the given RAID level

    Drive overhead is the number of additional drives required to hold the
    the redundant data needed for mirrored volumes and the parity checksums
    for volumes with parity.

    :param raid_level: RAID level of the virtual disk
    :param spans_count: number of spans for the virtual disk
    :return: the number of drives of overhead
    :raises: RedfishError if RAID level is not supported
    """
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        _raise_raid_level_not_supported(raid_level)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.RedfishError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['overhead'] * spans_count


def _max_volume_size_bytes(raid_level, physical_disks, free_space_bytes,
                           spans_count=1, stripe_size_kb=64 * units.Ki):
    # restrict the size to the smallest available space
    free_spaces = [free_space_bytes[disk] for disk in physical_disks]
    size_kb = min(free_spaces) // units.Ki

    # NOTE(ifarkas): using math.floor so we get a volume size that does not
    #                exceed the available space
    stripes_per_disk = int(math.floor(float(size_kb) / stripe_size_kb))

    disks_count = len(physical_disks)
    overhead_disks_count = _raid_level_overhead(raid_level, spans_count)
    if disks_count <= overhead_disks_count:
        reason = _('The number of physical drives (%(drives)s) is too few for '
                   'the required number of overhead drives (%(overhead)s)' %
                   {'drives': disks_count, 'overhead': overhead_disks_count})
        raise exception.RedfishError(error=reason)

    max_volume_size_bytes = int(
        stripes_per_disk * stripe_size_kb
        * (disks_count - overhead_disks_count) * units.Ki)
    return max_volume_size_bytes


def _volume_usage_per_disk_bytes(logical_disk, physical_disks, spans_count=1,
                                 stripe_size_kb=64 * units.Ki):
    disks_count = len(physical_disks)
    overhead_disks_count = _raid_level_overhead(logical_disk['raid_level'],
                                                spans_count)
    volume_size_kb = logical_disk['size_bytes'] // units.Ki
    # NOTE(ifarkas): using math.ceil so we get the largest disk usage
    #                possible, so we can avoid over-committing
    stripes_per_volume = math.ceil(float(volume_size_kb) / stripe_size_kb)

    stripes_per_disk = math.ceil(
        float(stripes_per_volume) / (disks_count - overhead_disks_count))
    volume_usage_per_disk_bytes = int(
        stripes_per_disk * stripe_size_kb * units.Ki)
    return volume_usage_per_disk_bytes


def _calculate_spans(raid_level, disks_count):
    """Calculates number of spans for a RAID level given a physical disk count

    :param raid_level: RAID level of the virtual disk.
    :param disks_count: number of physical disks used for the virtual disk.
    :returns: number of spans.
    """
    if raid_level in ['0', '1', '5', '6']:
        return 1
    elif raid_level in ['5+0', '6+0']:
        return 2
    elif raid_level in ['1+0']:
        return disks_count >> 1
    else:
        reason = (_('Cannot calculate spans for RAID level "%s"') %
                  raid_level)
        raise exception.RedfishError(error=reason)


def _calculate_volume_props(logical_disk, physical_disks, free_space_bytes,
                            disk_to_storage):
    """Calculate specific properties of the volume and update logical_disk dict

    Calculates various properties like span_depth and span_length for the
    logical disk to be created. Converts the size_gb property to size_bytes for
    use by sushy. Also performs checks to be sure the amount of physical space
    required for the logical disk is available.

    :param logical_disk: properties of the logical disk to create as
           specified by the operator.
    :param physical_disks: list of drives available on the node.
    :param free_space_bytes: dict mapping drives to their available space.
    :param disk_to_storage: dict mapping drives to their storage.
    :raises: RedfishError if physical drives cannot fulfill the logical disk.
    """
    # TODO(billdodd): match e.g. {'size': '> 100'} -> oslo_utils.specs_matcher
    selected_disks = [disk for disk in physical_disks
                      if disk.identity in logical_disk['physical_disks']]

    spans_count = _calculate_spans(
        logical_disk['raid_level'], len(selected_disks))

    if spans_count == 0 or len(selected_disks) % spans_count != 0:
        error_msg = _('For RAID level %(raid_level)s, the number of physical '
                      'disks provided (%(num_disks)s) must be a multiple of '
                      'the spans count (%(spans_count)s)' %
                      {'raid_level': logical_disk['raid_level'],
                       'num_disks': len(selected_disks),
                       'spans_count': spans_count})
        raise exception.RedfishError(error=error_msg)

    disks_per_span = len(selected_disks) / spans_count

    # TODO(billdodd): confirm this?
    # Best practice is to not pass span_length and span_depth when creating a
    # RAID10. Redfish will dynamically calculate these values using maximum
    # values obtained from the RAID controller.
    logical_disk['span_depth'] = None
    logical_disk['span_length'] = None
    if logical_disk['raid_level'] != '1+0':
        logical_disk['span_depth'] = spans_count
        logical_disk['span_length'] = disks_per_span

    max_volume_size_bytes = _max_volume_size_bytes(
        logical_disk['raid_level'], selected_disks, free_space_bytes,
        spans_count=spans_count)

    if logical_disk['size_bytes'] == 'MAX':
        if max_volume_size_bytes == 0:
            error_msg = _("size set to 'MAX' but could not allocate physical "
                          "disk space")
            raise exception.RedfishError(error=error_msg)

        logical_disk['size_bytes'] = max_volume_size_bytes
    elif max_volume_size_bytes < logical_disk['size_bytes']:
        error_msg = _('The physical disk space (%(max_vol_size)s bytes) is '
                      'not enough for the size of the logical disk '
                      '(%(logical_size)s bytes)' %
                      {'max_vol_size': max_volume_size_bytes,
                       'logical_size': logical_disk['size_bytes']})
        raise exception.RedfishError(error=error_msg)

    disk_usage = _volume_usage_per_disk_bytes(logical_disk, selected_disks,
                                              spans_count=spans_count)

    for disk in selected_disks:
        if free_space_bytes[disk] < disk_usage:
            error_msg = _('The free space of a disk (%(free_space)s bytes) '
                          'is not enough for the per-disk size of the logical '
                          'disk (%(disk_usage)s bytes)' %
                          {'free_space': free_space_bytes[disk],
                           'disk_usage': disk_usage})
            raise exception.RedfishError(error=error_msg)
        else:
            free_space_bytes[disk] -= disk_usage

    if 'controller' not in logical_disk:
        storage = disk_to_storage[selected_disks[0]]
        if storage:
            logical_disk['controller'] = storage.identity


def _raid_level_min_disks(raid_level, spans_count=1):
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        _raise_raid_level_not_supported(raid_level)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.RedfishError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['min_disks'] * spans_count


def _raid_level_max_disks(raid_level, spans_count=1):
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        _raise_raid_level_not_supported(raid_level)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.RedfishError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['max_disks'] * spans_count


def _usable_disks_count(raid_level, disks_count):
    """Calculates the number of disks usable for a RAID level

    ...given a physical disk count

    :param raid_level: RAID level of the virtual disk.
    :param disks_count: number of physical disks used for the virtual disk.
    :returns: number of disks.
    :raises: RedfishError if RAID level is not supported.
    """
    if raid_level in ['0', '1', '5', '6']:
        return disks_count
    elif raid_level in ['5+0', '6+0', '1+0']:
        # largest even number less than disk_count
        return (disks_count >> 1) << 1
    else:
        _raise_raid_level_not_supported(raid_level)


def _assign_disks_to_volume(logical_disks, physical_disks_by_type,
                            free_space_bytes, disk_to_storage):
    logical_disk = logical_disks.pop(0)
    raid_level = logical_disk['raid_level']

    # iterate over all possible configurations
    for (disk_type,
         protocol, size_bytes), disks in physical_disks_by_type.items():
        if ('disk_type' in logical_disk
                and logical_disk['disk_type'].lower() != disk_type.lower()):
            continue
        if ('interface_type' in logical_disk
                and logical_disk['interface_type'].lower()
                != PROTOCOL_MAP[protocol].lower()):
            continue

        # filter out disks without free disk space
        disks = [disk for disk in disks if free_space_bytes[disk] > 0]

        # sort disks by free size which is important if we have max disks limit
        # on a volume
        disks = sorted(
            disks,
            key=lambda disk: free_space_bytes[disk])

        # filter out disks already in use if sharing is disabled
        if ('share_physical_disks' not in logical_disk
                or not logical_disk['share_physical_disks']):
            disks = [disk for disk in disks
                     if disk.capacity_bytes == free_space_bytes[disk]]

        max_spans = _calculate_spans(raid_level, len(disks))
        min_spans = min([2, max_spans])
        min_disks = _raid_level_min_disks(raid_level,
                                          spans_count=min_spans)
        max_disks = _raid_level_max_disks(raid_level,
                                          spans_count=max_spans)
        candidate_max_disks = min([max_disks, len(disks)])

        for disks_count in range(min_disks, candidate_max_disks + 1):
            if ('number_of_physical_disks' in logical_disk
                    and logical_disk[
                        'number_of_physical_disks'] != disks_count):
                continue

            # skip invalid disks_count
            if disks_count != _usable_disks_count(logical_disk['raid_level'],
                                                  disks_count):
                continue

            selected_disks = disks[0:disks_count]

            candidate_volume = logical_disk.copy()
            candidate_free_space_bytes = free_space_bytes.copy()
            candidate_volume['physical_disks'] = [disk.identity for disk
                                                  in selected_disks]
            try:
                _calculate_volume_props(candidate_volume, selected_disks,
                                        candidate_free_space_bytes,
                                        disk_to_storage)
            except exception.RedfishError as exc:
                LOG.debug('Caught RedfishError in _calculate_volume_props(). '
                          'Reason: %s', exc)
                continue

            if len(logical_disks) > 0:
                try:
                    result, candidate_free_space_bytes = (
                        _assign_disks_to_volume(logical_disks,
                                                physical_disks_by_type,
                                                candidate_free_space_bytes,
                                                disk_to_storage))
                except exception.RedfishError as exc:
                    LOG.debug('Caught RedfishError in '
                              '_assign_disks_to_volume(). Reason: %s', exc)
                    continue
                if result:
                    logical_disks.append(candidate_volume)
                    return True, candidate_free_space_bytes
            else:
                logical_disks.append(candidate_volume)
                return True, candidate_free_space_bytes
    else:
        # put back the logical_disk to queue
        logical_disks.insert(0, logical_disk)
        return False, free_space_bytes


def _find_configuration(logical_disks, physical_disks, disk_to_storage):
    """Find RAID configuration.

    This method transforms the RAID configuration defined in Ironic to a format
    that is required by sushy. This includes matching the physical disks
    to RAID volumes when it's not pre-defined, or in general calculating
    missing properties.
    """

    # shared physical disks of RAID volumes size_gb='MAX' should be
    # de-prioritized during the matching process to reserve as much space as
    # possible. Reserved means it won't be used during matching.
    volumes_with_reserved_physical_disks = [
        volume for volume in logical_disks
        if ('physical_disks' in volume and volume['size_bytes'] == 'MAX'
            and volume.get('share_physical_disks', False))]
    reserved_physical_disks = [
        disk for disk in physical_disks
        for volume in volumes_with_reserved_physical_disks
        if disk.identity in volume['physical_disks']]

    # we require each logical disk contain only homogeneous physical disks, so
    # sort them by type
    physical_disks_by_type = {}
    reserved_physical_disks_by_type = {}
    free_space_bytes = {}
    for disk in physical_disks:
        # calculate free disk space
        # NOTE(billdodd): This won't be true if part of the drive is being used
        #     by an existing Volume, but has some space available for new
        #     Volumes. Redfish and/or SNIA may address this case in future.
        free_space_bytes[disk] = disk.capacity_bytes

        disk_type = (disk.media_type, disk.protocol, disk.capacity_bytes)
        if disk_type not in physical_disks_by_type:
            physical_disks_by_type[disk_type] = []
            reserved_physical_disks_by_type[disk_type] = []

        if disk in reserved_physical_disks:
            reserved_physical_disks_by_type[disk_type].append(disk)
        else:
            physical_disks_by_type[disk_type].append(disk)

    # exclude non-shared physical disks (predefined by the user) from
    # physical_disks_by_type because they are not going to be used during
    # matching
    for volume in logical_disks:
        if ('physical_disks' in volume
                and not volume.get('share_physical_disks', False)):
            for disk in physical_disks:
                if disk.identity in volume['physical_disks']:
                    disk_type = (disk.media_type, disk.protocol,
                                 disk.capacity_bytes)
                    if disk in physical_disks_by_type[disk_type]:
                        physical_disks_by_type[disk_type].remove(disk)

    processed_volumes = []

    # step 1 - process volumes with predefined disks and exact size
    for volume in [volume for volume in logical_disks
                   if ('physical_disks' in volume
                       and volume['size_bytes'] != 'MAX')]:
        _calculate_volume_props(volume, physical_disks, free_space_bytes,
                                disk_to_storage)
        processed_volumes.append(volume)

    # step 2 - process volumes without predefined disks
    volumes_without_disks = [disk for disk in logical_disks
                             if 'physical_disks' not in disk]

    if volumes_without_disks:
        result, free_space_bytes = (
            _assign_disks_to_volume(volumes_without_disks,
                                    physical_disks_by_type, free_space_bytes,
                                    disk_to_storage))
        if not result:
            # try again using the reserved physical disks in addition
            for disk_type, disks in physical_disks_by_type.items():
                physical_disks_by_type[disk_type] += (
                    reserved_physical_disks_by_type[disk_type])

            result, free_space_bytes = (
                _assign_disks_to_volume(volumes_without_disks,
                                        physical_disks_by_type,
                                        free_space_bytes,
                                        disk_to_storage))
            if not result:
                error_msg = _('failed to find matching physical disks for all '
                              'logical disks')
                LOG.error('Redfish driver failed to create RAID '
                          'configuration. Reason: %(error)s.',
                          {'error': error_msg})
                raise exception.RedfishError(error=error_msg)

    processed_volumes += volumes_without_disks

    # step 3 - process volumes with predefined disks and size_bytes == 'MAX'
    for volume in [volume for volume in logical_disks
                   if ('physical_disks' in volume
                       and volume['size_bytes'] == 'MAX')]:
        _calculate_volume_props(volume, physical_disks, free_space_bytes,
                                disk_to_storage)
        processed_volumes.append(volume)

    return processed_volumes


def _filter_logical_disks(logical_disks, include_root_volume,
                          include_nonroot_volumes):
    filtered_disks = []
    for disk in logical_disks:
        if include_root_volume and disk.get('is_root_volume'):
            filtered_disks.append(disk)

        if include_nonroot_volumes and not disk.get('is_root_volume'):
            filtered_disks.append(disk)

    return filtered_disks


def _get_storage_controller(node, system, physical_disks):
    collection = system.storage
    for storage in collection.get_members():
        # Using first controller as expecting only one
        controller = (storage.storage_controllers[0]
                      if storage.storage_controllers else None)
        if controller and controller.raid_types == []:
            continue
        for drive in storage.drives:
            if drive.identity in physical_disks:
                return storage


def _drive_path(storage, drive_id):
    for drive in storage.drives:
        if drive.identity == drive_id:
            return drive._path


def _construct_volume_payload(
        node, storage, raid_controller, physical_disks, raid_level, size_bytes,
        disk_name=None, span_length=None, span_depth=None):
    payload = {'Encrypted': False,
               'VolumeType': RAID_LEVELS[raid_level]['volume_type'],
               'RAIDType': RAID_LEVELS[raid_level]['raid_type'],
               'CapacityBytes': size_bytes}
    if physical_disks:
        payload['Links'] = {
            "Drives": [{"@odata.id": _drive_path(storage, d)} for d in
                       physical_disks]
        }
    LOG.debug('Payload for RAID logical disk creation on node %(node_uuid)s: '
              '%(payload)r', {'node': node.uuid, 'payload': payload})
    return payload


def create_virtual_disk(task, raid_controller, physical_disks, raid_level,
                        size_bytes, disk_name=None, span_length=None,
                        span_depth=None, error_handler=None):
    """Create a single virtual disk on a RAID controller.

    :param task: TaskManager object containing the node.
    :param raid_controller: id of the RAID controller.
    :param physical_disks: ids of the physical disks.
    :param raid_level: RAID level of the virtual disk.
    :param size_bytes: size of the virtual disk.
    :param disk_name: name of the virtual disk. (optional)
    :param span_depth: Number of spans in virtual disk. (optional)
    :param span_length: Number of disks per span. (optional)
    :param error_handler: function to call if volume create fails. (optional)
    :returns: Newly created Volume resource or TaskMonitor if async task.
    :raises: RedfishConnectionError when it fails to connect to Redfish.
    :raises: RedfishError if there is an error creating the virtual disk.
    """
    node = task.node
    system = redfish_utils.get_system(node)
    storage = _get_storage_controller(node, system, physical_disks)
    if not storage:
        reason = _('No storage controller found for node %(node_uuid)s' %
                   {'node_uuid': node.uuid})
        raise exception.RedfishError(error=reason)
    volume_collection = storage.volumes

    apply_time = None
    apply_time_support = volume_collection.operation_apply_time_support
    if apply_time_support and apply_time_support.mapped_supported_values:
        supported_values = apply_time_support.mapped_supported_values
        if sushy.APPLY_TIME_IMMEDIATE in supported_values:
            apply_time = sushy.APPLY_TIME_IMMEDIATE
        elif sushy.APPLY_TIME_ON_RESET in supported_values:
            apply_time = sushy.APPLY_TIME_ON_RESET
    payload = _construct_volume_payload(
        node, storage, raid_controller, physical_disks, raid_level, size_bytes,
        disk_name=disk_name, span_length=span_length, span_depth=span_depth)

    try:
        return volume_collection.create(payload, apply_time=apply_time)
    except sushy.exceptions.SushyError as exc:
        msg = ('Redfish driver failed to create virtual disk for node '
               '%(node_uuid)s. Reason: %(error)s.')
        if error_handler:
            try:
                return error_handler(task, exc, volume_collection, payload)
            except sushy.exceptions.SushyError as exc:
                LOG.error(msg, {'node_uuid': node.uuid, 'error': exc})
                raise exception.RedfishError(error=exc)
        LOG.error(msg, {'node_uuid': node.uuid, 'error': exc})
        raise exception.RedfishError(error=exc)


class RedfishRAID(base.RAIDInterface):

    def __init__(self):
        super(RedfishRAID, self).__init__()
        if sushy is None:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_("Unable to import the sushy library"))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def _validate_vendor(self, task):
        vendor = task.node.properties.get('vendor')
        if not vendor:
            return

        if 'dell' in vendor.lower().split():
            raise exception.InvalidParameterValue(
                _("The %(iface)s raid interface is not suitable for node "
                  "%(node)s with vendor %(vendor)s, use idrac-redfish instead")
                % {'iface': task.node.get_interface('raid'),
                   'node': task.node.uuid, 'vendor': vendor})

    def validate(self, task):
        """Validates the RAID Interface.

        This method validates the properties defined by Ironic for RAID
        configuration. Driver implementations of this interface can override
        this method for doing more validations (such as BMC's credentials).

        :param task: A TaskManager instance.
        :raises: InvalidParameterValue, if the RAID configuration is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        self._validate_vendor(task)
        super(RedfishRAID, self).validate(task)

    def validate_raid_config(self, task, raid_config):
        """Validates the given RAID configuration.

        :param task: A TaskManager instance.
        :param raid_config: The RAID configuration to validate.
        :raises: InvalidParameterValue, if the RAID configuration is invalid.
        """

        super(RedfishRAID, self).validate_raid_config(task, raid_config)

        # Check if any interface_type is scsi that is not supported by Redfish
        scsi_disks = ([x for x in raid_config['logical_disks']
                      if x.get('interface_type') == raid.SCSI])

        if len(scsi_disks) > 0:
            raise exception.InvalidParameterValue(
                _('interface type `scsi` not supported by Redfish RAID'))

    @base.deploy_step(priority=0,
                      argsinfo=base.RAID_APPLY_CONFIGURATION_ARGSINFO)
    def apply_configuration(self, task, raid_config, create_root_volume=True,
                            create_nonroot_volumes=False,
                            delete_existing=False):
        return super(RedfishRAID, self).apply_configuration(
            task, raid_config, create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes,
            delete_existing=delete_existing)

    @base.clean_step(priority=0, abortable=False, argsinfo={
        'create_root_volume': {
            'description': (
                'This specifies whether to create the root volume. '
                'Defaults to `True`.'
            ),
            'required': False
        },
        'create_nonroot_volumes': {
            'description': (
                'This specifies whether to create the non-root volumes. '
                'Defaults to `True`.'
            ),
            'required': False
        },
        'delete_existing': {
            'description': (
                'Setting this to `True` indicates to delete existing RAID '
                'configuration prior to creating the new configuration. '
                'Default value is `False`.'
            ),
            'required': False,
        }
    })
    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True,
                             delete_existing=False):
        """Create RAID configuration on the node.

        This method creates the RAID configuration as read from
        node.target_raid_config.  This method
        by default will create all logical disks.

        :param task: TaskManager object containing the node.
        :param create_root_volume: Setting this to False indicates
            not to create root volume that is specified in the node's
            target_raid_config. Default value is True.
        :param create_nonroot_volumes: Setting this to False indicates
            not to create non-root volumes (all except the root volume) in
            the node's target_raid_config.  Default value is True.
        :param delete_existing: Setting this to True indicates to delete RAID
            configuration prior to creating the new configuration. Default is
            False.
        :returns: states.CLEANWAIT if RAID configuration is in progress
            asynchronously or None if it is complete.
        :raises: RedfishError if there is an error creating the configuration
        """
        node = task.node

        logical_disks = node.target_raid_config['logical_disks']
        convert_drive_units(logical_disks, node)
        physical_disks, disk_to_storage = get_physical_disks(node)
        # TODO(billdodd): filter out physical disks that are already in use?
        #                 filter out disks with HotSpareType != "None"?
        logical_disks = _find_configuration(logical_disks, physical_disks,
                                            disk_to_storage)

        logical_disks_to_create = _filter_logical_disks(
            logical_disks, create_root_volume, create_nonroot_volumes)

        logical_disks_to_create = self.pre_create_configuration(
            task, logical_disks_to_create)

        reboot_required = False
        raid_configs = list()
        for logical_disk in logical_disks_to_create:
            raid_config = dict()
            response = create_virtual_disk(
                task,
                raid_controller=logical_disk.get('controller'),
                physical_disks=logical_disk['physical_disks'],
                raid_level=logical_disk['raid_level'],
                size_bytes=logical_disk['size_bytes'],
                disk_name=logical_disk.get('name'),
                span_length=logical_disk.get('span_length'),
                span_depth=logical_disk.get('span_depth'),
                error_handler=self.volume_create_error_handler)
            # only save the async tasks (task_monitors) in raid_config
            if (response is not None
                    and hasattr(response, 'task_monitor_uri')):
                raid_config['operation'] = 'create'
                raid_config['raid_controller'] = logical_disk.get(
                    'controller')
                raid_config['task_monitor_uri'] = response.task_monitor_uri
                reboot_required = True
                raid_configs.append(raid_config)

        node.set_driver_internal_info('raid_configs', raid_configs)

        return_state = None
        deploy_utils.set_async_step_flags(
            node,
            reboot=reboot_required,
            skip_current_step=True,
            polling=True)
        if reboot_required:
            return_state = deploy_utils.reboot_to_finish_step(task)

        return self.post_create_configuration(
            task, raid_configs, return_state=return_state)

    @base.clean_step(priority=0)
    @base.deploy_step(priority=0)
    def delete_configuration(self, task):
        """Delete RAID configuration on the node.

        :param task: TaskManager object containing the node.
        :returns: states.CLEANWAIT (cleaning) or states.DEPLOYWAIT (deployment)
            if deletion is in progress asynchronously or None if it is
            complete.
        """
        node = task.node
        system = redfish_utils.get_system(node)
        vols_to_delete = []
        try:
            for storage in system.storage.get_members():
                controller = (storage.storage_controllers[0]
                              if storage.storage_controllers else None)
                controller_id = None
                if controller:
                    controller_id = storage.identity
                for volume in storage.volumes.get_members():
                    if (volume.raid_type or volume.volume_type not in
                            [None, sushy.VOLUME_TYPE_RAW_DEVICE]):
                        vols_to_delete.append((storage.volumes, volume,
                                               controller_id))
        except sushy.exceptions.SushyError as exc:
            error_msg = _('Cannot get the list of volumes to delete for node '
                          '%(node_uuid)s. Reason: %(error)s.' %
                          {'node_uuid': node.uuid, 'error': exc})
            LOG.error(error_msg)
            raise exception.RedfishError(error=exc)

        self.pre_delete_configuration(task, vols_to_delete)

        reboot_required = False
        raid_configs = list()
        for vol_coll, volume, controller_id in vols_to_delete:
            raid_config = dict()
            apply_time = None
            apply_time_support = vol_coll.operation_apply_time_support
            if (apply_time_support
                    and apply_time_support.mapped_supported_values):
                supported_values = apply_time_support.mapped_supported_values
                if sushy.APPLY_TIME_IMMEDIATE in supported_values:
                    apply_time = sushy.APPLY_TIME_IMMEDIATE
                elif sushy.APPLY_TIME_ON_RESET in supported_values:
                    apply_time = sushy.APPLY_TIME_ON_RESET
            response = volume.delete(apply_time=apply_time)
            # only save the async tasks (task_monitors) in raid_config
            if (response is not None
                    and hasattr(response, 'task_monitor_uri')):
                raid_config['operation'] = 'delete'
                raid_config['raid_controller'] = controller_id
                raid_config['task_monitor_uri'] = response.task_monitor_uri
                reboot_required = True
                raid_configs.append(raid_config)

        node.set_driver_internal_info('raid_configs', raid_configs)

        return_state = None
        deploy_utils.set_async_step_flags(
            node,
            reboot=reboot_required,
            skip_current_step=True,
            polling=True)
        if reboot_required:
            return_state = deploy_utils.reboot_to_finish_step(task)

        return self.post_delete_configuration(
            task, raid_configs, return_state=return_state)

    def volume_create_error_handler(self, task, exc, volume_collection,
                                    payload):
        """Handle error from failed VolumeCollection.create()

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action if the call to
        VolumeCollection.create() fails.

        :param task: a TaskManager instance containing the node to act on.
        :param exc: the exception raised by VolumeCollection.create().
        :param volume_collection: the sushy VolumeCollection instance.
        :param payload: the payload passed to the failed create().
        :returns: Newly created Volume resource or TaskMonitor if async task.
        :raises: RedfishError if there is an error creating the virtual disk.
        """
        raise exc

    def pre_create_configuration(self, task, logical_disks_to_create):
        """Perform required actions before creating config.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform custom actions prior to creating
        the RAID configuration on the Redfish service.

        :param task: a TaskManager instance containing the node to act on.
        :param logical_disks_to_create: list of logical disks to create.
        :returns: updated list of logical disks to create.
        """
        return logical_disks_to_create

    def post_create_configuration(self, task, raid_configs, return_state=None):
        """Perform post create_configuration action to commit the config.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to commit the
        RAID create configuration to the Redfish service.

        :param task: a TaskManager instance containing the node to act on.
        :param raid_configs: a list of dictionaries containing the RAID
                             configuration operation details.
        :param return_state: state to return based on operation being invoked
        """
        return return_state

    def pre_delete_configuration(self, task, vols_to_delete):
        """Perform required actions before deleting config.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform custom actions prior to deleting
        the RAID configuration on the Redfish service.

        :param task: a TaskManager instance containing the node to act on.
        :param vols_to_delete: list of volumes to delete.
        """
        pass

    def post_delete_configuration(self, task, raid_configs, return_state=None):
        """Perform post delete_configuration action to commit the config.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to commit the
        RAID delete configuration to the Redfish service.

        :param task: a TaskManager instance containing the node to act on.
        :param raid_configs: a list of dictionaries containing the RAID
                             configuration operation details.
        :param return_state: state to return based on operation being invoked
        """
        return return_state

    def _clear_raid_configs(self, node):
        """Clears RAID configurations from driver_internal_info

        Note that the caller must have an exclusive lock on the node.

        :param node: the node to clear the RAID configs from
        """
        node.del_driver_internal_info('raid_configs')
        node.save()

    @METRICS.timer('RedfishRAID._query_raid_config_failed')
    @periodics.node_periodic(
        purpose='checking async RAID config failed',
        spacing=CONF.redfish.raid_config_fail_interval,
        filters={'reserved': False, 'provision_state_in': {
            states.CLEANFAIL, states.DEPLOYFAIL}, 'maintenance': True},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('raid_configs'),
    )
    def _query_raid_config_failed(self, task, manager, context):
        """Periodic job to check for failed RAID configuration."""
        # A RAID config failed. Discard any remaining RAID
        # configs so when the user takes the node out of
        # maintenance mode, pending RAID configs do not
        # automatically continue.
        LOG.warning('RAID configuration failed for node %(node)s. '
                    'Discarding remaining RAID configurations.',
                    {'node': task.node.uuid})

        task.upgrade_lock()
        self._clear_raid_configs(task.node)

    @METRICS.timer('RedfishRAID._query_raid_config_status')
    @periodics.node_periodic(
        purpose='checking async RAID config tasks',
        spacing=CONF.redfish.raid_config_status_interval,
        filters={'reserved': False, 'provision_state_in': {
            states.CLEANWAIT, states.DEPLOYWAIT}},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('raid_configs'),
    )
    def _query_raid_config_status(self, task, manager, context):
        """Periodic job to check RAID config tasks."""
        self._check_node_raid_config(task)

    def _get_error_messages(self, response):
        try:
            body = response.json()
        except ValueError:
            return []
        else:
            error = body.get('error', {})
            code = error.get('code', '')
            message = error.get('message', code)
            ext_info = error.get('@Message.ExtendedInfo', [{}])
            messages = [m.get('Message') for m in ext_info if 'Message' in m]
            if not messages and message:
                messages = [message]
            return messages

    def _raid_config_in_progress(self, task, raid_config):
        """Check if this RAID configuration operation is still in progress."""
        task_monitor_uri = raid_config['task_monitor_uri']
        try:
            task_monitor = redfish_utils.get_task_monitor(task.node,
                                                          task_monitor_uri)
        except exception.RedfishError:
            LOG.info('Unable to get status of RAID %(operation)s task to node '
                     '%(node_uuid)s; assuming task completed successfully',
                     {'operation': raid_config['operation'],
                      'node_uuid': task.node.uuid})
            return False
        if task_monitor.is_processing:
            LOG.debug('RAID %(operation)s task %(task_mon)s to node '
                      '%(node_uuid)s still in progress',
                      {'operation': raid_config['operation'],
                       'task_mon': task_monitor.task_monitor_uri,
                       'node_uuid': task.node.uuid})
            return True
        else:
            response = task_monitor.response
            if response is not None:
                status_code = response.status_code
                if status_code >= 400:
                    messages = self._get_error_messages(response)
                    LOG.error('RAID %(operation)s task to node '
                              '%(node_uuid)s failed with status '
                              '%(status_code)s; messages: %(messages)s',
                              {'operation': raid_config['operation'],
                               'node_uuid': task.node.uuid,
                               'status_code': status_code,
                               'messages': ", ".join(messages)})
                else:
                    LOG.info('RAID %(operation)s task to node '
                             '%(node_uuid)s completed with status '
                             '%(status_code)s',
                             {'operation': raid_config['operation'],
                              'node_uuid': task.node.uuid,
                              'status_code': status_code})
        return False

    @METRICS.timer('RedfishRAID._check_node_raid_config')
    def _check_node_raid_config(self, task):
        """Check the progress of running RAID config on a node."""
        node = task.node
        raid_configs = node.driver_internal_info['raid_configs']

        task.upgrade_lock()
        raid_configs[:] = [i for i in raid_configs
                           if self._raid_config_in_progress(task, i)]

        if not raid_configs:
            self._clear_raid_configs(node)
            LOG.info('RAID configuration completed for node %(node)s',
                     {'node': node.uuid})
            if task.node.clean_step:
                manager_utils.notify_conductor_resume_clean(task)
            else:
                manager_utils.notify_conductor_resume_deploy(task)
