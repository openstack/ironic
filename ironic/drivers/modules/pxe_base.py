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

from ironic_lib import metrics_utils
from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import pxe_utils
from ironic.drivers.modules import deploy_utils
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

    ipxe_enabled = False

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
            images_info = pxe_utils.get_image_info(
                node, mode=mode, ipxe_enabled=self.ipxe_enabled)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get %(mode)s image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'mode': mode, 'node': node.uuid, 'err': e})
        else:
            pxe_utils.clean_up_pxe_env(
                task, images_info, ipxe_enabled=self.ipxe_enabled)

    @METRICS.timer('PXEBaseMixin.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        pxe_utils.parse_driver_info(task.node, mode='rescue')
