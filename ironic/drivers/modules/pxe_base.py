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
Base PXE Interface Methods
"""

from futurist import periodics
from ironic_lib import metrics_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _("UUID (from Glance) of the deployment kernel. "
                       "Required."),
    'deploy_ramdisk': _("UUID (from Glance) of the ramdisk that is "
                        "mounted at boot time. Required."),
}
OPTIONAL_PROPERTIES = {
    'force_persistent_boot_device': _("Controls the persistency of boot order "
                                      "changes. 'Always' will make all "
                                      "changes persistent, 'Default' will "
                                      "make all but the final one upon "
                                      "instance deployment non-persistent, "
                                      "and 'Never' will make no persistent "
                                      "changes at all. The old values 'True' "
                                      "and 'False' are still supported but "
                                      "deprecated in favor of the new ones."
                                      "Defaults to 'Default'. Optional."),
}
RESCUE_PROPERTIES = {
    'rescue_kernel': _('UUID (from Glance) of the rescue kernel. This value '
                       'is required for rescue mode.'),
    'rescue_ramdisk': _('UUID (from Glance) of the rescue ramdisk with agent '
                        'that is used at node rescue time. This value is '
                        'required for rescue mode.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(RESCUE_PROPERTIES)


class PXEBaseMixin(object):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    @METRICS.timer('PXEBaseMixin.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the PXE environment that was setup for booting
        the deploy or rescue ramdisk. It unlinks the deploy/rescue
        kernel/ramdisk in the node's directory in tftproot and removes it's PXE
        config.

        :param task: a task from TaskManager.
        :param mode: Label indicating a deploy or rescue operation
            was carried out on the node. Supported values are 'deploy' and
            'rescue'. Defaults to 'deploy', indicating deploy operation was
            carried out.
        :returns: None
        """
        node = task.node
        mode = deploy_utils.rescue_or_deploy_mode(node)
        try:
            images_info = pxe_utils.get_image_info(node, mode=mode)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get %(mode)s image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'mode': mode, 'node': node.uuid, 'err': e})
        else:
            pxe_utils.clean_up_pxe_env(task, images_info)

    @METRICS.timer('PXEBaseMixin.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        pxe_utils.parse_driver_info(task.node, mode='rescue')

    def _persistent_ramdisk_boot(self, node):
        """If the ramdisk should be configured as a persistent boot device."""
        value = node.driver_info.get('force_persistent_boot_device', 'Default')
        if value in {'Always', 'Default', 'Never'}:
            return value == 'Always'
        else:
            return strutils.bool_from_string(value, False)

    _RETRY_ALLOWED_STATES = {states.DEPLOYWAIT, states.CLEANWAIT,
                             states.RESCUEWAIT}

    @METRICS.timer('PXEBaseMixin._check_boot_timeouts')
    @periodics.periodic(spacing=CONF.pxe.boot_retry_check_interval,
                        enabled=bool(CONF.pxe.boot_retry_timeout))
    def _check_boot_timeouts(self, manager, context):
        """Periodically checks whether boot has timed out and retry it.

        :param manager: conductor manager.
        :param context: request context.
        """
        filters = {'provision_state_in': self._RETRY_ALLOWED_STATES,
                   'reserved': False,
                   'maintenance': False,
                   'provisioned_before': CONF.pxe.boot_retry_timeout}
        node_iter = manager.iter_nodes(filters=filters)

        for node_uuid, driver, conductor_group in node_iter:
            try:
                lock_purpose = 'checking PXE boot status'
                with task_manager.acquire(context, node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    self._check_boot_status(task)
            except (exception.NodeLocked, exception.NodeNotFound):
                continue

    def _check_boot_status(self, task):
        if not isinstance(task.driver.boot, PXEBaseMixin):
            return

        if not _should_retry_boot(task.node):
            return

        task.upgrade_lock(purpose='retrying PXE boot')

        # Retry critical checks after acquiring the exclusive lock.
        if (task.node.maintenance or task.node.provision_state
                not in self._RETRY_ALLOWED_STATES
                or not _should_retry_boot(task.node)):
            return

        LOG.info('Booting the ramdisk on node %(node)s is taking more than '
                 '%(timeout)d seconds, retrying boot',
                 {'node': task.node.uuid,
                  'timeout': CONF.pxe.boot_retry_timeout})

        manager_utils.node_power_action(task, states.POWER_OFF)
        # NOTE(dtantsur): retry even persistent boot setting in case it did not
        # work for some reason.
        persistent = self._persistent_ramdisk_boot(task.node)
        manager_utils.node_set_boot_device(task, boot_devices.PXE,
                                           persistent=persistent)
        manager_utils.node_power_action(task, states.POWER_ON)


def _should_retry_boot(node):
    # NOTE(dtantsur): this assumes IPA, do we need to make it generic?
    for field in ('agent_last_heartbeat', 'last_power_state_change'):
        if manager_utils.value_within_timeout(
                node.driver_internal_info.get(field),
                CONF.pxe.boot_retry_timeout):
            # Alive and heartbeating, probably busy with something long
            LOG.debug('Not retrying PXE boot for node %(node)s; its '
                      '%(event)s happened less than %(timeout)d seconds ago',
                      {'node': node.uuid, 'event': field,
                       'timeout': CONF.pxe.boot_retry_timeout})
            return False
    return True
