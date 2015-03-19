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
iLO Deploy Driver(s) and supporting methods.
"""

import tempfile

from oslo_config import cfg
from oslo_utils import excutils

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import image_service
from ironic.common import images
from ironic.common import keystone
from ironic.common import states
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

clean_opts = [
    cfg.IntOpt('clean_priority_erase_devices',
               help='Priority for erase devices clean step. If unset, '
                    'it defaults to 10. If set to 0, the step will be '
                    'disabled and will not run during cleaning.')
              ]

REQUIRED_PROPERTIES = {
    'ilo_deploy_iso': _("UUID (from Glance) of the deployment ISO. "
                    "Required.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES

CONF.import_opt('pxe_append_params', 'ironic.drivers.modules.iscsi_deploy',
                group='pxe')
CONF.import_opt('swift_ilo_container', 'ironic.drivers.modules.ilo.common',
                group='ilo')
CONF.register_opts(clean_opts, group='ilo')


def _get_boot_iso_object_name(node):
    """Returns the boot iso object name for a given node.

    :param node: the node for which object name is to be provided.
    """
    return "boot-%s" % node.uuid


def _get_boot_iso(task, root_uuid):
    """This method returns a boot ISO to boot the node.

    It chooses one of the three options in the order as below:
    1. Does nothing if 'ilo_boot_iso' is present in node's instance_info.
    2. Image deployed has a meta-property 'boot_iso' in Glance. This should
       refer to the UUID of the boot_iso which exists in Glance.
    3. Generates a boot ISO on the fly using kernel and ramdisk mentioned in
       the image deployed. It uploads the generated boot ISO to Swift.

    :param task: a TaskManager instance containing the node to act on.
    :param root_uuid: the uuid of the root partition.
    :returns: boot ISO URL. Should be either of below:
        * A Swift object - It should be of format 'swift:<object-name>'. It is
          assumed that the image object is present in
          CONF.ilo.swift_ilo_container;
        * A Glance image - It should be format 'glance://<glance-image-uuid>'
          or just <glance-image-uuid>;
        * An HTTP URL.
        On error finding the boot iso, it returns None.
    :raises: MissingParameterValue, if any of the required parameters are
        missing in the node's driver_info or instance_info.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value in the node's driver_info or instance_info.
    :raises: SwiftOperationError, if operation with Swift fails.
    :raises: ImageCreationFailed, if creation of boot ISO failed.
    :raises: exception.ImageRefValidationFailed if ilo_boot_iso is not
        HTTP(S) URL.
    """
    LOG.debug("Trying to get a boot ISO to boot the baremetal node")

    # Option 1 - Check if user has provided ilo_boot_iso in node's
    # instance_info
    if task.node.instance_info.get('ilo_boot_iso'):
        LOG.debug("Using ilo_boot_iso provided in node's instance_info")
        boot_iso = task.node.instance_info['ilo_boot_iso']
        if not service_utils.is_glance_image(boot_iso):
            try:
                image_service.HttpImageService().validate_href(boot_iso)
            except exception.ImageRefValidationFailed:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Virtual media deploy accepts only Glance "
                                  "images or HTTP(S) URLs as "
                                  "instance_info['ilo_boot_iso']. Either %s "
                                  "is not a valid HTTP(S) URL or is "
                                  "not reachable."), boot_iso)
        return task.node.instance_info['ilo_boot_iso']

    # Option 2 - Check if user has provided a boot_iso in Glance. If boot_iso
    # is a supported non-glance href execution will proceed to option 3.
    deploy_info = _parse_deploy_info(task.node)

    image_href = deploy_info['image_source']
    image_properties = (
        images.get_image_properties(task.context,
            image_href, ['boot_iso', 'kernel_id', 'ramdisk_id']))

    boot_iso_uuid = image_properties.get('boot_iso')
    kernel_href = (task.node.instance_info.get('kernel') or
                   image_properties.get('kernel_id'))
    ramdisk_href = (task.node.instance_info.get('ramdisk') or
                    image_properties.get('ramdisk_id'))

    if boot_iso_uuid:
        LOG.debug("Found boot_iso %s in Glance", boot_iso_uuid)
        return boot_iso_uuid

    if not kernel_href or not ramdisk_href:
        LOG.error(_LE("Unable to find kernel or ramdisk for "
                      "image %(image)s to generate boot ISO for %(node)s"),
                  {'image': image_href, 'node': task.node.uuid})
        return

    # NOTE(rameshg87): Functionality to share the boot ISOs created for
    # similar instances (instances with same deployed image) is
    # not implemented as of now. Creation/Deletion of such a shared boot ISO
    # will require synchronisation across conductor nodes for the shared boot
    # ISO.  Such a synchronisation mechanism doesn't exist in ironic as of now.

    # Option 3 - Create boot_iso from kernel/ramdisk, upload to Swift
    # and provide its name.
    deploy_iso_uuid = deploy_info['ilo_deploy_iso']
    boot_mode = driver_utils.get_node_capability(task.node, 'boot_mode')
    boot_iso_object_name = _get_boot_iso_object_name(task.node)
    kernel_params = CONF.pxe.pxe_append_params
    container = CONF.ilo.swift_ilo_container

    with tempfile.NamedTemporaryFile() as fileobj:
        boot_iso_tmp_file = fileobj.name
        images.create_boot_iso(task.context, boot_iso_tmp_file,
                               kernel_href, ramdisk_href,
                               deploy_iso_uuid, root_uuid,
                               kernel_params, boot_mode)
        swift_api = swift.SwiftAPI()
        swift_api.create_object(container, boot_iso_object_name,
                                boot_iso_tmp_file)

    LOG.debug("Created boot_iso %s in Swift", boot_iso_object_name)

    return 'swift:%s' % boot_iso_object_name


def _clean_up_boot_iso_for_instance(node):
    """Deletes the boot ISO if it was created in Swift for the instance.

    :param node: an ironic node object.
    """
    ilo_boot_iso = node.instance_info.get('ilo_boot_iso')
    if not (ilo_boot_iso and ilo_boot_iso.startswith('swift')):
        return
    swift_api = swift.SwiftAPI()
    container = CONF.ilo.swift_ilo_container
    boot_iso_object_name = _get_boot_iso_object_name(node)
    try:
        swift_api.delete_object(container, boot_iso_object_name)
    except exception.SwiftOperationError as e:
        LOG.exception(_LE("Failed to clean up boot ISO for %(node)s."
                          "Error: %(error)s."),
                      {'node': node.uuid, 'error': e})


def _parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the driver_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    """
    info = node.driver_info
    d_info = {}
    d_info['ilo_deploy_iso'] = info.get('ilo_deploy_iso')

    error_msg = _("Error validating iLO virtual media deploy. Some parameters"
                  " were missing in node's driver_info")
    deploy_utils.check_for_missing_params(d_info, error_msg)

    return d_info


def _parse_deploy_info(node):
    """Gets the instance and driver specific Node deployment info.

    This method validates whether the 'instance_info' and 'driver_info'
    property of the supplied node contains the required information for
    this driver to deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the instance_info and driver_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    info = {}
    info.update(iscsi_deploy.parse_instance_info(node))
    info.update(_parse_driver_info(node))
    return info


def _reboot_into(task, iso, ramdisk_options):
    """Reboots the node into a given boot ISO.

    This method attaches the given bootable ISO as virtual media, prepares the
    arguments for ramdisk in virtual media floppy, and then reboots the node.

    :param task: a TaskManager instance containing the node to act on.
    :param iso: a bootable ISO image href to attach to. Should be either
        of below:
        * A Swift object - It should be of format 'swift:<object-name>'.
          It is assumed that the image object is present in
          CONF.ilo.swift_ilo_container;
        * A Glance image - It should be format 'glance://<glance-image-uuid>'
          or just <glance-image-uuid>;
        * An HTTP URL.
    :param ramdisk_options: the options to be passed to the ramdisk in virtual
        media floppy.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    ilo_common.setup_vmedia_for_boot(task, iso, ramdisk_options)
    manager_utils.node_set_boot_device(task, boot_devices.CDROM)
    manager_utils.node_power_action(task, states.REBOOT)


def _prepare_agent_vmedia_boot(task):
    """prepare for vmedia boot."""

    deploy_ramdisk_opts = agent.build_agent_options(task.node)
    deploy_iso = task.node.driver_info['ilo_deploy_iso']
    _reboot_into(task, deploy_iso, deploy_ramdisk_opts)


class IloVirtualMediaIscsiDeploy(base.DeployInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the deployment information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue, if some information is invalid.
        :raises: MissingParameterValue if 'kernel_id' and 'ramdisk_id' are
            missing in the Glance image or 'kernel' and 'ramdisk' not provided
            in instance_info for non-Glance image.
        """
        iscsi_deploy.validate(task)

        d_info = _parse_deploy_info(task.node)

        if task.node.driver_internal_info.get('is_whole_disk_image'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        iscsi_deploy.validate_image_properties(task.context, d_info, props)
        driver_utils.validate_boot_mode_capability(task.node)
        driver_utils.validate_boot_option_capability(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Start deployment of the task's node.

        Fetches the instance image, prepares the options for the deployment
        ramdisk, sets the node to boot from virtual media cdrom, and reboots
        the given node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        :raises: InstanceDeployFailure, if image size if greater than root
            partition.
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IloOperationError, if some operation on iLO fails.
        """
        node = task.node
        manager_utils.node_power_action(task, states.POWER_OFF)

        iscsi_deploy.cache_instance_image(task.context, node)
        iscsi_deploy.check_image_size(task)

        deploy_ramdisk_opts = iscsi_deploy.build_deploy_ramdisk_options(node)
        agent_opts = agent.build_agent_options(node)
        deploy_ramdisk_opts.update(agent_opts)
        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        deploy_ramdisk_opts['BOOTIF'] = deploy_nic_mac
        deploy_iso = node.driver_info['ilo_deploy_iso']

        _reboot_into(task, deploy_iso, deploy_ramdisk_opts)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: IloOperationError, if some operation on iLO failed.
        """
        ilo_common.update_boot_mode(task)

    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks instance image and triggers image cache cleanup.

        :param task: a TaskManager instance containing the node to act on.
        """
        _clean_up_boot_iso_for_instance(task.node)
        iscsi_deploy.destroy_images(task.node.uuid)

    def take_over(self, task):
        pass


class IloVirtualMediaAgentDeploy(base.DeployInterface):
    """Interface for deploy-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance
        :raises: MissingParameterValue if some parameters are missing.
        """
        _parse_driver_info(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Prepares the options for the agent ramdisk and sets the node to boot
        from virtual media cdrom.

        :param task: a TaskManager instance.
        :returns: states.DEPLOYWAIT
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IloOperationError, if some operation on iLO fails.
        """
        _prepare_agent_vmedia_boot(task)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: states.DELETED
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        node = task.node
        node.instance_info = agent.build_instance_info_for_deploy(task)
        node.save()
        ilo_common.update_boot_mode(task)

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        Ejects the attached virtual media from the iLO and also removes
        the floppy image from Swift, if it exists.

        :param task: a TaskManager instance.
        """
        ilo_common.cleanup_vmedia_boot(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        :param task: a TaskManager instance.
        """
        pass

    def get_clean_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node
        :returns: A list of clean step dictionaries
        """
        steps = deploy_utils.agent_get_clean_steps(task)
        if CONF.ilo.clean_priority_erase_devices:
            for step in steps:
                if (step.get('step') == 'erase_devices' and
                        step.get('interface') == 'deploy'):
                    # Override with operator set priority
                    step['priority'] = CONF.ilo.clean_priority_erase_devices

        return steps

    def execute_clean_step(self, task, step):
        """Execute a clean step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :returns: states.CLEANING to signify the step will be completed async
        """
        return deploy_utils.agent_execute_clean_step(task, step)

    def prepare_cleaning(self, task):
        """Boot into the agent to prepare for cleaning."""
        # Create cleaning ports if necessary
        provider = dhcp_factory.DHCPFactory().provider

        # If we have left over ports from a previous cleaning, remove them
        if getattr(provider, 'delete_cleaning_ports', None):
            provider.delete_cleaning_ports(task)

        if getattr(provider, 'create_cleaning_ports', None):
            provider.create_cleaning_ports(task)

        _prepare_agent_vmedia_boot(task)
        # Tell the conductor we are waiting for the agent to boot.
        return states.CLEANING

    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning."""
        manager_utils.node_power_action(task, states.POWER_OFF)
        # If we created cleaning ports, delete them
        provider = dhcp_factory.DHCPFactory().provider
        if getattr(provider, 'delete_cleaning_ports', None):
            provider.delete_cleaning_ports(task)


class IloPXEDeploy(pxe.PXEDeploy):

    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        If the node's 'capabilities' property includes a boot_mode, that
        boot mode will be applied for the node. Otherwise, the existing
        boot mode of the node is used in the node's 'capabilities' property.

        PXEDeploys' prepare method is then called, to prepare the deploy
        environment for the node

        :param task: a TaskManager instance containing the node to act on.
        """
        ilo_common.update_boot_mode(task)
        super(IloPXEDeploy, self).prepare(task)

    def deploy(self, task):
        """Start deployment of the task's node.

        This method sets the boot device to 'NETWORK' and then calls
        PXEDeploy's deploy method to deploy on the given node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        """
        manager_utils.node_set_boot_device(task, boot_devices.PXE)
        return super(IloPXEDeploy, self).deploy(task)


class IloConsoleInterface(ipmitool.IPMIShellinaboxConsole):
    """A ConsoleInterface that uses ipmitool and shellinabox."""

    def get_properties(self):
        d = ilo_common.REQUIRED_PROPERTIES.copy()
        d.update(ilo_common.CONSOLE_PROPERTIES)
        return d

    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue when a required parameter is missing

        """
        node = task.node
        driver_info = ilo_common.parse_driver_info(node)
        if 'console_port' not in driver_info:
            raise exception.MissingParameterValue(_(
                "Missing 'console_port' parameter in node's driver_info."))

        ilo_common.update_ipmi_properties(task)
        super(IloConsoleInterface, self).validate(task)


class IloPXEVendorPassthru(pxe.VendorPassthru):

    @base.passthru(['POST'])
    def pass_deploy_info(self, task, **kwargs):
        manager_utils.node_set_boot_device(task, boot_devices.PXE, True)
        super(IloPXEVendorPassthru, self).pass_deploy_info(task, **kwargs)


class VendorPassthru(agent_base_vendor.BaseAgentVendor):
    """Vendor-specific interfaces for iLO deploy drivers."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        Checks if a valid vendor passthru method was passed and validates
        the parameters for the vendor passthru method.

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containing the vendor passthru method's
            parameters.
        :raises: MissingParameterValue, if some required parameters were not
            passed.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if method == 'pass_deploy_info':
            iscsi_deploy.get_deploy_info(task.node, **kwargs)

    def _configure_vmedia_boot(self, task, root_uuid):
        """Configure vmedia boot for the node."""
        node = task.node
        boot_iso = _get_boot_iso(task, root_uuid)
        if not boot_iso:
            LOG.error(_LE("Cannot get boot ISO for node %s"), node.uuid)
            return

        ilo_common.setup_vmedia_for_boot(task, boot_iso)
        manager_utils.node_set_boot_device(task, boot_devices.CDROM)

        i_info = node.instance_info
        if not i_info.get('ilo_boot_iso'):
            i_info['ilo_boot_iso'] = boot_iso
            node.instance_info = i_info

    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def pass_deploy_info(self, task, **kwargs):
        """Continues the iSCSI deployment from where ramdisk left off.

        This method continues the iSCSI deployment from the conductor node
        and writes the deploy image to the bare metal's disk.  After that,
        it does the following depending on boot_option for deploy:
        - If the boot_option requested for this deploy is 'local', then it
          sets the node to boot from disk (ramdisk installs the boot loader
          present within the image to the bare metal's disk).
        - If the boot_option requested is 'netboot' or no boot_option is
          requested, it finds/creates the boot ISO to boot the instance
          image, attaches the boot ISO to the bare metal and then sets
          the node to boot from CDROM.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: kwargs containing parameters for iSCSI deployment.
        :raises: InvalidState
        """
        node = task.node
        task.process_event('resume')

        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        ilo_common.cleanup_vmedia_boot(task)
        uuid_dict_returned = iscsi_deploy.continue_deploy(task, **kwargs)
        root_uuid_or_disk_id = uuid_dict_returned.get(
            'root uuid', uuid_dict_returned.get('disk identifier'))

        # TODO(rameshg87): It's not correct to return here as it will leave
        # the node in DEPLOYING state. This will be fixed in bug 1405519.
        if not root_uuid_or_disk_id:
            return

        try:
            # For iscsi_ilo driver, we boot from disk everytime if the image
            # deployed is a whole disk image.
            if iscsi_deploy.get_boot_option(node) == "local" or iwdi:
                manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                                   persistent=True)
            else:
                self._configure_vmedia_boot(task, root_uuid_or_disk_id)

            deploy_utils.notify_deploy_complete(kwargs.get('address'))

            LOG.info(_LI('Deployment to node %s done'), node.uuid)
            task.process_event('done')
        except Exception as e:
            LOG.error(_LE('Deploy failed for instance %(instance)s. '
                          'Error: %(error)s'),
                      {'instance': node.instance_uuid, 'error': e})
            msg = _('Failed to continue iSCSI deployment.')
            deploy_utils.set_failed_state(task, msg)

    @task_manager.require_exclusive_lock
    def continue_deploy(self, task, **kwargs):
        """Method invoked when deployed with the IPA ramdisk.

        This method is invoked during a heartbeat from an agent when
        the node is in wait-call-back state. This deploys the image on
        the node and then configures the node to boot according to the
        desired boot option (netboot or localboot).

        :param task: a TaskManager object containing the node.
        :param kwargs: the kwargs passed from the heartbeat method.
        :raises: InstanceDeployFailure, if it encounters some error during
            the deploy.
        """
        task.process_event('resume')
        node = task.node
        LOG.debug('Continuing the deployment on node %s', node.uuid)

        ilo_common.cleanup_vmedia_boot(task)

        uuid_dict_returned = iscsi_deploy.do_agent_iscsi_deploy(task,
                                                                self._client)
        root_uuid = uuid_dict_returned.get('root uuid')

        if iscsi_deploy.get_boot_option(node) == "local":
            efi_system_part_uuid = uuid_dict_returned.get(
                'efi system partition uuid')
            self.configure_local_boot(
                task, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid)
        else:
            # Agent vendorpassthru are made without auth token.
            # We require auth_token to talk to glance while building boot iso.
            task.context.auth_token = keystone.get_admin_auth_token()
            self._configure_vmedia_boot(task, root_uuid)

        self.reboot_and_finish_deploy(task)
