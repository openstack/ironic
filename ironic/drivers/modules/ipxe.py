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

from ironic.common import pxe_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import pxe_base


class iPXEBoot(pxe_base.PXEBaseMixin, base.BootInterface):

    ipxe_enabled = True

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot', 'ipxe_boot']

    def __init__(self):
        pxe_utils.create_ipxe_boot_script()
        pxe_utils.place_loaders_for_boot(CONF.deploy.http_root)
        # This is required to serve the iPXE binary via tftp
        pxe_utils.place_loaders_for_boot(CONF.pxe.tftp_root)
