# Copyright 2018 FUJITSU LIMITED
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
Irmc RAID specific methods
"""
from futurist import periodics
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import raid as raid_common
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic import conf
from ironic.drivers import base
from ironic.drivers.modules.irmc import common as irmc_common

client = importutils.try_import('scciclient.irmc')

LOG = logging.getLogger(__name__)
CONF = conf.CONF

METRICS = metrics_utils.get_metrics_logger(__name__)

RAID_LEVELS = {
    '0': {
        'min_disks': 1,
        'max_disks': 1000,
        'factor': 0,
    },
    '1': {
        'min_disks': 2,
        'max_disks': 2,
        'factor': 1,
    },
    '5': {
        'min_disks': 3,
        'max_disks': 1000,
        'factor': 1,
    },
    '6': {
        'min_disks': 4,
        'max_disks': 1000,
        'factor': 2,
    },
    '10': {
        'min_disks': 4,
        'max_disks': 1000,
        'factor': 2,
    },
    '50': {
        'min_disks': 6,
        'max_disks': 1000,
        'factor': 2,
    }
}

RAID_COMPLETING = 'completing'
RAID_COMPLETED = 'completed'
RAID_FAILED = 'failed'


def _get_raid_adapter(node):
    """Get the RAID adapter info on a RAID controller.

    :param node: an ironic node object.
    :returns: RAID adapter dictionary, None otherwise.
    :raises: IRMCOperationError on an error from python-scciclient.
    """
    irmc_info = node.driver_info
    LOG.info('iRMC driver is gathering RAID adapter info for node %s',
             node.uuid)
    try:
        return client.elcm.get_raid_adapter(irmc_info)
    except client.elcm.ELCMProfileNotFound:
        reason = ('Cannot find any RAID profile in "%s"' % node.uuid)
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=reason)


def _get_fgi_status(report, node_uuid):
    """Get a dict FGI(Foreground initialization) status on a RAID controller.

    :param report: SCCI report information.
    :returns: FGI status on success, None if SCCIInvalidInputError and
              waiting status if SCCIRAIDNotReady.
    """
    try:
        return client.scci.get_raid_fgi_status(report)
    except client.scci.SCCIInvalidInputError:
        LOG.warning('ServerViewRAID not available in %(node)s',
                    {'node': node_uuid})
    except client.scci.SCCIRAIDNotReady:
        return RAID_COMPLETING


def _get_physical_disk(node):
    """Get physical disks info on a RAID controller.

    This method only support to create the RAID configuration
    on the RAIDAdapter 0.

    :param node: an ironic node object.
    :returns: dict of physical disks on RAID controller.
    """

    physical_disk_dict = {}
    raid_adapter = _get_raid_adapter(node)
    physical_disks = raid_adapter['Server']['HWConfigurationIrmc'][
        'Adapters']['RAIDAdapter'][0]['PhysicalDisks']

    if physical_disks:
        for disks in physical_disks['PhysicalDisk']:
            physical_disk_dict.update({disks['Slot']: disks['Type']})

    return physical_disk_dict


def _create_raid_adapter(node):
    """Create RAID adapter info on a RAID controller.

    :param node: an ironic node object.
    :raises: IRMCOperationError on an error from python-scciclient.
    """

    irmc_info = node.driver_info
    target_raid_config = node.target_raid_config

    try:
        return client.elcm.create_raid_configuration(irmc_info,
                                                     target_raid_config)
    except client.elcm.ELCMProfileNotFound as exc:
        LOG.error('iRMC driver failed with profile not found for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=exc)
    except client.scci.SCCIClientError as exc:
        LOG.error('iRMC driver failed to create raid adapter info for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=exc)


def _delete_raid_adapter(node):
    """Delete the RAID adapter info on a RAID controller.

    :param node: an ironic node object.
    :raises: IRMCOperationError if SCCI failed from python-scciclient.
    """

    irmc_info = node.driver_info

    try:
        client.elcm.delete_raid_configuration(irmc_info)
    except client.scci.SCCIClientError as exc:
        LOG.error('iRMC driver failed to delete RAID configuration '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=exc)


def _commit_raid_config(task):
    """Perform to commit RAID config into node."""

    node = task.node
    node_uuid = task.node.uuid
    raid_config = {'logical_disks': []}

    raid_adapter = _get_raid_adapter(node)

    raid_adapter_info = raid_adapter['Server']['HWConfigurationIrmc'][
        'Adapters']['RAIDAdapter'][0]
    controller = raid_adapter_info['@AdapterId']
    raid_config['logical_disks'].append({'controller': controller})

    logical_drives = raid_adapter_info['LogicalDrives']['LogicalDrive']
    for logical_drive in logical_drives:
        raid_config['logical_disks'].append({'irmc_raid_info': {
            'logical_drive_number': logical_drive['@Number'], 'raid_level':
                logical_drive['RaidLevel'], 'name': logical_drive['Name'],
            ' size': logical_drive['Size']}})
    for physical_drive in \
            raid_adapter_info['PhysicalDisks']['PhysicalDisk']:
        raid_config['logical_disks'].append({'physical_drives': {
            'physical_drive': physical_drive}})
    node.raid_config = raid_config

    raid_common.update_raid_info(node, node.raid_config)
    LOG.info('RAID config is created successfully on node %s',
             node_uuid)

    return states.CLEANWAIT


def _validate_logical_drive_capacity(disk, valid_disk_slots):
    physical_disks = valid_disk_slots['PhysicalDisk']
    size_gb = {}
    all_volume_list = []
    physical_disk_list = []

    for size in physical_disks:
        size_gb.update({size['@Number']: size['Size']['#text']})
        all_volume_list.append(size['Size']['#text'])

    factor = RAID_LEVELS[disk['raid_level']]['factor']

    if disk.get('physical_disks'):
        selected_disks = \
            [physical_disk for physical_disk in disk['physical_disks']]
        for volume in selected_disks:
            physical_disk_list.append(size_gb[volume])
        if disk['raid_level'] == '10':
            valid_capacity = \
                min(physical_disk_list) * (len(physical_disk_list) / 2)
        else:
            valid_capacity = \
                min(physical_disk_list) * (len(physical_disk_list) - factor)
    else:
        valid_capacity = \
            min(all_volume_list) * \
            ((RAID_LEVELS[disk['raid_level']]['min_disks']) - factor)

    if disk['size_gb'] > valid_capacity:
        raise exception.InvalidParameterValue(
            'Insufficient disk capacity with %s GB' % disk['size_gb'])

    if disk['size_gb'] == valid_capacity:
        disk['size_gb'] = 'MAX'


def _validate_physical_disks(node, logical_disks):
    """Validate physical disks on a RAID configuration.

    :param node: an ironic node object.
    :param logical_disks: RAID info to set RAID configuration
    :raises: IRMCOperationError on an error.
    """
    raid_adapter = _get_raid_adapter(node)
    physical_disk_dict = _get_physical_disk(node)
    if raid_adapter is None:
        reason = ('Cannot find any raid profile in "%s"' % node.uuid)
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=reason)
    if physical_disk_dict is None:
        reason = ('Cannot find any physical disks in "%s"' % node.uuid)
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=reason)
    valid_disks = raid_adapter['Server']['HWConfigurationIrmc'][
        'Adapters']['RAIDAdapter'][0]['PhysicalDisks']
    if valid_disks is None:
        reason = ('Cannot find any HDD over in the node "%s"' % node.uuid)
        raise exception.IRMCOperationError(operation='RAID config',
                                           error=reason)
    valid_disk_slots = [slot['Slot'] for slot in valid_disks['PhysicalDisk']]
    remain_valid_disk_slots = list(valid_disk_slots)
    number_of_valid_disks = len(valid_disk_slots)
    used_valid_disk_slots = []

    for disk in logical_disks:
        # Check raid_level value in the target_raid_config of node
        if disk.get('raid_level') not in RAID_LEVELS:
            reason = ('RAID level is not supported: "%s"'
                      % disk.get('raid_level'))
            raise exception.IRMCOperationError(operation='RAID config',
                                               error=reason)

        min_disk_value = RAID_LEVELS[disk['raid_level']]['min_disks']
        max_disk_value = RAID_LEVELS[disk['raid_level']]['max_disks']
        remain_valid_disks = number_of_valid_disks - min_disk_value
        number_of_valid_disks = number_of_valid_disks - min_disk_value

        if remain_valid_disks < 0:
            reason = ('Physical disks do not enough slots for raid "%s"'
                      % disk['raid_level'])
            raise exception.IRMCOperationError(operation='RAID config',
                                               error=reason)

        if 'physical_disks' in disk:
            type_of_disks = []
            number_of_physical_disks = len(disk['physical_disks'])
            # Check number of physical disks along with raid level
            if number_of_physical_disks > max_disk_value:
                reason = ("Too many disks requested for RAID level %(level)s, "
                          "maximum is %(max)s",
                          {'level': disk['raid_level'], 'max': max_disk_value})
                raise exception.InvalidParameterValue(err=reason)
            if number_of_physical_disks < min_disk_value:
                reason = ("Not enough disks requested for RAID level "
                          "%(level)s, minimum is %(min)s ",
                          {'level': disk['raid_level'], 'min': min_disk_value})
                raise exception.IRMCOperationError(operation='RAID config',
                                                   error=reason)
            # Check physical disks in valid disk slots
            for phys_disk in disk['physical_disks']:
                if int(phys_disk) not in valid_disk_slots:
                    reason = ("Incorrect physical disk %(disk)s, correct are "
                              "%(valid)s",
                              {'disk': phys_disk, 'valid': valid_disk_slots})
                    raise exception.IRMCOperationError(operation='RAID config',
                                                       error=reason)
                type_of_disks.append(physical_disk_dict[int(phys_disk)])
                if physical_disk_dict[int(phys_disk)] != type_of_disks[0]:
                    reason = ('Cannot create RAID configuration with '
                              'different hard drives type %s'
                              % physical_disk_dict[int(phys_disk)])
                    raise exception.IRMCOperationError(operation='RAID config',
                                                       error=reason)
                # Check physical disk values with used disk slots
                if int(phys_disk) in used_valid_disk_slots:
                    reason = ("Disk %s is already used in a RAID configuration"
                              % disk['raid_level'])
                    raise exception.IRMCOperationError(operation='RAID config',
                                                       error=reason)

                used_valid_disk_slots.append(int(phys_disk))
                remain_valid_disk_slots.remove(int(phys_disk))

        if disk['size_gb'] != 'MAX':
            # Validate size_gb value input
            _validate_logical_drive_capacity(disk, valid_disks)


class IRMCRAID(base.RAIDInterface):

    def get_properties(self):
        """Return the properties of the interface."""
        return irmc_common.COMMON_PROPERTIES

    @METRICS.timer('IRMCRAID.create_configuration')
    @base.clean_step(priority=0, argsinfo={
        'create_root_volume': {
            'description': ('This specifies whether to create the root volume.'
                            'Defaults to `True`.'
                            ),
            'required': False
        },
        'create_nonroot_volumes': {
            'description': ('This specifies whether to create the non-root '
                            'volumes. '
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
        :returns: states.CLEANWAIT if RAID configuration is in progress
            asynchronously.
        :raises: MissingParameterValue, if node.target_raid_config is missing
            or empty.
        :raises: IRMCOperationError on an error from scciclient
        """

        node = task.node

        if not node.target_raid_config:
            raise exception.MissingParameterValue(
                'Missing the target_raid_config in node %s' % node.uuid)

        target_raid_config = node.target_raid_config.copy()

        logical_disks = target_raid_config['logical_disks']
        for log_disk in logical_disks:
            if log_disk.get('raid_level'):
                log_disk['raid_level'] = str(
                    log_disk['raid_level']).replace('+', '')

        # Validate physical disks on Fujitsu BM Server
        _validate_physical_disks(node, logical_disks)

        # Executing raid configuration on Fujitsu BM Server
        _create_raid_adapter(node)

        return _commit_raid_config(task)

    @METRICS.timer('IRMCRAID.delete_configuration')
    @base.clean_step(priority=0)
    def delete_configuration(self, task):
        """Delete the RAID configuration.

        :param task: a TaskManager instance containing the node to act on.
        :returns: states.CLEANWAIT if deletion is in progress
            asynchronously or None if it is complete.
        """
        node = task.node
        node_uuid = task.node.uuid

        # Default delete everything raid configuration in BM Server
        _delete_raid_adapter(node)
        node.raid_config = {}
        node.save()
        LOG.info('RAID config is deleted successfully on node %(node_id)s.'
                 'RAID config will clear and return (cfg)s value',
                 {'node_id': node_uuid, 'cfg': node.raid_config})

    @METRICS.timer('IRMCRAID._query_raid_config_fgi_status')
    @periodics.periodic(
        spacing=CONF.irmc.query_raid_config_fgi_status_interval)
    def _query_raid_config_fgi_status(self, manager, context):
        """Periodic tasks to check the progress of running RAID config."""

        filters = {'reserved': False, 'provision_state': states.CLEANWAIT,
                   'maintenance': False}
        fields = ['raid_config']
        node_list = manager.iter_nodes(fields=fields, filters=filters)
        for (node_uuid, driver, conductor_group, raid_config) in node_list:
            try:
                # NOTE(TheJulia): Evaluate based upon presence of raid
                # configuration before triggering a task, as opposed to after
                # so we don't create excess node task objects with related
                # DB queries.
                if not raid_config or raid_config.get('fgi_status'):
                    continue

                lock_purpose = 'checking async RAID configuration tasks'
                with task_manager.acquire(context, node_uuid,
                                          purpose=lock_purpose,
                                          shared=True) as task:
                    node = task.node
                    node_uuid = task.node.uuid
                    if not isinstance(task.driver.raid, IRMCRAID):
                        continue
                    if task.node.target_raid_config is None:
                        continue
                    task.upgrade_lock()
                    if node.provision_state != states.CLEANWAIT:
                        continue
                    # Avoid hitting clean_callback_timeout expiration
                    node.touch_provisioning()

                    try:
                        report = irmc_common.get_irmc_report(node)
                    except client.scci.SCCIInvalidInputError:
                        raid_config.update({'fgi_status': RAID_FAILED})
                        raid_common.update_raid_info(node, raid_config)
                        self._set_clean_failed(task, RAID_FAILED)
                        continue
                    except client.scci.SCCIClientError:
                        raid_config.update({'fgi_status': RAID_FAILED})
                        raid_common.update_raid_info(node, raid_config)
                        self._set_clean_failed(task, RAID_FAILED)
                        continue

                    fgi_status_dict = _get_fgi_status(report, node_uuid)
                    # Note(trungnv): Allow to check until RAID mechanism to be
                    # completed with RAID information in report.
                    if fgi_status_dict == 'completing':
                        continue
                    if not fgi_status_dict:
                        raid_config.update({'fgi_status': RAID_FAILED})
                        raid_common.update_raid_info(node, raid_config)
                        self._set_clean_failed(task, fgi_status_dict)
                        continue
                    if all(fgi_status == 'Idle' for fgi_status in
                           fgi_status_dict.values()):
                        raid_config.update({'fgi_status': RAID_COMPLETED})
                        LOG.info('RAID configuration has completed on '
                                 'node %(node)s with fgi_status is %(fgi)s',
                                 {'node': node_uuid, 'fgi': RAID_COMPLETED})
                        self._resume_cleaning(task)

            except exception.NodeNotFound:
                LOG.info('During query_raid_config_job_status, node '
                         '%(node)s was not found raid_config and presumed '
                         'deleted by another process.', {'node': node_uuid})
            except exception.NodeLocked:
                LOG.info('During query_raid_config_job_status, node '
                         '%(node)s was already locked by another process. '
                         'Skip.', {'node': node_uuid})

    def _set_clean_failed(self, task, fgi_status_dict):
        LOG.error('RAID configuration task failed for node %(node)s. '
                  'with FGI status is: %(fgi)s. ',
                  {'node': task.node.uuid, 'fgi': fgi_status_dict})
        fgi_message = 'ServerViewRAID not available in Baremetal Server'
        task.node.last_error = fgi_message
        task.process_event('fail')

    def _resume_cleaning(self, task):
        raid_common.update_raid_info(task.node, task.node.raid_config)
        manager_utils.notify_conductor_resume_clean(task)
