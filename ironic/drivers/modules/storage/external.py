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

from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import pxe_utils as common_pxe_utils
from ironic.drivers import base

CONF = cfg.CONF

LOG = log.getLogger(__name__)


class ExternalStorage(base.StorageInterface):
    """Externally driven Storage Interface."""

    def validate(self, task):
        def _fail_validation(task, reason,
                             exception=exception.InvalidParameterValue):
            msg = (_("Failed to validate external storage interface for node "
                     "%(node)s. %(reason)s") %
                   {'node': task.node.uuid, 'reason': reason})
            LOG.error(msg)
            raise exception(msg)

        if (not self.should_write_image(task)
            and not common_pxe_utils.is_ipxe_enabled(task)):
                msg = _("The [pxe]/ipxe_enabled option must "
                        "be set to True to support network "
                        "booting to an iSCSI volume or the boot "
                        "interface must be set to ``ipxe``.")
                _fail_validation(task, msg)

    def get_properties(self):
        return {}

    def attach_volumes(self, task):
        pass

    def detach_volumes(self, task):
        pass

    def should_write_image(self, task):
        """Determines if deploy should perform the image write-out.

        This enables the user to define a volume and Ironic understand
        that the image may already exist and we may be booting to that volume.

        :param task: The task object.
        :returns: True if the deployment write-out process should be
                  executed.
        """
        instance_info = task.node.instance_info
        if 'image_source' not in instance_info:
            for volume in task.volume_targets:
                if volume['boot_index'] == 0:
                    return False
        return True
