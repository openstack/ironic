# coding=utf-8
#
# Copyright 2014 Red Hat, Inc.
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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
A driver which subclasses the new location in the Nova tree.
This is a placeholder so that end users can gradually upgrade to use the
new settings. TODO: remove in the K release
"""

from ironic.common import i18n
from nova.openstack.common import log as logging
from nova.virt.ironic import driver

LOG = logging.getLogger(__name__)


class IronicDriver(driver.IronicDriver):
    """Nova Ironic driver that subclasses the Nova in-tree version."""

    def _do_deprecation_warning(self):
        LOG.warning(i18n._LW(
            'This class (ironic.nova.virt.ironic.IronicDriver) is '
            'deprecated and has moved into the Nova tree. Please set '
            'compute_driver =  nova.virt.ironic.IronicDriver.'))

    def __init__(self, virtapi, read_only=False):
        super(IronicDriver, self).__init__(virtapi)
        self._do_deprecation_warning()
