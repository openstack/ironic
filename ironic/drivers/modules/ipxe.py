# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
iPXE Boot Interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import pxe_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import pxe
from ironic.drivers.modules import pxe_base
from ironic.drivers import utils as driver_utils
LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

COMMON_PROPERTIES = pxe_base.COMMON_PROPERTIES


class iPXEBoot(pxe_base.PXEBaseMixin, base.BootInterface):

    ipxe_enabled = True

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot', 'ipxe_boot']

    def __init__(self):
        pxe_utils.create_ipxe_boot_script()

    def _validate_common(self, task):
        node = task.node

        if not driver_utils.get_node_mac_addresses(task):
            raise exception.MissingParameterValue(
                _("Node %s does not have any port associated with it.")
                % node.uuid)

        if not CONF.deploy.http_url or not CONF.deploy.http_root:
            raise exception.MissingParameterValue(_(
                "iPXE boot is enabled but no HTTP URL or HTTP "
                "root was specified."))

        # Check the trusted_boot capabilities value.
        deploy_utils.validate_capabilities(node)
        if deploy_utils.is_trusted_boot_requested(node):
            # Check if 'boot_option' and boot mode is compatible with
            # trusted boot.
            # NOTE(TheJulia): So in theory (huge theory here, not put to
            # practice or tested), that one can define the kernel as tboot
            # and define the actual kernel and ramdisk as appended data.
            # Similar to how one can iPXE load the XEN hypervisor.
            # tboot mailing list seem to indicate pxe/ipxe support, or
            # more specifically avoiding breaking the scenarios of use,
            # but there is also no definitive documentation on the subject.
            LOG.warning('Trusted boot has been requested for %(node)s in '
                        'concert with iPXE. This is not a supported '
                        'configuration for an ironic deployment.',
                        {'node': node.uuid})
            pxe.validate_boot_parameters_for_trusted_boot(node)

        pxe_utils.parse_driver_info(node)

    @METRICS.timer('iPXEBoot.validate')
    def validate(self, task):
        """Validate the PXE-specific info for booting deploy/instance images.

        This method validates the PXE-specific info for booting the
        ramdisk and instance on the node.  If invalid, raises an
        exception; otherwise returns None.

        :param task: a task from TaskManager.
        :returns: None
        :raises: InvalidParameterValue, if some parameters are invalid.
        :raises: MissingParameterValue, if some required parameters are
            missing.
        """
        self._validate_common(task)

        # NOTE(TheJulia): If we're not writing an image, we can skip
        # the remainder of this method.
        if (not task.driver.storage.should_write_image(task)):
            return

        node = task.node
        d_info = deploy_utils.get_image_instance_info(node)
        if (node.driver_internal_info.get('is_whole_disk_image')
                or deploy_utils.get_boot_option(node) == 'local'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info, props)

    @METRICS.timer('iPXEBoot.validate_inspection')
    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        :param task: A TaskManager instance with the node being checked
        :raises: UnsupportedDriverExtension
        """
        try:
            self._validate_common(task)
        except exception.MissingParameterValue:
            # Fall back to non-managed in-band inspection
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='inspection')
