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

"""
DRAC RAID specific methods
"""

import math

from futurist import periodics
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import raid as raid_common
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job

drac_exceptions = importutils.try_import('dracclient.exceptions')
drac_constants = importutils.try_import('dracclient.constants')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

RAID_LEVELS = {
    '0': {
        'min_disks': 1,
        'max_disks': 1000,
        'type': 'simple',
        'overhead': 0
    },
    '1': {
        'min_disks': 2,
        'max_disks': 2,
        'type': 'simple',
        'overhead': 1
    },
    '5': {
        'min_disks': 3,
        'max_disks': 1000,
        'type': 'simple',
        'overhead': 1
    },
    '6': {
        'min_disks': 4,
        'max_disks': 1000,
        'type': 'simple',
        'overhead': 2
    },
    '1+0': {
        'type': 'spanned',
        'span_type': '1'
    },
    '5+0': {
        'type': 'spanned',
        'span_type': '5'
    },
    '6+0': {
        'type': 'spanned',
        'span_type': '6'
    }
}


def list_raid_controllers(node):
    """List the RAID controllers of the node.

    :param node: an ironic node object.
    :returns: a list of RAIDController objects from dracclient.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.list_raid_controllers()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the list of RAID controllers '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


def list_virtual_disks(node):
    """List the virtual disks of the node.

    :param node: an ironic node object.
    :returns: a list of VirtualDisk objects from dracclient.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.list_virtual_disks()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the list of virtual disks '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


def list_physical_disks(node):
    """List the physical disks of the node.

    :param node: an ironic node object.
    :returns: a list of PhysicalDisk objects from dracclient.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.list_physical_disks()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the list of physical disks '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


def _is_raid_controller(node, raid_controller_fqdd, raid_controllers=None):
    """Find out if object's fqdd is for a raid controller or not

    :param node: an ironic node object
    :param raid_controller_fqdd: The object's fqdd we are testing to see
                                 if it is a raid controller or not.
    :param raid_controllers: A list of RAIDControllers used to check for
                             the presence of BOSS cards.  If None, the
                             iDRAC will be queried for the list of
                             controllers.
    :returns: boolean, True if the device is a RAID controller,
              False if not.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.is_raid_controller(raid_controller_fqdd,
                                         raid_controllers)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('Unable to determine if controller %(raid_controller_fqdd)s '
                  'on node %(node_uuid)s is a RAID controller. '
                  'Reason: %(error)s. ',
                  {'raid_controller_fqdd': raid_controller_fqdd,
                   'node_uuid': node.uuid, 'error': exc})

        raise exception.DracOperationError(error=exc)


def create_virtual_disk(node, raid_controller, physical_disks, raid_level,
                        size_mb, disk_name=None, span_length=None,
                        span_depth=None):
    """Create a single virtual disk on a RAID controller.

    The created virtual disk will be in pending state. The DRAC card will do
    the actual configuration once the changes are applied by calling the
    ``commit_config`` method.

    :param node: an ironic node object.
    :param raid_controller: id of the RAID controller.
    :param physical_disks: ids of the physical disks.
    :param raid_level: RAID level of the virtual disk.
    :param size_mb: size of the virtual disk.
    :param disk_name: name of the virtual disk. (optional)
    :param span_depth: Number of spans in virtual disk. (optional)
    :param span_length: Number of disks per span. (optional)
    :returns: a dictionary containing the commit_needed key with a boolean
              value indicating whether a config job must be created for the
              values to be applied.
    :raises: DracOperationError on an error from python-dracclient.
    """
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)

    try:
        return client.create_virtual_disk(raid_controller, physical_disks,
                                          raid_level, size_mb, disk_name,
                                          span_length, span_depth)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to create virtual disk for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def delete_virtual_disk(node, virtual_disk):
    """Delete a single virtual disk on a RAID controller.

    The deleted virtual disk will be in pending state. The DRAC card will do
    the actual configuration once the changes are applied by calling the
    ``commit_config`` method.

    :param node: an ironic node object.
    :param virtual_disk: id of the virtual disk.
    :returns: a dictionary containing the commit_needed key with a boolean
              value indicating whether a config job must be created for the
              values to be applied.
    :raises: DracOperationError on an error from python-dracclient.
    """
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)

    try:
        return client.delete_virtual_disk(virtual_disk)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to delete virtual disk '
                  '%(virtual_disk_fqdd)s for node %(node_uuid)s. '
                  'Reason: %(error)s.',
                  {'virtual_disk_fqdd': virtual_disk,
                   'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def _reset_raid_config(node, raid_controller):
    """Delete all virtual disk and unassign all hotspares physical disk

    :param node: an ironic node object.
    :param raid_controller: id of the RAID controller.
    :returns: a dictionary containing
              - The is_commit_required needed key with a
              boolean value indicating whether a config job must be created
              for the values to be applied.
              - The is_reboot_required key with a RebootRequired enumerated
              value indicating whether the server must be rebooted to
              reset configuration.
    :raises: DracOperationError on an error from python-dracclient.
    """
    try:

        drac_job.validate_job_queue(node)

        client = drac_common.get_drac_client(node)
        return client.reset_raid_config(raid_controller)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to delete all virtual disk '
                  'and unassign all hotspares '
                  'on %(raid_controller_fqdd)s '
                  'for node %(node_uuid)s. '
                  'Reason: %(error)s.',
                  {'raid_controller_fqdd': raid_controller,
                   'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def clear_foreign_config(node, raid_controller):
    """Free up the foreign drives.

    :param node: an ironic node object.
    :param raid_controller: id of the RAID controller.
    :returns: a dictionary containing
              - The is_commit_required needed key with a
              boolean value indicating whether a config job must be created
              for the values to be applied.
              - The is_reboot_required key with a RebootRequired enumerated
              value indicating whether the server must be rebooted to
              clear foreign configuration.
    :raises: DracOperationError on an error from python-dracclient.
    """
    try:

        drac_job.validate_job_queue(node)

        client = drac_common.get_drac_client(node)
        return client.clear_foreign_config(raid_controller)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to free foreign driver '
                  'on %(raid_controller_fqdd)s '
                  'for node %(node_uuid)s. '
                  'Reason: %(error)s.',
                  {'raid_controller_fqdd': raid_controller,
                   'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def commit_config(node, raid_controller, reboot=False, realtime=False):
    """Apply all pending changes on a RAID controller.

    :param node: an ironic node object.
    :param raid_controller: id of the RAID controller.
    :param reboot: indicates whether a reboot job should be automatically
                   created with the config job. (optional, defaults to False)
    :param realtime: indicates RAID controller supports realtime.
                     (optional, defaults to False)
    :returns: id of the created job
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.commit_pending_raid_changes(
            raid_controller=raid_controller,
            reboot=reboot,
            realtime=realtime)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to commit pending RAID config for'
                  ' controller %(raid_controller_fqdd)s on node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'raid_controller_fqdd': raid_controller,
                   'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def abandon_config(node, raid_controller):
    """Deletes all pending changes on a RAID controller.

    :param node: an ironic node object.
    :param raid_controller: id of the RAID controller.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        client.abandon_pending_raid_changes(raid_controller)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to delete pending RAID config '
                  'for controller %(raid_controller_fqdd)s on node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'raid_controller_fqdd': raid_controller,
                   'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def _calculate_spans(raid_level, disks_count):
    """Calculates number of spans for a RAID level given a physical disk count

    :param raid_level: RAID level of the virtual disk.
    :param disk_count: number of physical disks used for the virtual disk.
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
        raise exception.DracOperationError(error=reason)


def _usable_disks_count(raid_level, disks_count):
    """Calculates the number of disks usable for a RAID level

    ...given a physical disk count

    :param raid_level: RAID level of the virtual disk.
    :param disk_count: number of physical disks used for the virtual disk.
    :returns: number of disks.
    """
    if raid_level in ['0', '1', '5', '6']:
        return disks_count
    elif raid_level in ['5+0', '6+0', '1+0']:
        # largest even number less than disk_count
        return (disks_count >> 1) << 1
    else:
        reason = (_('RAID level %(raid_level)s is not supported by the '
                    'driver. Supported RAID levels: %(supported_raid_levels)s')
                  % {'raid_level': raid_level,
                     'supported_raid_levels': list(RAID_LEVELS)})
        raise exception.DracOperationError(error=reason)


def _raid_level_min_disks(raid_level, spans_count=1):
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        reason = (_('RAID level %(raid_level)s is not supported by the '
                    'driver. Supported RAID levels: %(supported_raid_levels)s')
                  % {'raid_level': raid_level,
                     'supported_raid_levels': list(RAID_LEVELS)})
        raise exception.DracOperationError(error=reason)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.DracOperationError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['min_disks'] * spans_count


def _raid_level_max_disks(raid_level, spans_count=1):
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        reason = (_('RAID level %(raid_level)s is not supported by the '
                    'driver. Supported RAID levels: %(supported_raid_levels)s')
                  % {'raid_level': raid_level,
                     'supported_raid_levels': list(RAID_LEVELS)})
        raise exception.DracOperationError(error=reason)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.DracOperationError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['max_disks'] * spans_count


def _raid_level_overhead(raid_level, spans_count=1):
    try:
        raid_level_info = RAID_LEVELS[raid_level]
    except KeyError:
        reason = (_('RAID level %(raid_level)s is not supported by the '
                    'driver. Supported RAID levels: %(supported_raid_levels)s')
                  % {'raid_level': raid_level,
                     'supported_raid_levels': list(RAID_LEVELS)})
        raise exception.DracOperationError(error=reason)

    if raid_level_info['type'] == 'spanned':
        if spans_count <= 1:
            reason = _('Spanned RAID volumes cannot contain a single span')
            raise exception.DracOperationError(error=reason)

        span_type = raid_level_info['span_type']
        raid_level_info = RAID_LEVELS[span_type]

    return raid_level_info['overhead'] * spans_count


def _max_volume_size_mb(raid_level, physical_disks, free_space_mb,
                        spans_count=1, stripe_size_kb=64 * units.Ki):
    # restrict the size to the smallest available space
    free_spaces = [free_space_mb[disk] for disk in physical_disks]
    size_kb = min(free_spaces) * units.Ki

    # NOTE(ifarkas): using math.floor so we get a volume size that does not
    #                exceed the available space
    stripes_per_disk = int(math.floor(float(size_kb) / stripe_size_kb))

    disks_count = len(physical_disks)
    overhead_disks_count = _raid_level_overhead(raid_level, spans_count)

    return int(stripes_per_disk * stripe_size_kb
               * (disks_count - overhead_disks_count) / units.Ki)


def _volume_usage_per_disk_mb(logical_disk, physical_disks, spans_count=1,
                              stripe_size_kb=64 * units.Ki):
    disks_count = len(physical_disks)
    overhead_disks_count = _raid_level_overhead(logical_disk['raid_level'],
                                                spans_count)
    volume_size_kb = logical_disk['size_mb'] * units.Ki
    # NOTE(ifarkas): using math.ceil so we get the largest disk usage
    #                possible, so we can avoid over-committing
    stripes_per_volume = math.ceil(float(volume_size_kb) / stripe_size_kb)

    stripes_per_disk = math.ceil(
        float(stripes_per_volume) / (disks_count - overhead_disks_count))
    return int(stripes_per_disk * stripe_size_kb / units.Ki)


def _find_configuration(logical_disks, physical_disks):
    """Find RAID configuration.

    This method transforms the RAID configuration defined in Ironic to a format
    that is required by dracclient. This includes matching the physical disks
    to RAID volumes when it's not pre-defined, or in general calculating
    missing properties.
    """

    # shared physical disks of RAID volumes size_gb='MAX' should be
    # deprioritized during the matching process to reserve as much space as
    # possible. Reserved means it won't be used during matching.
    volumes_with_reserved_physical_disks = [
        volume for volume in logical_disks
        if ('physical_disks' in volume and volume['size_mb'] == 'MAX'
            and volume.get('share_physical_disks', False))]
    reserved_physical_disks = [
        disk for disk in physical_disks
        for volume in volumes_with_reserved_physical_disks
        if disk.id in volume['physical_disks']]

    # we require each logical disk contain only homogeneous physical disks, so
    # sort them by type
    physical_disks_by_type = {}
    reserved_physical_disks_by_type = {}
    free_space_mb = {}
    for disk in physical_disks:
        # calculate free disk space
        free_space_mb[disk] = disk.free_size_mb

        disk_type = (disk.controller, disk.media_type, disk.interface_type,
                     disk.size_mb)
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
                if disk.id in volume['physical_disks']:
                    disk_type = (disk.controller, disk.media_type,
                                 disk.interface_type, disk.size_mb)
                    if disk in physical_disks_by_type[disk_type]:
                        physical_disks_by_type[disk_type].remove(disk)

    processed_volumes = []

    # step 1 - process volumes with predefined disks and exact size
    for volume in [volume for volume in logical_disks
                   if ('physical_disks' in volume
                       and volume['size_mb'] != 'MAX')]:
        _calculate_volume_props(volume, physical_disks, free_space_mb)
        processed_volumes.append(volume)

    # step 2 - process volumes without predefined disks
    volumes_without_disks = [disk for disk in logical_disks
                             if 'physical_disks' not in disk]

    if volumes_without_disks:
        result, free_space_mb = (
            _assign_disks_to_volume(volumes_without_disks,
                                    physical_disks_by_type, free_space_mb))
        if not result:
            # try again using the reserved physical disks in addition
            for disk_type, disks in physical_disks_by_type.items():
                physical_disks_by_type[disk_type] += (
                    reserved_physical_disks_by_type[disk_type])

            result, free_space_mb = (
                _assign_disks_to_volume(volumes_without_disks,
                                        physical_disks_by_type,
                                        free_space_mb))
            if not result:
                error_msg = _('failed to find matching physical disks for all '
                              'logical disks')
                LOG.error('DRAC driver failed to create RAID '
                          'configuration. Reason: %(error)s.',
                          {'error': error_msg})
                raise exception.DracOperationError(error=error_msg)

    processed_volumes += volumes_without_disks

    # step 3 - process volumes with predefined disks and size_mb == 'MAX'
    for volume in [volume for volume in logical_disks
                   if ('physical_disks' in volume
                       and volume['size_mb'] == 'MAX')]:
        _calculate_volume_props(volume, physical_disks, free_space_mb)
        processed_volumes.append(volume)

    return processed_volumes


def _calculate_volume_props(logical_disk, physical_disks, free_space_mb):
    selected_disks = [disk for disk in physical_disks
                      if disk.id in logical_disk['physical_disks']]

    spans_count = _calculate_spans(
        logical_disk['raid_level'], len(selected_disks))

    if len(selected_disks) % spans_count != 0:
        error_msg = _('invalid number of physical disks was provided')
        raise exception.DracOperationError(error=error_msg)

    disks_per_span = len(selected_disks) / spans_count

    # Best practice is to not pass span_length and span_depth when creating a
    # RAID10.  The iDRAC will dynamically calculate these values using maximum
    # values obtained from the RAID controller.
    logical_disk['span_depth'] = None
    logical_disk['span_length'] = None
    if logical_disk['raid_level'] != '1+0':
        logical_disk['span_depth'] = spans_count
        logical_disk['span_length'] = disks_per_span

    max_volume_size_mb = _max_volume_size_mb(
        logical_disk['raid_level'], selected_disks, free_space_mb,
        spans_count=spans_count)

    if logical_disk['size_mb'] == 'MAX':
        if max_volume_size_mb == 0:
            error_msg = _("size set to 'MAX' but could not allocate physical "
                          "disk space")
            raise exception.DracOperationError(error=error_msg)

        logical_disk['size_mb'] = max_volume_size_mb
    elif max_volume_size_mb < logical_disk['size_mb']:
        if max_volume_size_mb == 0:
            error_msg = _('not enough physical disk space for the logical '
                          'disk')
            raise exception.DracOperationError(error=error_msg)

    disk_usage = _volume_usage_per_disk_mb(logical_disk, selected_disks,
                                           spans_count=spans_count)

    for disk in selected_disks:
        if free_space_mb[disk] < disk_usage:
            error_msg = _('not enough free space on physical disks for the '
                          'logical disk')
            raise exception.DracOperationError(error=error_msg)
        else:
            free_space_mb[disk] -= disk_usage

    if 'controller' not in logical_disk:
        logical_disk['controller'] = selected_disks[0].controller


def _assign_disks_to_volume(logical_disks, physical_disks_by_type,
                            free_space_mb):
    logical_disk = logical_disks.pop(0)
    raid_level = logical_disk['raid_level']

    # iterate over all possible configurations
    for (controller, disk_type,
         interface_type, size_mb), disks in physical_disks_by_type.items():

        if ('disk_type' in logical_disk
            and logical_disk['disk_type'] != disk_type):
            continue

        if ('interface_type' in logical_disk
            and logical_disk['interface_type'] != interface_type):
            continue

        # filter out disks without free disk space
        disks = [disk for disk in disks if free_space_mb[disk] > 0]

        # sort disks by free size which is important if we have max disks limit
        # on a volume
        disks = sorted(
            disks,
            key=lambda disk: free_space_mb[disk])

        # filter out disks already in use if sharing is disabled
        if ('share_physical_disks' not in logical_disk
                or not logical_disk['share_physical_disks']):
            disks = [disk for disk in disks
                     if disk.free_size_mb == free_space_mb[disk]]

        max_spans = _calculate_spans(raid_level, len(disks))
        min_spans = min([2, max_spans])
        min_disks = _raid_level_min_disks(raid_level,
                                          spans_count=min_spans)
        max_disks = _raid_level_max_disks(raid_level,
                                          spans_count=max_spans)
        candidate_max_disks = min([max_disks, len(disks)])

        for disks_count in range(min_disks, candidate_max_disks + 1):
            if ('number_of_physical_disks' in logical_disk
                and logical_disk['number_of_physical_disks'] != disks_count):
                    continue

            # skip invalid disks_count
            if disks_count != _usable_disks_count(logical_disk['raid_level'],
                                                  disks_count):
                continue

            selected_disks = disks[0:disks_count]

            candidate_volume = logical_disk.copy()
            candidate_free_space_mb = free_space_mb.copy()
            candidate_volume['physical_disks'] = [disk.id for disk
                                                  in selected_disks]
            try:
                _calculate_volume_props(candidate_volume, selected_disks,
                                        candidate_free_space_mb)
            except exception.DracOperationError:
                continue

            if len(logical_disks) > 0:
                result, candidate_free_space_mb = (
                    _assign_disks_to_volume(logical_disks,
                                            physical_disks_by_type,
                                            candidate_free_space_mb))
                if result:
                    logical_disks.append(candidate_volume)
                    return (True, candidate_free_space_mb)
            else:
                logical_disks.append(candidate_volume)
                return (True, candidate_free_space_mb)
    else:
        # put back the logical_disk to queue
        logical_disks.insert(0, logical_disk)
        return (False, free_space_mb)


def _filter_logical_disks(logical_disks, include_root_volume,
                          include_nonroot_volumes):
    filtered_disks = []
    for disk in logical_disks:
        if include_root_volume and disk.get('is_root_volume'):
            filtered_disks.append(disk)

        if include_nonroot_volumes and not disk.get('is_root_volume'):
            filtered_disks.append(disk)

    return filtered_disks


def _commit_to_controllers(node, controllers, substep="completed"):
    """Commit changes to RAID controllers on the node.

    :param node: an ironic node object
    :param controllers: a list of dictionary containing
                        - The raid_controller key with raid controller
                        fqdd value indicating on which raid configuration
                        job needs to be perform.
                        - The is_commit_required needed key with a
                        boolean value indicating whether a config job must
                        be created.
                        - The is_reboot_required key with a RebootRequired
                        enumerated value indicating whether the server must
                        be rebooted only if raid controller does not support
                        realtime.
    :param substep: contain sub cleaning step which executes any raid
                    configuration job if set after cleaning step.
                    (default to completed)
    :returns: states.CLEANWAIT if deletion is in progress asynchronously
              or None if it is completed.
    """
    if not controllers:
        LOG.debug('No changes on any of the controllers on node %s',
                  node.uuid)
        return

    driver_internal_info = node.driver_internal_info
    driver_internal_info['raid_config_substep'] = substep
    driver_internal_info['raid_config_parameters'] = []

    if 'raid_config_job_ids' not in driver_internal_info:
        driver_internal_info['raid_config_job_ids'] = []

    all_realtime = True
    optional = drac_constants.RebootRequired.optional
    for controller in controllers:
        raid_controller = controller['raid_controller']

        # Commit the configuration
        # The logic below will reboot the node if there is at least one
        # controller without real time support. In that case the reboot
        # is triggered when the configuration is committed to the last
        # controller.

        realtime = controller['is_reboot_required'] == optional
        all_realtime = all_realtime and realtime
        if controller == controllers[-1]:
            job_id = commit_config(node, raid_controller=raid_controller,
                                   reboot=not all_realtime,
                                   realtime=realtime)
        else:
            job_id = commit_config(node, raid_controller=raid_controller,
                                   reboot=False,
                                   realtime=realtime)

        LOG.info('Change has been committed to RAID controller '
                 '%(controller)s on node %(node)s. '
                 'DRAC job id: %(job_id)s',
                 {'controller': controller, 'node': node.uuid,
                  'job_id': job_id})

        driver_internal_info['raid_config_job_ids'].append(job_id)

        if raid_controller not in driver_internal_info[
                'raid_config_parameters']:
            driver_internal_info['raid_config_parameters'].append(
                raid_controller)

    node.driver_internal_info = driver_internal_info
    node.save()

    return states.CLEANWAIT


class DracRAID(base.RAIDInterface):

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracRAID.create_configuration')
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
        }
    })
    def create_configuration(self, task,
                             create_root_volume=True,
                             create_nonroot_volumes=True):
        """Create the RAID configuration.

        This method creates the RAID configuration on the given node.

        :param task: a TaskManager instance containing the node to act on.
        :param create_root_volume: If True, a root volume is created
            during RAID configuration. Otherwise, no root volume is
            created. Default is True.
        :param create_nonroot_volumes: If True, non-root volumes are
            created. If False, no non-root volumes are created. Default
            is True.
        :returns: states.CLEANWAIT if creation is in progress asynchronously
                  or None if it is completed.
        :raises: MissingParameterValue, if node.target_raid_config is missing
            or empty.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        logical_disks = node.target_raid_config['logical_disks']
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
                disk['size_mb'] = 'MAX'
            else:
                disk['size_mb'] = disk['size_gb'] * units.Ki

            del disk['size_gb']

        physical_disks = list_physical_disks(node)
        logical_disks = _find_configuration(logical_disks, physical_disks)

        logical_disks_to_create = _filter_logical_disks(
            logical_disks, create_root_volume, create_nonroot_volumes)

        controllers = list()
        for logical_disk in logical_disks_to_create:
            controller = dict()
            controller_cap = create_virtual_disk(
                node,
                raid_controller=logical_disk['controller'],
                physical_disks=logical_disk['physical_disks'],
                raid_level=logical_disk['raid_level'],
                size_mb=logical_disk['size_mb'],
                disk_name=logical_disk.get('name'),
                span_length=logical_disk.get('span_length'),
                span_depth=logical_disk.get('span_depth'))
            controller['raid_controller'] = logical_disk['controller']
            controller['is_reboot_required'] = controller_cap[
                'is_reboot_required']
            if controller not in controllers:
                controllers.append(controller)

        return _commit_to_controllers(node, controllers)

    @METRICS.timer('DracRAID.delete_configuration')
    @base.clean_step(priority=0)
    def delete_configuration(self, task):
        """Delete the RAID configuration.

        :param task: a TaskManager instance containing the node to act on.
        :returns: states.CLEANWAIT if deletion is in progress asynchronously
                  or None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        controllers = list()
        drac_raid_controllers = list_raid_controllers(node)
        for cntrl in drac_raid_controllers:
            if _is_raid_controller(node, cntrl.id, drac_raid_controllers):
                controller = dict()
                controller_cap = _reset_raid_config(node, cntrl.id)
                controller["raid_controller"] = cntrl.id
                controller["is_reboot_required"] = controller_cap[
                    "is_reboot_required"]
                controllers.append(controller)

        return _commit_to_controllers(node, controllers,
                                      substep="delete_foreign_config")

    @METRICS.timer('DracRAID.get_logical_disks')
    def get_logical_disks(self, task):
        """Get the RAID configuration of the node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: A dictionary of properties.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        logical_disks = []
        for disk in list_virtual_disks(node):
            logical_disk = {
                'id': disk.id,
                'controller': disk.controller,
                'size_gb': int(disk.size_mb / units.Ki),
                'raid_level': disk.raid_level
            }

            if disk.name is not None:
                logical_disk['name'] = disk.name

            logical_disks.append(logical_disk)

        return {'logical_disks': logical_disks}

    @METRICS.timer('DracRAID._query_raid_config_job_status')
    @periodics.periodic(
        spacing=CONF.drac.query_raid_config_job_status_interval)
    def _query_raid_config_job_status(self, manager, context):
        """Periodic task to check the progress of running RAID config jobs."""

        filters = {'reserved': False, 'maintenance': False}
        fields = ['driver_internal_info']

        node_list = manager.iter_nodes(fields=fields, filters=filters)
        for (node_uuid, driver, conductor_group,
             driver_internal_info) in node_list:
            try:
                lock_purpose = 'checking async raid configuration jobs'
                with task_manager.acquire(context, node_uuid,
                                          purpose=lock_purpose,
                                          shared=True) as task:
                    if not isinstance(task.driver.raid, DracRAID):
                        continue

                    job_ids = driver_internal_info.get('raid_config_job_ids')
                    if not job_ids:
                        continue

                    self._check_node_raid_jobs(task)

            except exception.NodeNotFound:
                LOG.info("During query_raid_config_job_status, node "
                         "%(node)s was not found and presumed deleted by "
                         "another process.", {'node': node_uuid})
            except exception.NodeLocked:
                LOG.info("During query_raid_config_job_status, node "
                         "%(node)s was already locked by another process. "
                         "Skip.", {'node': node_uuid})

    @METRICS.timer('DracRAID._check_node_raid_jobs')
    def _check_node_raid_jobs(self, task):
        """Check the progress of running RAID config jobs of a node."""

        node = task.node
        raid_config_job_ids = node.driver_internal_info['raid_config_job_ids']
        finished_job_ids = []

        for config_job_id in raid_config_job_ids:
            config_job = drac_job.get_job(node, job_id=config_job_id)

            if config_job is None or config_job.status == 'Completed':
                finished_job_ids.append(config_job_id)
            elif config_job.status == 'Failed':
                finished_job_ids.append(config_job_id)
                self._set_raid_config_job_failure(node)

        if not finished_job_ids:
            return

        task.upgrade_lock()
        self._delete_cached_config_job_id(node, finished_job_ids)

        if not node.driver_internal_info.get('raid_config_job_failure',
                                             False):
            if 'raid_config_substep' in node.driver_internal_info:
                if node.driver_internal_info['raid_config_substep'] == \
                        'delete_foreign_config':
                    self._execute_cleaning_foreign_drives(task, node)
                elif node.driver_internal_info['raid_config_substep'] == \
                        'completed':
                    self._complete_raid_cleaning_substep(task, node)
            else:
                self._complete_raid_cleaning_substep(task, node)
        else:
            self._clear_raid_substep(node)
            self._clear_raid_config_job_failure(node)
            self._set_clean_failed(task, config_job)

    def _execute_cleaning_foreign_drives(self, task, node):
        controllers = list()
        jobs_required = False
        for controller_id in node.driver_internal_info[
                'raid_config_parameters']:
            controller_cap = clear_foreign_config(
                node, controller_id)
            controller = {'raid_controller': controller_id,
                          'is_reboot_required':
                              controller_cap[
                                  'is_reboot_required']}
            controllers.append(controller)
            jobs_required = jobs_required or controller_cap[
                'is_commit_required']

        if not jobs_required:
            LOG.info(
                "No foreign drives detected, so "
                "resume cleaning")
            self._complete_raid_cleaning_substep(task, node)
        else:
            _commit_to_controllers(
                node,
                controllers,
                substep='completed')

    def _complete_raid_cleaning_substep(self, task, node):
        self._clear_raid_substep(node)
        self._resume_cleaning(task)

    def _clear_raid_substep(self, node):
        driver_internal_info = node.driver_internal_info
        driver_internal_info.pop('raid_config_substep', None)
        driver_internal_info.pop('raid_config_parameters', None)
        node.driver_internal_info = driver_internal_info
        node.save()

    def _set_raid_config_job_failure(self, node):
        driver_internal_info = node.driver_internal_info
        driver_internal_info['raid_config_job_failure'] = True
        node.driver_internal_info = driver_internal_info
        node.save()

    def _clear_raid_config_job_failure(self, node):
        driver_internal_info = node.driver_internal_info
        del driver_internal_info['raid_config_job_failure']
        node.driver_internal_info = driver_internal_info
        node.save()

    def _delete_cached_config_job_id(self, node, finished_config_job_ids=None):
        if finished_config_job_ids is None:
            finished_config_job_ids = []
        driver_internal_info = node.driver_internal_info
        unfinished_job_ids = [job_id for job_id
                              in driver_internal_info['raid_config_job_ids']
                              if job_id not in finished_config_job_ids]
        driver_internal_info['raid_config_job_ids'] = unfinished_job_ids
        node.driver_internal_info = driver_internal_info
        node.save()

    def _set_clean_failed(self, task, config_job):
        LOG.error("RAID configuration job failed for node %(node)s. "
                  "Failed config job: %(config_job_id)s. "
                  "Message: '%(message)s'.",
                  {'node': task.node.uuid, 'config_job_id': config_job.id,
                   'message': config_job.message})
        task.node.last_error = config_job.message
        task.process_event('fail')

    def _resume_cleaning(self, task):
        raid_common.update_raid_info(
            task.node, self.get_logical_disks(task))
        driver_internal_info = task.node.driver_internal_info
        driver_internal_info['cleaning_reboot'] = True
        task.node.driver_internal_info = driver_internal_info
        task.node.save()
        manager_utils.notify_conductor_resume_clean(task)
