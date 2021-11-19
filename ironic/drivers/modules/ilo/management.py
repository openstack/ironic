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

from urllib import parse as urlparse

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base
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

_ACTIVATE_ILO_LICENSE_ARGSINFO = {
    'ilo_license_key': {
        'description': (
            'The HPE iLO Advanced license key to activate enterprise '
            'features.'
        ),
        'required': True
    }
}

_RESET_ILO_CREDENTIALS_ARGSINFO = {
    'ilo_password': {
        'description': (
            'Password string for iLO user with administrative privileges '
            'being set in the driver_info property "ilo_username".'
        ),
        'required': True
    }
}

_SECURITY_PARAMETER_UPDATE_ARGSINFO = {
    'security_parameters': {
        'description': (
            "This argument represents the ordered list of JSON "
            "dictionaries of security parameters. Each security "
            "parameter consists of three fields, namely 'param', "
            "'ignore' and 'enable' from which 'param' field will be "
            "mandatory. These fields represent security parameter "
            "name, ignore flag and state of the security parameter. "
            "The supported security parameter names are "
            "'password_complexity', 'require_login_for_ilo_rbsu', "
            "'ipmi_over_lan', 'secure_boot', 'require_host_authentication'. "
            "The security parameters will be updated (in the order given) "
            "one by one on the baremetal server."
        ),
        'required': True
    }
}

_MINIMUM_PASSWORD_LENGTH_UPDATE_ARGSINFO = {
    'password_length': {
        'description': (
            "This argument represents the minimum password length that can "
            "be set for ilo. If not specified, default will be 8."
        ),
        'required': False
    },
    'ignore': {
        'description': (
            "This argument represents boolean parameter. If set 'True' "
            "the security parameters will be ignored by iLO while "
            "computing the overall iLO security status. If not specified, "
            "default will be 'False'."
        ),
        'required': False
    }
}

_Auth_Failure_Logging_Threshold_ARGSINFO = {
    'logging_threshold': {
        'description': (
            "This argument represents the authentication failure "
            "logging threshold that can be set for ilo. If not "
            "specified, default will be 1."
        ),
        'required': False
    },
    'ignore': {
        'description': (
            "This argument represents boolean parameter. If set 'True' "
            "the security parameters will be ignored by iLO while "
            "computing the overall iLO security status. If not specified, "
            "default will be 'False'."
        ),
        'required': False
    }
}

_FIRMWARE_UPDATE_ARGSINFO = {
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
}

_FIRMWARE_UPDATE_SUM_ARGSINFO = {
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
        'required': False
    }
}

_CLEAR_CA_CERTS_ARGSINFO = {
    'certificate_files': {
        'description': (
            "The list of files containing the certificates to be cleared. "
            "If empty list is specified, all the certificates on the ilo "
            "will be cleared, except the certificates in the file "
            "configured with configuration parameter 'webserver_verify_ca' "
            "are spared as they are required for booting the deploy image "
            "for some boot interfaces."
        ),
        'required': True
    }
}


def _execute_ilo_step(node, step, *args, **kwargs):
    """Executes a particular deploy or clean step.

    :param node: an Ironic node object.
    :param step: a step to be executed.
    :param args: The args to be passed to the step.
    :param kwargs: The kwargs to be passed to the step.
    :raises: NodeCleaningFailure, on failure to execute the clean step.
    :raises: InstanceDeployFailure, on failure to execute the deploy step.
    """
    ilo_object = ilo_common.get_ilo_object(node)

    try:
        step_method = getattr(ilo_object, step)
    except AttributeError:
        # The specified clean/deploy step is not present in the proliantutils
        # package. Raise exception to update the proliantutils package
        # to newer version.
        msg = (_("Step '%s' not found. 'proliantutils' package needs to be "
                 "updated.") % step)
        if node.clean_step:
            raise exception.NodeCleaningFailure(msg)
        raise exception.InstanceDeployFailure(msg)
    try:
        step_method(*args, **kwargs)
    except ilo_error.IloCommandNotSupportedError:
        # This step is not supported on Gen8 and below servers.
        # Log the failure and continue with cleaning or deployment.
        LOG.warning("'%(step)s' step is not supported on node "
                    "%(uuid)s. Skipping the step.",
                    {'step': step, 'uuid': node.uuid})
    except ilo_error.IloError as ilo_exception:
        msg = (_("Step %(step)s failed on node %(node)s with "
                 "error: %(err)s") %
               {'node': node.uuid, 'step': step, 'err': ilo_exception})
        if node.clean_step:
            raise exception.NodeCleaningFailure(msg)
        raise exception.InstanceDeployFailure(msg)


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
    @base.deploy_step(priority=0)
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_ilo)
    def reset_ilo(self, task):
        """Resets the iLO.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        node = task.node
        _execute_ilo_step(node, 'reset_ilo')

        # Reset iLO ejects virtual media
        # Re-create the environment for agent boot, if required
        task.driver.boot.clean_up_ramdisk(task)
        deploy_utils.prepare_agent_boot(task)

    @METRICS.timer('IloManagement.reset_ilo_credential')
    @base.deploy_step(priority=0, argsinfo=_RESET_ILO_CREDENTIALS_ARGSINFO)
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_ilo_credential)
    def reset_ilo_credential(self, task, change_password=None):
        """Resets the iLO password.

        :param task: a task from TaskManager.
        :param change_password: Value for password to update on iLO.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        info = task.node.driver_info
        password = change_password
        if not password:
            password = info.pop('ilo_change_password', None)

        if not password:
            LOG.info("Missing 'ilo_change_password' parameter in "
                     "driver_info. Step 'reset_ilo_credential' is "
                     "not performed on node %s.", task.node.uuid)
            return

        _execute_ilo_step(task.node, 'reset_ilo_credential', password)

        info['ilo_password'] = password
        task.node.driver_info = info
        task.node.save()

    @METRICS.timer('IloManagement.reset_bios_to_default')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=CONF.ilo.clean_priority_reset_bios_to_default)
    def reset_bios_to_default(self, task):
        """Resets the BIOS settings to default values.

        Resets BIOS to default settings. This operation is currently supported
        only on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        return _execute_ilo_step(task.node, 'reset_bios_to_default')

    @METRICS.timer('IloManagement.reset_secure_boot_keys_to_default')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=CONF.ilo.
                     clean_priority_reset_secure_boot_keys_to_default)
    def reset_secure_boot_keys_to_default(self, task):
        """Reset secure boot keys to manufacturing defaults.

        Resets the secure boot keys to manufacturing defaults. This
        operation is supported only on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        return _execute_ilo_step(task.node, 'reset_secure_boot_keys')

    @METRICS.timer('IloManagement.clear_secure_boot_keys')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=CONF.ilo.clean_priority_clear_secure_boot_keys)
    def clear_secure_boot_keys(self, task):
        """Clear all secure boot keys.

        Clears all the secure boot keys. This operation is supported only
        on HP Proliant Gen9 and above servers.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        return _execute_ilo_step(task.node, 'clear_secure_boot_keys')

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
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        """
        ilo_license_key = kwargs.get('ilo_license_key')
        node = task.node

        if not isinstance(ilo_license_key, str):
            msg = (_("Value of 'ilo_license_key' must be a string instead of "
                     "'%(value)s'. Step 'activate_license' is not executed "
                     "for %(node)s.")
                   % {'value': ilo_license_key, 'node': node.uuid})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        LOG.debug("Activating iLO license for node %(node)s ...",
                  {'node': node.uuid})
        _execute_ilo_step(node, 'activate_license', ilo_license_key)
        LOG.info("iLO license activated for node %s.", node.uuid)

    @METRICS.timer('IloManagement.security_parameters_update')
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_SECURITY_PARAMETER_UPDATE_ARGSINFO)
    def security_parameters_update(self, task, **kwargs):
        """Updates the security parameters.

        :param task: a TaskManager object.
        """
        node = task.node
        security_parameter = kwargs.get('security_parameters')
        try:
            for sec_param_info in security_parameter:
                param, enable, ignore = (
                    ilo_common.validate_security_parameter_values(
                        sec_param_info))
                LOG.debug("Updating %(param)s security parameter for node "
                          "%(node)s ..", {'param': param, 'node': node.uuid})
                _execute_ilo_step(node, ('update_' + param), enable, ignore)
                LOG.info("%(param)s security parameter for node %(node)s is "
                         "updated", {'param': param, 'node': node.uuid})
        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                exception.NodeCleaningFailure):
            LOG.error("%(param)s security parameter updation for "
                      "node: %(node)s failed.",
                      {'param': param, 'node': node.uuid})
            raise

    @METRICS.timer('IloManagement.update_minimum_password_length')
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_MINIMUM_PASSWORD_LENGTH_UPDATE_ARGSINFO)
    def update_minimum_password_length(self, task, **kwargs):
        """Updates the Minimum Password Length security parameter.

        :param task: a TaskManager object.
        """
        node = task.node
        passwd_length = kwargs.get('password_length')
        ignore = kwargs.get('ignore', False)
        ignore = strutils.bool_from_string(ignore, default=False)

        LOG.debug("Updating minimum password length security parameter "
                  "for node %(node)s ..", {'node': node.uuid})
        _execute_ilo_step(node, 'update_minimum_password_length',
                          passwd_length, ignore)
        LOG.info("Minimum password length security parameter for node "
                 "%(node)s is updated", {'node': node.uuid})

    @METRICS.timer('IloManagement.update_auth_failure_logging_threshold')
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_Auth_Failure_Logging_Threshold_ARGSINFO)
    def update_auth_failure_logging_threshold(self, task, **kwargs):
        """Updates the Auth Failure Logging Threshold security parameter.

        :param task: a TaskManager object.
        """
        node = task.node
        logging_threshold = kwargs.get('logging_threshold')
        ignore = kwargs.get('ignore', False)
        ignore = strutils.bool_from_string(ignore, default=False)

        LOG.debug("Updating authentication failure logging threshold "
                  "security parameter for node %(node)s ..",
                  {'node': node.uuid})
        _execute_ilo_step(node, 'update_authentication_failure_logging',
                          logging_threshold, ignore)
        LOG.info("Authentication failure logging threshold security "
                 "parameter for node %(node)s is updated",
                 {'node': node.uuid})

    @METRICS.timer('IloManagement.update_firmware')
    @base.deploy_step(priority=0, argsinfo=_FIRMWARE_UPDATE_ARGSINFO)
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_FIRMWARE_UPDATE_ARGSINFO)
    @firmware_processor.verify_firmware_update_args
    def update_firmware(self, task, **kwargs):
        """Updates the firmware.

        :param task: a TaskManager object.
        :raises: InvalidParameterValue if update firmware mode is not 'ilo'.
                 Even applicable for invalid input cases.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
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
            if node.clean_step:
                raise exception.NodeCleaningFailure(node=node.uuid,
                                                    reason=ilo_exc)
            raise exception.InstanceDeployFailure(reason=ilo_exc)

        # Updating of firmware images happen here.
        try:
            for fw_location_obj, component in fw_location_objs_n_components:
                fw_location = fw_location_obj.fw_image_location
                LOG.debug("Firmware update for %(firmware_file)s on "
                          "node: %(node)s ... in progress",
                          {'firmware_file': fw_location, 'node': node.uuid})

                _execute_ilo_step(
                    node, 'update_firmware', fw_location, component)

                LOG.debug("Firmware update for %(firmware_file)s on "
                          "node: %(node)s ... done",
                          {'firmware_file': fw_location, 'node': node.uuid})
        except (exception.NodeCleaningFailure,
                exception.InstanceDeployFailure):
            with excutils.save_and_reraise_exception():
                LOG.error("Firmware update for %(firmware_file)s on "
                          "node: %(node)s failed.",
                          {'firmware_file': fw_location, 'node': node.uuid})
        finally:
            for fw_loc_obj_n_comp_tup in fw_location_objs_n_components:
                fw_loc_obj_n_comp_tup[0].remove()

        # Firmware might have ejected the virtual media, if it was used.
        # Re-create the environment for agent boot, if required
        task.driver.boot.clean_up_ramdisk(task)
        deploy_utils.prepare_agent_boot(task)

        LOG.info("All Firmware update operations completed successfully "
                 "for node: %s.", node.uuid)

    @METRICS.timer('IloManagement.update_firmware_sum')
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_FIRMWARE_UPDATE_SUM_ARGSINFO)
    def update_firmware_sum(self, task, **kwargs):
        """Clean step to update the firmware using Smart Update Manager (SUM)

        :param task: a TaskManager object.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :returns: states.CLEANWAIT to signify the step will be completed async
        """
        return self._do_update_firmware_sum(task, **kwargs)

    @METRICS.timer('IloManagement.update_firmware_sum')
    @base.deploy_step(priority=0, argsinfo=_FIRMWARE_UPDATE_SUM_ARGSINFO)
    def flash_firmware_sum(self, task, **kwargs):
        """Deploy step to Update the firmware using Smart Update Manager (SUM).

        :param task: a TaskManager object.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        :returns: states.DEPLOYWAIT to signify the step will be completed
            async
        """
        return self._do_update_firmware_sum(task, **kwargs)

    def _do_update_firmware_sum(self, task, **kwargs):
        """Update the firmware using Smart Update Manager (SUM).

        :param task: a TaskManager object.
        :raises: NodeCleaningFailure or InstanceDeployFailure, on failure to
            execute of clean or deploy step respectively.
        :returns: states.CLEANWAIT or states.DEPLOYWAIT to signify the step
            will be completed async for clean or deploy step respectively.
        """
        node = task.node
        if node.provision_state == states.DEPLOYING:
            step = node.deploy_step
            step_type = 'deploy'
        else:
            step = node.clean_step
            step_type = 'clean'

        # The arguments are validated and sent to the ProliantHardwareManager
        # to perform SUM based firmware update clean step.
        firmware_processor.get_and_validate_firmware_image_info(kwargs,
                                                                'sum')

        url = kwargs['url']
        if urlparse.urlparse(url).scheme == 'swift':
            url = firmware_processor.get_swift_url(urlparse.urlparse(url))
            step['args']['url'] = url

        # Insert SPP ISO into virtual media CDROM
        ilo_common.attach_vmedia(node, 'CDROM', url)

        return agent_base.execute_step(task, step, step_type)

    @staticmethod
    @agent_base.post_deploy_step_hook(
        interface='management', step='flash_firmware_sum')
    @agent_base.post_clean_step_hook(
        interface='management', step='update_firmware_sum')
    def _update_firmware_sum_final(task, command):
        """Deploy/Clean step hook after SUM based firmware update operation.

        This method is invoked as a post deploy/clean step hook by the Ironic
        conductor once firmware update operaion is completed. The deploy/clean
        logs are collected and stored according to the configured storage
        backend when the node is configured to collect the logs.

        :param task: a TaskManager instance.
        :param command: A command result structure of the SUM based firmware
            update operation returned from agent ramdisk on query of the
            status of command(s).
        """
        if not _should_collect_logs(command):
            return

        if task.node.provision_state == states.DEPLOYWAIT:
            log_data = command['command_result']['deploy_result']['Log Data']
            label = command['command_result']['deploy_step']['step']
        else:
            log_data = command['command_result']['clean_result']['Log Data']
            label = command['command_result']['clean_step']['step']

        node = task.node
        try:
            driver_utils.store_ramdisk_logs(node, log_data, label=label)
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

    def get_supported_boot_modes(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :raises: IloOperationError if any exception happens in proliantutils
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        node = task.node
        ilo_object = ilo_common.get_ilo_object(node)
        try:
            modes = ilo_object.get_supported_boot_mode()
            if modes == ilo_common.SUPPORTED_BOOT_MODE_LEGACY_BIOS_ONLY:
                return [boot_modes.LEGACY_BIOS]
            elif modes == ilo_common.SUPPORTED_BOOT_MODE_UEFI_ONLY:
                return [boot_modes.UEFI]
            elif modes == ilo_common.SUPPORTED_BOOT_MODE_LEGACY_BIOS_AND_UEFI:
                return [boot_modes.UEFI, boot_modes.LEGACY_BIOS]
        except ilo_error.IloError as ilo_exception:
            operation = _("Get supported boot modes")
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

    @task_manager.require_exclusive_lock
    def set_boot_mode(self, task, mode):
        """Set the boot mode for a node.

        Set the boot mode to use on next reboot of the node.

        :param task: A task from TaskManager.
        :param mode: The boot mode, one of
                     :mod:`ironic.common.boot_modes`.
        :raises: InvalidParameterValue if an invalid boot mode is
                 specified.
        :raises: IloOperationError if setting boot mode failed.
        """
        if mode not in self.get_supported_boot_modes(task):
            raise exception.InvalidParameterValue(_(
                "The given boot mode '%s' is not supported.") % mode)
        ilo_common.set_boot_mode(task.node, mode)

    def get_boot_mode(self, task):
        """Get the current boot mode for a node.

        Provides the current boot mode of the node.

        :param task: A task from TaskManager.
        :raises: IloOperationError on an error from IloClient library.
        :returns: The boot mode, one of :mod:`ironic.common.boot_mode` or
                  None if it is unknown.
        """
        return ilo_common.get_current_boot_mode(task.node)

    def get_secure_boot_state(self, task):
        """Get the current secure boot state for the node.

        :param task: A task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: IloOperationError on an error from IloClient library.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the hardware
        :returns: Boolean
        """
        try:
            return ilo_common.get_secure_boot_mode(task)
        except ilo_error.IloOperationNotSupported:
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='get_secure_boot_state')

    def set_secure_boot_state(self, task, state):
        """Set the current secure boot state for the node.

        :param task: A task from TaskManager.
        :param state: A new state as a boolean.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: IloOperationError on an error from IloClient library.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the hardware
        """
        try:
            ilo_common.set_secure_boot_mode(task, state)
        except ilo_error.IloOperationNotSupported:
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='set_secure_boot_state')


class Ilo5Management(IloManagement):

    def _set_driver_internal_value(self, task, value, *keys):
        for key in keys:
            task.node.set_driver_internal_info(key, value)
        task.node.save()

    def _pop_driver_internal_values(self, task, *keys):
        for key in keys:
            task.node.del_driver_internal_info(key)
        task.node.save()

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
                if not node.driver_internal_info.get(
                        'ilo_disk_erase_hdd_check') and ('HDD' in disk_types):
                    ilo_object.do_disk_erase('HDD', erase_pattern.get('hdd'))
                    self._set_driver_internal_value(
                        task, True, 'cleaning_reboot',
                        'ilo_disk_erase_hdd_check')
                    self._set_driver_internal_value(
                        task, False, 'skip_current_clean_step')
                    return deploy_utils.reboot_to_finish_step(task)

                if not node.driver_internal_info.get(
                        'ilo_disk_erase_ssd_check') and ('SSD' in disk_types):
                    ilo_object.do_disk_erase('SSD', erase_pattern.get('ssd'))
                    self._set_driver_internal_value(
                        task, True, 'ilo_disk_erase_hdd_check',
                        'ilo_disk_erase_ssd_check', 'cleaning_reboot')
                    self._set_driver_internal_value(
                        task, False, 'skip_current_clean_step')
                    return deploy_utils.reboot_to_finish_step(task)

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
            log_msg = ("Out-of-band sanitize disk erase job failed for node "
                       "%(node)s. Message: '%(message)s'." %
                       {'node': task.node.uuid, 'message': ilo_exception})
            self._pop_driver_internal_values(task,
                                             'ilo_disk_erase_hdd_check',
                                             'ilo_disk_erase_ssd_check',
                                             'cleaning_reboot',
                                             'skip_current_clean_step')
            manager_utils.cleaning_error_handler(task, log_msg,
                                                 errmsg=ilo_exception)

    @base.clean_step(priority=0, abortable=False)
    def one_button_secure_erase(self, task):
        """Erase the whole system securely.

        The One-button secure erase process resets iLO and deletes all licenses
        stored there, resets BIOS settings, and deletes all Active Health
        System (AHS) and warranty data stored on the system. It also erases
        supported non-volatile storage data and deletes any deployment setting
        profiles.

        :param task: a TaskManager instance.
        :raises: IloError on an error from iLO.
        """
        node = task.node
        LOG.info("Calling one button secure erase for node %(node)s",
                 {'node': node.uuid})
        try:
            ilo_object = ilo_common.get_ilo_object(node)
            ilo_object.do_one_button_secure_erase()
            manager_utils.node_power_action(task, states.REBOOT)
            node.maintenance = True
            node.maintenance_reason = (
                "One Button Secure erase clean step has begun, it will wipe "
                "data from drives and any non-volatile/persistent storage, "
                "reset iLO and delete all licenses stored there, reset BIOS "
                "settings, delete  Active Health System (AHS) and warranty "
                "data stored in the system and delete any deployment settings "
                "profiles.")
            node.save()
            return states.CLEANWAIT
        except ilo_error.IloError as ilo_exception:
            log_msg = ("One button secure erase job failed for node "
                       "%(node)s. Message: '%(message)s'." %
                       {'node': task.node.uuid, 'message': ilo_exception})
            manager_utils.cleaning_error_handler(task, log_msg,
                                                 errmsg=ilo_exception)

    @base.clean_step(priority=0, argsinfo=_CLEAR_CA_CERTS_ARGSINFO)
    def clear_ca_certificates(self, task, certificate_files):
        """Clears the certificates provided in the list of files to iLO.

        :param task: a task from TaskManager.
        :param certificate_files: a list of cerificate files.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        node = task.node

        if node.driver_internal_info.get('clear_ca_certs_flag'):
            # NOTE(vmud213): Clear the flag and do nothing as this flow
            # is part of the reboot required by the clean step that is
            # already executed.
            node.del_driver_internal_info('clear_ca_certs_flag')
            node.save()
            return

        try:
            ilo_common.clear_certificates(task, certificate_files)
        except (exception.IloOperationNotSupported,
                exception.IloOperationError) as ir_exception:
            msg = (_("Step 'clear_ca_certificates' failed on node %(node)s "
                     "with error: %(err)s") %
                   {'node': node.uuid, 'err': ir_exception})
            if node.clean_step:
                raise exception.NodeCleaningFailure(msg)
            raise exception.InstanceDeployFailure(msg)

        node.set_driver_internal_info('clear_ca_certs_flag', True)
        node.save()

        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        manager_utils.node_power_action(task, states.REBOOT)

        # set_async_step_flags calls node.save()
        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            skip_current_step=False)

        return deploy_utils.get_async_step_return_state(task.node)
