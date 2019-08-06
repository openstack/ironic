# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
iLO Management Interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
import six
import six.moves.urllib.parse as urlparse

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import firmware_processor
from ironic.drivers.modules import ipmitool
from ironic.drivers import utils as driver_utils
from ironic.objects import volume_target

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

ilo_error = importutils.try_import('proliantutils.exception')

BOOT_DEVICE_MAPPING_TO_ILO = {
    boot_devices.PXE: 'NETWORK',
    boot_devices.DISK: 'HDD',
    boot_devices.CDROM: 'CDROM',
    boot_devices.ISCSIBOOT: 'ISCSI'
}
BOOT_DEVICE_ILO_TO_GENERIC = {
    v: k for k, v in BOOT_DEVICE_MAPPING_TO_ILO.items()}

MANAGEMENT_PROPERTIES = ilo_common.REQUIRED_PROPERTIES.copy()
MANAGEMENT_PROPERTIES.update(ilo_common.CLEAN_PROPERTIES)


def _execute_ilo_clean_step(node, step, *args, **kwargs):
    """Executes a particular clean step.

    :param node: an Ironic node object.
    :param step: a clean step to be executed.
    :param args: The args to be passed to the clean step.
    :param kwargs: The kwargs to be passed to the clean step.
    :raises: NodeCleaningFailure, on failure to execute step.
    """
    ilo_object = ilo_common.get_ilo_object(node)

    try:
        clean_step = getattr(ilo_object, step)
    except AttributeError:
        # The specified clean step is not present in the proliantutils
        # package. Raise exception to update the proliantutils package
        # to newer version.
        raise exception.NodeCleaningFailure(
            _("Clean step '%s' not found. 'proliantutils' package needs to be "
              "updated.") % step)
    try:
        clean_step(*args, **kwargs)
    except ilo_error.IloCommandNotSupportedError:
        # This clean step is not supported on Gen8 and below servers.
        # Log the failure and continue with cleaning.
        LOG.warning("'%(step)s' clean step is not supported on node "
                    "%(uuid)s. Skipping the clean step.",
                    {'step': step, 'uuid': node.uuid})
    except ilo_error.IloError as ilo_exception:
        raise exception.NodeCleaningFailure(_(
            "Clean step %(step)s failed "
            "on node %(node)s with error: %(err)s") %
            {'node': node.uuid, 'step': step, 'err': ilo_exception})


def _should_collect_logs(command):
    """Returns boolean to check whether logs need to collected or not."""
    return ((CONF.agent.deploy_logs_collect == 'on_failure'
             and command['command_status'] == 'FAILED')
            or CONF.agent.deploy_logs_collect == 'always')


class IloManagement(base.ManagementInterface):

    def get_properties(self):
        return MANAGEMENT_PROPERTIES

    @METRICS.timer('IloManagement.validate')
    def validate(self, task):
        """Check that 'driver_info' contains required ILO credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required iLO parameters
            are not valid.
        :raises: MissingParameterValue if a required parameter is missing.

        """
        ilo_common.parse_driver_info(task.node)

    @METRICS.timer('IloManagement.get_supported_boot_devices')
    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(BOOT_DEVICE_MAPPING_TO_ILO)

    @METRICS.timer('IloManagement.get_boot_device')
    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required iLO parameter is missing.
        :raises: IloOperationError on an error from IloClient library.
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of the supported devices listed in
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent:
                Whether the boot device will persist to all future boots or
                not, None if it is unknown.

        """
        ilo_object = ilo_common.get_ilo_object(task.node)
        persistent = False

        try:
            # Return one time boot device if set, else return
            # the persistent boot device
            next_boot = ilo_object.get_one_time_boot()
            if next_boot == 'Normal':
                # One time boot is not set. Check for persistent boot.
                persistent = True
                next_boot = ilo_object.get_persistent_boot_device()

        except ilo_error.IloError as ilo_exception:
            operation = _("Get boot device")
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

        boot_device = BOOT_DEVICE_ILO_TO_GENERIC.get(next_boot, None)

        if boot_device is None:
            persistent = None

        return {'boot_device': boot_device, 'persistent': persistent}

    @METRICS.timer('IloManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IloOperationError on an error from IloClient library.
        """

        try:
            boot_device = BOOT_DEVICE_MAPPING_TO_ILO[device]
        except KeyError:
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        try:
            ilo_object = ilo_common.get_ilo_object(task.node)

            if not persistent:
                ilo_object.set_one_time_boot(boot_device)
            else:
                ilo_object.update_persistent_boot([boot_device])

        except ilo_error.IloError as ilo_exception:
            operation = _("Setting %s as boot device") % device
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

        LOG.debug("Node %(uuid)s set to boot from %(device)s.",
                  {'uuid': task.node.uuid, 'device': device})

    @METRICS.timer('IloManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required ipmi parameters
                 are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: returns a dict of sensor data group by sensor type.

        """
        ilo_common.update_ipmi_properties(task)
        ipmi_management = ipmitool.IPMIManagement()
        return ipmi_management.get_sensors_data(task)

    @METRICS.timer('IloManagement.reset_ilo')
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_ilo)
    def reset_ilo(self, task):
        """Resets the iLO.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        return _execute_ilo_clean_step(task.node, 'reset_ilo')

    @METRICS.timer('IloManagement.reset_ilo_credential')
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_ilo_credential)
    def reset_ilo_credential(self, task):
        """Resets the iLO password.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        info = task.node.driver_info
        password = info.pop('ilo_change_password', None)

        if not password:
            LOG.info("Missing 'ilo_change_password' parameter in "
                     "driver_info. Clean step 'reset_ilo_credential' is "
                     "not performed on node %s.", task.node.uuid)
            return

        _execute_ilo_clean_step(task.node, 'reset_ilo_credential', password)

        info['ilo_password'] = password
        task.node.driver_info = info
        task.node.save()

    @METRICS.timer('IloManagement.reset_bios_to_default')
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_bios_to_default)
    def reset_bios_to_default(self, task):
        """Resets the BIOS settings to default values.

        Resets BIOS to default settings. This operation is currently supported
        only on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        return _execute_ilo_clean_step(task.node, 'reset_bios_to_default')

    @METRICS.timer('IloManagement.reset_secure_boot_keys_to_default')
    @base.clean_step(priority=CONF.ilo.
                     clean_priority_reset_secure_boot_keys_to_default)
    def reset_secure_boot_keys_to_default(self, task):
        """Reset secure boot keys to manufacturing defaults.

        Resets the secure boot keys to manufacturing defaults. This
        operation is supported only on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        return _execute_ilo_clean_step(task.node, 'reset_secure_boot_keys')

    @METRICS.timer('IloManagement.clear_secure_boot_keys')
    @base.clean_step(priority=CONF.ilo.clean_priority_clear_secure_boot_keys)
    def clear_secure_boot_keys(self, task):
        """Clear all secure boot keys.

        Clears all the secure boot keys. This operation is supported only
        on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        return _execute_ilo_clean_step(task.node, 'clear_secure_boot_keys')

    @METRICS.timer('IloManagement.activate_license')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'ilo_license_key': {
            'description': (
                'The HPE iLO Advanced license key to activate enterprise '
                'features.'
            ),
            'required': True
        }
    })
    def activate_license(self, task, **kwargs):
        """Activates iLO Advanced license.

        :param task: a TaskManager object.
        :raises: InvalidParameterValue, if any of the arguments are invalid.
        :raises: NodeCleaningFailure, on failure to execute clean step.
        """
        ilo_license_key = kwargs.get('ilo_license_key')
        node = task.node

        if not isinstance(ilo_license_key, six.string_types):
            msg = (_("Value of 'ilo_license_key' must be a string instead of "
                     "'%(value)s'. Step 'activate_license' is not executed "
                     "for %(node)s.")
                   % {'value': ilo_license_key, 'node': node.uuid})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        LOG.debug("Activating iLO license for node %(node)s ...",
                  {'node': node.uuid})
        _execute_ilo_clean_step(node, 'activate_license', ilo_license_key)
        LOG.info("iLO license activated for node %s.", node.uuid)

    @METRICS.timer('IloManagement.update_firmware')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'firmware_update_mode': {
            'description': (
                "This argument indicates the mode (or mechanism) of firmware "
                "update procedure. Supported value is 'ilo'."
            ),
            'required': True
        },
        'firmware_images': {
            'description': (
                "This argument represents the ordered list of JSON "
                "dictionaries of firmware images. Each firmware image "
                "dictionary consists of three mandatory fields, namely 'url', "
                "'checksum' and 'component'. These fields represent firmware "
                "image location URL, md5 checksum of image file and firmware "
                "component type respectively. The supported firmware URL "
                "schemes are 'file', 'http', 'https' and 'swift'. The "
                "supported values for firmware component are 'ilo', 'cpld', "
                "'power_pic', 'bios' and 'chassis'. The firmware images will "
                "be applied (in the order given) one by one on the baremetal "
                "server. For more information, see "
                "https://docs.openstack.org/ironic/latest/admin/drivers/ilo.html#initiating-firmware-update-as-manual-clean-step"  # noqa
            ),
            'required': True
        }
    })
    @firmware_processor.verify_firmware_update_args
    def update_firmware(self, task, **kwargs):
        """Updates the firmware.

        :param task: a TaskManager object.
        :raises: InvalidParameterValue if update firmware mode is not 'ilo'.
                 Even applicable for invalid input cases.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        node = task.node
        fw_location_objs_n_components = []
        firmware_images = kwargs['firmware_images']
        # Note(deray): Processing of firmware images happens here. As part
        # of processing checksum validation is also done for the firmware file.
        # Processing of firmware file essentially means downloading the file
        # on the conductor, validating the checksum of the downloaded content,
        # extracting the raw firmware file from its compact format, if it is,
        # and hosting the file on a web server or a swift store based on the
        # need of the baremetal server iLO firmware update method.
        try:
            for firmware_image_info in firmware_images:
                url, checksum, component = (
                    firmware_processor.get_and_validate_firmware_image_info(
                        firmware_image_info, kwargs['firmware_update_mode']))
                LOG.debug("Processing of firmware file: %(firmware_file)s on "
                          "node: %(node)s ... in progress",
                          {'firmware_file': url, 'node': node.uuid})

                fw_processor = firmware_processor.FirmwareProcessor(url)
                fw_location_obj = fw_processor.process_fw_on(node, checksum)
                fw_location_objs_n_components.append(
                    (fw_location_obj, component))

                LOG.debug("Processing of firmware file: %(firmware_file)s on "
                          "node: %(node)s ... done",
                          {'firmware_file': url, 'node': node.uuid})
        except exception.IronicException as ilo_exc:
            # delete all the files extracted so far from the extracted list
            # and re-raise the exception
            for fw_loc_obj_n_comp_tup in fw_location_objs_n_components:
                fw_loc_obj_n_comp_tup[0].remove()
            LOG.error("Processing of firmware image: %(firmware_image)s "
                      "on node: %(node)s ... failed",
                      {'firmware_image': firmware_image_info,
                       'node': node.uuid})
            raise exception.NodeCleaningFailure(node=node.uuid, reason=ilo_exc)

        # Updating of firmware images happen here.
        try:
            for fw_location_obj, component in fw_location_objs_n_components:
                fw_location = fw_location_obj.fw_image_location
                LOG.debug("Firmware update for %(firmware_file)s on "
                          "node: %(node)s ... in progress",
                          {'firmware_file': fw_location, 'node': node.uuid})

                _execute_ilo_clean_step(
                    node, 'update_firmware', fw_location, component)

                LOG.debug("Firmware update for %(firmware_file)s on "
                          "node: %(node)s ... done",
                          {'firmware_file': fw_location, 'node': node.uuid})
        except exception.NodeCleaningFailure:
            with excutils.save_and_reraise_exception():
                LOG.error("Firmware update for %(firmware_file)s on "
                          "node: %(node)s failed.",
                          {'firmware_file': fw_location, 'node': node.uuid})
        finally:
            for fw_loc_obj_n_comp_tup in fw_location_objs_n_components:
                fw_loc_obj_n_comp_tup[0].remove()

        LOG.info("All Firmware update operations completed successfully "
                 "for node: %s.", node.uuid)

    @METRICS.timer('IloManagement.update_firmware_sum')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'url': {
            'description': (
                "The image location for SPP (Service Pack for Proliant) ISO."
            ),
            'required': True
        },
        'checksum': {
            'description': (
                "The md5 checksum of the SPP image file."
            ),
            'required': True
        },
        'components': {
            'description': (
                "The list of firmware component filenames. If not specified, "
                "SUM updates all the firmware components."
            ),
            'required': False}
    })
    def update_firmware_sum(self, task, **kwargs):
        """Updates the firmware using Smart Update Manager (SUM).

        :param task: a TaskManager object.
        :raises: NodeCleaningFailure, on failure to execute step.
        """
        node = task.node
        # The arguments are validated and sent to the ProliantHardwareManager
        # to perform SUM based firmware update clean step.
        firmware_processor.get_and_validate_firmware_image_info(kwargs,
                                                                'sum')

        url = kwargs['url']
        if urlparse.urlparse(url).scheme == 'swift':
            url = firmware_processor.get_swift_url(urlparse.urlparse(url))
            node.clean_step['args']['url'] = url

        # Insert SPP ISO into virtual media CDROM
        ilo_common.attach_vmedia(node, 'CDROM', url)

        step = node.clean_step
        return deploy_utils.agent_execute_clean_step(task, step)

    @staticmethod
    @agent_base_vendor.post_clean_step_hook(
        interface='management', step='update_firmware_sum')
    def _update_firmware_sum_final(task, command):
        """Clean step hook after SUM based firmware update operation.

        This method is invoked as a post clean step hook by the Ironic
        conductor once firmware update operaion is completed. The clean logs
        are collected and stored according to the configured storage backend
        when the node is configured to collect the logs.

        :param task: a TaskManager instance.
        :param command: A command result structure of the SUM based firmware
            update operation returned from agent ramdisk on query of the
            status of command(s).
        """
        if not _should_collect_logs(command):
            return

        node = task.node
        try:
            driver_utils.store_ramdisk_logs(
                node,
                command['command_result']['clean_result']['Log Data'],
                label='update_firmware_sum')
        except exception.SwiftOperationError as e:
            LOG.error('Failed to store the logs from the node %(node)s '
                      'for "update_firmware_sum" clean step in Swift. '
                      'Error: %(error)s',
                      {'node': node.uuid, 'error': e})
        except EnvironmentError as e:
            LOG.exception('Failed to store the logs from the node %(node)s '
                          'for "update_firmware_sum" clean step due to a '
                          'file-system related error. Error: %(error)s',
                          {'node': node.uuid, 'error': e})
        except Exception as e:
            LOG.exception('Unknown error when storing logs from the node '
                          '%(node)s for "update_firmware_sum" clean step. '
                          'Error: %(error)s',
                          {'node': node.uuid, 'error': e})

    @METRICS.timer('IloManagement.set_iscsi_boot_target')
    def set_iscsi_boot_target(self, task):
        """Set iSCSI details of the system in UEFI boot mode.

        The initiator is set with the target details like
        IQN, LUN, IP, Port etc.
        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IloCommandNotSupportedInBiosError if system in BIOS boot mode.
        :raises: IloError on an error from iLO.
        """
        # Getting target info
        node = task.node
        macs = [port['address'] for port in task.ports]
        boot_volume = node.driver_internal_info.get('boot_from_volume')
        volume = volume_target.VolumeTarget.get_by_uuid(task.context,
                                                        boot_volume)
        properties = volume.properties
        username = properties.get('auth_username')
        password = properties.get('auth_password')
        try:
            portal = properties['target_portal']
            iqn = properties['target_iqn']
            lun = properties['target_lun']
            host, port = portal.split(':')
        except KeyError as e:
            raise exception.MissingParameterValue(
                _('Failed to get iSCSI target info for node '
                  '%(node)s. Error: %(error)s') % {'node': task.node.uuid,
                                                   'error': e})
        ilo_object = ilo_common.get_ilo_object(task.node)
        try:
            auth_method = 'CHAP' if username else None
            ilo_object.set_iscsi_info(
                iqn, lun, host, port, auth_method=auth_method,
                username=username, password=password, macs=macs)
        except ilo_error.IloCommandNotSupportedInBiosError as ilo_exception:
            operation = (_("Setting of target IQN %(target_iqn)s for node "
                           "%(node)s")
                         % {'target_iqn': iqn, 'node': node.uuid})
            raise exception.IloOperationNotSupported(operation=operation,
                                                     error=ilo_exception)
        except ilo_error.IloError as ilo_exception:
            operation = (_("Setting of target IQN %(target_iqn)s for node "
                           "%(node)s")
                         % {'target_iqn': iqn, 'node': node.uuid})
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

    @METRICS.timer('IloManagement.clear_iscsi_boot_target')
    def clear_iscsi_boot_target(self, task):
        """Unset iSCSI details of the system in UEFI boot mode.

        :param task: a task from TaskManager.
        :raises: IloCommandNotSupportedInBiosError if system in BIOS boot mode.
        :raises: IloError on an error from iLO.
        """
        ilo_object = ilo_common.get_ilo_object(task.node)
        try:
            macs = [port['address'] for port in task.ports]
            ilo_object.unset_iscsi_info(macs=macs)
        except ilo_error.IloCommandNotSupportedInBiosError as ilo_exception:
            operation = (_("Unsetting of iSCSI target for node %(node)s")
                         % {'node': task.node.uuid})
            raise exception.IloOperationNotSupported(operation=operation,
                                                     error=ilo_exception)
        except ilo_error.IloError as ilo_exception:
            operation = (_("Unsetting of iSCSI target for node %(node)s")
                         % {'node': task.node.uuid})
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

    @METRICS.timer('IloManagement.inject_nmi')
    @task_manager.require_exclusive_lock
    def inject_nmi(self, task):
        """Inject NMI, Non Maskable Interrupt.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param task: A TaskManager instance containing the node to act on.
        :raises: IloCommandNotSupportedError if system does not support
            NMI injection.
        :raises: IloError on an error from iLO.
        :returns: None
        """
        node = task.node
        ilo_object = ilo_common.get_ilo_object(node)
        try:
            operation = (_("Injecting NMI for node %(node)s")
                         % {'node': node.uuid})
            ilo_object.inject_nmi()
        except ilo_error.IloCommandNotSupportedError as ilo_exception:
            raise exception.IloOperationNotSupported(operation=operation,
                                                     error=ilo_exception)
        except ilo_error.IloError as ilo_exception:
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)


class Ilo5Management(IloManagement):

    def _set_driver_internal_value(self, task, value, *keys):
        driver_internal_info = task.node.driver_internal_info
        for key in keys:
            driver_internal_info[key] = value
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    def _pop_driver_internal_values(self, task, *keys):
        driver_internal_info = task.node.driver_internal_info
        for key in keys:
            driver_internal_info.pop(key, None)
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    def _set_clean_failed(self, task, msg):
        LOG.error("Out-of-band sanitize disk erase job failed for node "
                  "%(node)s. Message: '%(message)s'.",
                  {'node': task.node.uuid, 'message': msg})
        task.node.last_error = msg
        task.process_event('fail')

    def _wait_for_disk_erase_status(self, node):
        """Wait for out-of-band sanitize disk erase to be completed."""
        interval = CONF.ilo.oob_erase_devices_job_status_interval
        ilo_object = ilo_common.get_ilo_object(node)
        time_elps = [0]

        # This will loop indefinitely till disk erase is complete
        def _wait():
            if ilo_object.has_disk_erase_completed():
                raise loopingcall.LoopingCallDone()

            time_elps[0] += interval
            LOG.debug("%(tim)s secs elapsed while waiting for out-of-band "
                      "sanitize disk erase to complete for node %(node)s.",
                      {'tim': time_elps[0], 'node': node.uuid})

        # Start a timer and wait for the operation to complete.
        timer = loopingcall.FixedIntervalLoopingCall(_wait)
        timer.start(interval=interval).wait()
        return True

    def _validate_erase_pattern(self, erase_pattern, node):
        invalid = False
        if isinstance(erase_pattern, dict):
            for device_type, pattern in erase_pattern.items():
                if device_type == 'hdd' and pattern in (
                        'overwrite', 'crypto', 'zero'):
                        continue
                elif device_type == 'ssd' and pattern in (
                        'block', 'crypto', 'zero'):
                        continue
                else:
                    invalid = True
                    break
        else:
            invalid = True

        if invalid:
            msg = (_("Erase pattern '%(value)s' is invalid. Clean step "
                     "'erase_devices' is not executed for %(node)s. Supported "
                     "patterns are, for "
                     "'hdd': ('overwrite', 'crypto', 'zero') and for "
                     "'ssd': ('block', 'crypto', 'zero'). "
                     "Ex. {'hdd': 'overwrite', 'ssd': 'block'}")
                   % {'value': erase_pattern, 'node': node.uuid})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

    @METRICS.timer('Ilo5Management.erase_devices')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'erase_pattern': {
            'description': (
                'Dictionary of disk type and corresponding erase pattern '
                'to be used to perform specific out-of-band sanitize disk '
                'erase. Supported values are, '
                'for "hdd": ("overwrite", "crypto", "zero"), '
                'for "ssd": ("block", "crypto", "zero"). Default pattern is: '
                '{"hdd": "overwrite", "ssd": "block"}.'
            ),
            'required': False
        }
    })
    def erase_devices(self, task, **kwargs):
        """Erase all the drives on the node.

        This method performs out-of-band sanitize disk erase on all the
        supported physical drives in the node. This erase cannot be performed
        on logical drives.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue, if any of the arguments are invalid.
        :raises: IloError on an error from iLO.
        """
        erase_pattern = kwargs.get('erase_pattern',
                                   {'hdd': 'overwrite', 'ssd': 'block'})
        node = task.node
        self._validate_erase_pattern(erase_pattern, node)
        driver_internal_info = node.driver_internal_info
        LOG.debug("Calling out-of-band sanitize disk erase for node %(node)s",
                  {'node': node.uuid})
        try:
            ilo_object = ilo_common.get_ilo_object(node)
            disk_types = ilo_object.get_available_disk_types()
            LOG.info("Disk type detected are: %(disk_types)s. Sanitize disk "
                     "erase are now exercised for one after another disk type "
                     "for node %(node)s.",
                     {'disk_types': disk_types, 'node': node.uuid})

            if disk_types:
                # First disk-erase will execute for HDD's and after reboot only
                # try for SSD, since both share same redfish api and would be
                # overwritten.
                if not driver_internal_info.get(
                        'ilo_disk_erase_hdd_check') and ('HDD' in disk_types):
                    ilo_object.do_disk_erase('HDD', erase_pattern.get('hdd'))
                    self._set_driver_internal_value(
                        task, True, 'cleaning_reboot',
                        'ilo_disk_erase_hdd_check')
                    self._set_driver_internal_value(
                        task, False, 'skip_current_clean_step')
                    deploy_opts = deploy_utils.build_agent_options(task.node)
                    task.driver.boot.prepare_ramdisk(task, deploy_opts)
                    manager_utils.node_power_action(task, states.REBOOT)
                    return states.CLEANWAIT

                if not driver_internal_info.get(
                        'ilo_disk_erase_ssd_check') and ('SSD' in disk_types):
                    ilo_object.do_disk_erase('SSD', erase_pattern.get('ssd'))
                    self._set_driver_internal_value(
                        task, True, 'ilo_disk_erase_hdd_check',
                        'ilo_disk_erase_ssd_check', 'cleaning_reboot')
                    self._set_driver_internal_value(
                        task, False, 'skip_current_clean_step')
                    deploy_opts = deploy_utils.build_agent_options(task.node)
                    task.driver.boot.prepare_ramdisk(task, deploy_opts)
                    manager_utils.node_power_action(task, states.REBOOT)
                    return states.CLEANWAIT

                # It will wait until disk erase will complete
                if self._wait_for_disk_erase_status(task.node):
                    LOG.info("For node %(uuid)s erase_devices clean "
                             "step is done.", {'uuid': task.node.uuid})
                    self._pop_driver_internal_values(
                        task, 'ilo_disk_erase_hdd_check',
                        'ilo_disk_erase_ssd_check')
            else:
                LOG.info("No drive found to perform out-of-band sanitize "
                         "disk erase for node %(node)s", {'node': node.uuid})
        except ilo_error.IloError as ilo_exception:
            self._pop_driver_internal_values(task,
                                             'ilo_disk_erase_hdd_check',
                                             'ilo_disk_erase_ssd_check',
                                             'cleaning_reboot',
                                             'skip_current_clean_step')
            self._set_clean_failed(task, ilo_exception)
