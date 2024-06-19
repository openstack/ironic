# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2021 Dell Inc. or its subsidiaries.
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

"""
DRAC management interface
"""

import json

from ironic_lib import metrics_utils
import jsonschema
from jsonschema import exceptions as json_schema_exc
from oslo_log import log as logging
import sushy

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import molds
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import management as redfish_management
from ironic.drivers.modules.redfish import utils as redfish_utils


LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

# This dictionary is used to map boot device names between two (2) name
# spaces. The name spaces are:
#
#     1) ironic boot devices
#     2) iDRAC boot sources
#
# Mapping can be performed in both directions.
#
# The keys are ironic boot device types. Each value is a list of strings
# that appear in the identifiers of iDRAC boot sources.
#
# The iDRAC represents boot sources with class DCIM_BootSourceSetting
# [1]. Each instance of that class contains a unique identifier, which
# is called an instance identifier, InstanceID,
#
# An InstanceID contains the Fully Qualified Device Descriptor (FQDD) of
# the physical device that hosts the boot source [2].
#
# [1] "Dell EMC BIOS and Boot Management Profile", Version 4.0.0, July
#     10, 2017, Section 7.2 "Boot Management", pp. 44-47 --
#     http://en.community.dell.com/techcenter/extras/m/white_papers/20444495/download
# [2] "Lifecycle Controller Version 3.15.15.15 User's Guide", Dell EMC,
#     2017, Table 13, "Easy-to-use Names of System Components", pp. 71-74 --
#     http://topics-cdn.dell.com/pdf/idrac9-lifecycle-controller-v3.15.15.15_users-guide2_en-us.pdf
_BOOT_DEVICES_MAP = {
    boot_devices.DISK: ['AHCI', 'Disk', 'RAID'],
    boot_devices.PXE: ['NIC'],
    boot_devices.CDROM: ['Optical'],
}

_DRAC_BOOT_MODES = ['Bios', 'Uefi']

# BootMode constant
_NON_PERSISTENT_BOOT_MODE = 'OneTime'

# Clear job id's constant
_CLEAR_JOB_IDS = 'JID_CLEARALL'

# Clean steps constant
_CLEAR_JOBS_CLEAN_STEPS = ['clear_job_queue', 'known_good_state']

_CONF_MOLD_SCHEMA = {
    'type': 'object',
    'properties': {
        'oem': {
            'type': 'object',
            'properties': {
                'interface': {'const': 'idrac-redfish'},
                'data': {'type': 'object', 'minProperties': 1}
            },
            'required': ['interface', 'data']
        }

    },
    'required': ['oem'],
    'additionalProperties': False
}


def _is_boot_order_flexibly_programmable(persistent, bios_settings):
    return persistent and 'SetBootOrderFqdd1' in bios_settings


def _flexibly_program_boot_order(device, drac_boot_mode):
    if device == boot_devices.DISK:
        if drac_boot_mode == 'Bios':
            bios_settings = {'SetBootOrderFqdd1': 'HardDisk.List.1-1'}
        else:
            # 'Uefi'
            bios_settings = {
                'SetBootOrderFqdd1': '*.*.*',  # Disks, which are all else
                'SetBootOrderFqdd2': 'NIC.*.*',
                'SetBootOrderFqdd3': 'Optical.*.*',
                'SetBootOrderFqdd4': 'Floppy.*.*',
            }
    elif device == boot_devices.PXE:
        bios_settings = {'SetBootOrderFqdd1': 'NIC.*.*'}
    else:
        # boot_devices.CDROM
        bios_settings = {'SetBootOrderFqdd1': 'Optical.*.*'}

    return bios_settings


def _validate_conf_mold(data):
    """Validates iDRAC configuration mold JSON schema

    :param data: dictionary of configuration mold data
    :raises InvalidParameterValue: If configuration mold validation fails
    """
    try:
        jsonschema.validate(data, _CONF_MOLD_SCHEMA)
    except json_schema_exc.ValidationError as e:
        raise exception.InvalidParameterValue(
            _("Invalid configuration mold: %(error)s") % {'error': e})


class DracRedfishManagement(redfish_management.RedfishManagement):
    """iDRAC Redfish interface for management-related actions."""

    EXPORT_CONFIGURATION_ARGSINFO = {
        "export_configuration_location": {
            "description": "URL of location to save the configuration to.",
            "required": True,
        }
    }

    IMPORT_CONFIGURATION_ARGSINFO = {
        "import_configuration_location": {
            "description": "URL of location to fetch desired configuration "
                           "from.",
            "required": True,
        }
    }

    IMPORT_EXPORT_CONFIGURATION_ARGSINFO = {**EXPORT_CONFIGURATION_ARGSINFO,
                                            **IMPORT_CONFIGURATION_ARGSINFO}

    @base.deploy_step(priority=0, argsinfo=EXPORT_CONFIGURATION_ARGSINFO)
    @base.clean_step(priority=0, argsinfo=EXPORT_CONFIGURATION_ARGSINFO,
                     requires_ramdisk=False)
    def export_configuration(self, task, export_configuration_location):
        """(Deprecated) Export the configuration of the server.

        Exports the configuration of the server against which the step is run
        and stores it in specific format in indicated location.

        Uses Dell's Server Configuration Profile (SCP) from `sushy-oem-idrac`
        library to get ALL configuration for cloning.

        :param task: A task from TaskManager.
        :param export_configuration_location: URL of location to save the
            configuration to.

        :raises: MissingParameterValue if missing configuration name of a file
            to save the configuration to
        :raises: DracOperatationError when no managagers for Redfish system
            found or configuration export from SCP failed
        :raises: RedfishError when loading OEM extension failed
        """
        if not export_configuration_location:
            raise exception.MissingParameterValue(
                _('export_configuration_location missing'))

        system = redfish_utils.get_system(task.node)
        configuration = None

        if not system.managers:
            raise exception.DracOperationError(
                error=(_("No managers found for %(node)s") %
                       {'node': task.node.uuid}))

        configuration = drac_utils.execute_oem_manager_method(
            task, 'export system configuration',
            lambda m: m.export_system_configuration(
                include_destructive_fields=False))

        if configuration and configuration.status_code == 200:
            configuration = {"oem": {"interface": "idrac-redfish",
                                     "data": configuration.json()}}
            molds.save_configuration(task,
                                     export_configuration_location,
                                     configuration)
        else:
            raise exception.DracOperationError(
                error=(_("No configuration exported for node %(node)s") %
                       {'node': task.node.uuid}))

    @base.deploy_step(priority=0, argsinfo=IMPORT_CONFIGURATION_ARGSINFO)
    @base.clean_step(priority=0, argsinfo=IMPORT_CONFIGURATION_ARGSINFO,
                     requires_ramdisk=False)
    def import_configuration(self, task, import_configuration_location):
        """(Deprecated) Import and apply the configuration to the server.

        Gets pre-created configuration from storage by given location and
        imports that into given server. Uses Dell's Server Configuration
        Profile (SCP).

        :param task: A task from TaskManager.
        :param import_configuration_location: URL of location to fetch desired
            configuration from.

        :raises: MissingParameterValue if missing configuration name of a file
            to fetch the configuration from
        """
        if not import_configuration_location:
            raise exception.MissingParameterValue(
                _('import_configuration_location missing'))

        configuration = molds.get_configuration(task,
                                                import_configuration_location)
        if not configuration:
            raise exception.DracOperationError(
                error=(_("No configuration found for node %(node)s by name "
                         "%(configuration_name)s") %
                       {'node': task.node.uuid,
                        'configuration_name': import_configuration_location}))

        _validate_conf_mold(configuration)

        task_monitor = drac_utils.execute_oem_manager_method(
            task, 'import system configuration',
            lambda m: m.import_system_configuration(
                json.dumps(configuration["oem"]["data"])),)

        task.node.set_driver_internal_info('import_task_monitor_url',
                                           task_monitor.task_monitor_uri)

        deploy_utils.set_async_step_flags(
            task.node,
            reboot=True,
            skip_current_step=True,
            polling=True)
        return deploy_utils.reboot_to_finish_step(task)

    @base.clean_step(priority=0,
                     argsinfo=IMPORT_EXPORT_CONFIGURATION_ARGSINFO,
                     requires_ramdisk=False)
    @base.deploy_step(priority=0,
                      argsinfo=IMPORT_EXPORT_CONFIGURATION_ARGSINFO)
    def import_export_configuration(self, task, import_configuration_location,
                                    export_configuration_location):
        """Import and export configuration in one go.

        Gets pre-created configuration from storage by given name and
        imports that into given server. After that exports the configuration of
        the server against which the step is run and stores it in specific
        format in indicated storage as configured by Ironic.

        :param import_configuration_location: URL of location to fetch desired
            configuration from.
        :param export_configuration_location: URL of location to save the
            configuration to.
        """
        # Import is async operation, setting sub-step to store export config
        # and indicate that it's being executed as part of composite step
        task.node.set_driver_internal_info('export_configuration_location',
                                           export_configuration_location)
        task.node.save()

        return self.import_configuration(task, import_configuration_location)
        # Export executed as part of Import async periodic task status check

    @METRICS.timer('DracRedfishManagement._query_import_configuration_status')
    @periodics.node_periodic(
        purpose='checking async import configuration task',
        spacing=CONF.drac.query_import_config_job_status_interval,
        filters={'reserved': False, 'maintenance': False},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: (
            n.driver_internal_info.get('import_task_monitor_url')
        ),
    )
    def _query_import_configuration_status(self, task, manager, context):
        """Period job to check import configuration task."""
        self._check_import_configuration_task(
            task, task.node.driver_internal_info.get(
                'import_task_monitor_url'))

    def _check_import_configuration_task(self, task, task_monitor_url):
        """Checks progress of running import configuration task"""

        node = task.node
        try:
            task_monitor = redfish_utils.get_task_monitor(
                node, task_monitor_url)
        except exception.RedfishError as e:
            error_msg = (_("Failed import configuration task: "
                           "%(task_monitor_url)s. Message: '%(message)s'. "
                           "Most likely this happened because could not find "
                           "the task anymore as it got deleted by iDRAC. "
                           "If not already, upgrade iDRAC firmware to "
                           "5.00.00.00 or later that preserves tasks for "
                           "longer or decrease "
                           "[drac]query_import_config_job_status_interval")
                         % {'task_monitor_url': task_monitor_url,
                            'message': e})
            log_msg = ("Import configuration task failed for node "
                       "%(node)s. %(error)s" % {'node': task.node.uuid,
                                                'error': error_msg})
            node.del_driver_internal_info('import_task_monitor_url')
            node.save()
            self._set_failed(task, log_msg, error_msg)
            return

        if not task_monitor.is_processing:
            import_task = task_monitor.get_task()

            task.upgrade_lock()
            node.del_driver_internal_info('import_task_monitor_url')

            succeeded = False
            if (import_task.task_state == sushy.TASK_STATE_COMPLETED
                and import_task.task_status in
                    [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):

                # Task could complete with errors (partial success)
                # iDRAC 5.00.00.00 has stopped reporting Critical messages
                # so checking also by message_id
                succeeded = not any(m.message for m in import_task.messages
                                    if (m.severity
                                        and m.severity != sushy.SEVERITY_OK)
                                    or (m.message_id and 'SYS055'
                                        in m.message_id))

            if succeeded:
                LOG.info('Configuration import %(task_monitor_url)s '
                         'successful for node %(node)s',
                         {'node': node.uuid,
                          'task_monitor_url': task_monitor_url})

                # If import executed as part of import_export_configuration
                export_configuration_location = node.driver_internal_info.get(
                    'export_configuration_location')
                if export_configuration_location:
                    # then do sync export configuration before finishing
                    self._cleanup_export_substep(node)
                    try:
                        self.export_configuration(
                            task, export_configuration_location)
                    except (sushy.exceptions.SushyError,
                            exception.IronicException) as e:
                        error_msg = (_("Failed export configuration. %(exc)s" %
                                       {'exc': e}))
                        log_msg = ("Export configuration failed for node "
                                   "%(node)s. %(error)s" %
                                   {'node': task.node.uuid,
                                    'error': error_msg})
                        self._set_failed(task, log_msg, error_msg)
                        return
                self._set_success(task)
            else:
                # Select all messages, skipping OEM messages that don't have
                # `message` field populated.
                messages = [m.message for m in import_task.messages
                            if m.message is not None
                            and ((m.severity
                                  and m.severity != sushy.SEVERITY_OK)
                                 or (m.message_id
                                     and 'SYS055' in m.message_id))]
                error_msg = (_("Failed import configuration task: "
                               "%(task_monitor_url)s. Message: '%(message)s'.")
                             % {'task_monitor_url': task_monitor_url,
                                'message': ', '.join(messages)})
                log_msg = ("Import configuration task failed for node "
                           "%(node)s. %(error)s" % {'node': task.node.uuid,
                                                    'error': error_msg})
                self._set_failed(task, log_msg, error_msg)
            node.save()
        else:
            LOG.debug('Import configuration %(task_monitor_url)s in progress '
                      'for node %(node)s',
                      {'node': node.uuid,
                       'task_monitor_url': task_monitor_url})

    def _set_success(self, task):
        if task.node.clean_step:
            manager_utils.notify_conductor_resume_clean(task)
        else:
            manager_utils.notify_conductor_resume_deploy(task)

    def _set_failed(self, task, log_msg, error_msg):
        if task.node.clean_step:
            manager_utils.cleaning_error_handler(task, log_msg, error_msg)
        else:
            manager_utils.deploying_error_handler(task, log_msg, error_msg)

    def _cleanup_export_substep(self, node):
        node.del_driver_internal_info('export_configuration_location')

    @METRICS.timer('DracRedfishManagement.clear_job_queue')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def clear_job_queue(self, task):
        """Clear iDRAC job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        try:
            drac_utils.execute_oem_manager_method(
                task, 'clear job queue',
                lambda m: m.job_service.delete_jobs(job_ids=['JID_CLEARALL']))
        except exception.RedfishError as exc:
            if "Oem/Dell/DellJobService is missing" in str(exc):
                LOG.warning('iDRAC on node %(node)s does not support '
                            'clearing Lifecycle Controller job queue '
                            'using the idrac-redfish driver. '
                            'If using iDRAC9, consider upgrading firmware.',
                            {'node': task.node.uuid})
            if task.node.provision_state != states.VERIFYING:
                raise

    @METRICS.timer('DracRedfishManagement.reset_idrac')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def reset_idrac(self, task):
        """Reset the iDRAC.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        try:
            drac_utils.execute_oem_manager_method(
                task, 'reset iDRAC', lambda m: m.reset_idrac())
            redfish_utils.wait_until_get_system_ready(task.node)
            LOG.info('Reset iDRAC for node %(node)s done',
                     {'node': task.node.uuid})
        except exception.RedfishError as exc:
            if "Oem/Dell/DelliDRACCardService is missing" in str(exc):
                LOG.warning('iDRAC on node %(node)s does not support '
                            'iDRAC reset using the idrac-redfish driver. '
                            'If using iDRAC9, consider upgrading firmware. ',
                            {'node': task.node.uuid})
            if task.node.provision_state != states.VERIFYING:
                raise

    @METRICS.timer('DracRedfishManagement.known_good_state')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def known_good_state(self, task):
        """Reset iDRAC to known good state.

        An iDRAC is reset to a known good state by resetting it and
        clearing its job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        self.reset_idrac(task)
        self.clear_job_queue(task)
        LOG.info('Reset iDRAC to known good state for node %(node)s',
                 {'node': task.node.uuid})
