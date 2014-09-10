# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011-2014 OpenStack Foundation
# Copyright 2014 Red Hat, Inc.
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
A scheduler host manager which subclasses the new location in the Nova tree.
This is a placeholder so that end users can gradually upgrade to use the
new settings. TODO: remove in the K release
"""

from ironic.common import i18n
from nova.openstack.common import log as logging
from nova.scheduler import ironic_host_manager

LOG = logging.getLogger(__name__)


class IronicHostManager(ironic_host_manager.IronicHostManager):
    """Ironic HostManager class that subclasses the Nova in-tree version."""

    def _do_deprecation_warning(self):
        LOG.warning(i18n._LW(
            'This class (ironic.nova.scheduler.ironic_host_manager.'
            'IronicHostManager) is deprecated and has moved into the Nova '
            'tree. Please set scheduler_host_manager = '
            'nova.scheduler.ironic_host_manager.IronicHostManager.'))

    def __init__(self):
        super(IronicHostManager, self).__init__()
        self._do_deprecation_warning()
