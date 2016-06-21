# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools

import ironic.api
import ironic.api.app
import ironic.common.driver_factory
import ironic.common.exception
import ironic.common.glance_service.v2.image_service
import ironic.common.hash_ring
import ironic.common.image_service
import ironic.common.images
import ironic.common.keystone
import ironic.common.paths
import ironic.common.service
import ironic.common.swift
import ironic.common.utils
import ironic.dhcp.neutron
import ironic.drivers.modules.agent
import ironic.drivers.modules.agent_base_vendor
import ironic.drivers.modules.agent_client
import ironic.drivers.modules.amt.common
import ironic.drivers.modules.amt.power
import ironic.drivers.modules.deploy_utils
import ironic.drivers.modules.iboot
import ironic.drivers.modules.ilo.common
import ironic.drivers.modules.ilo.deploy
import ironic.drivers.modules.ilo.management
import ironic.drivers.modules.ilo.power
import ironic.drivers.modules.image_cache
import ironic.drivers.modules.inspector
import ironic.drivers.modules.ipminative
import ironic.drivers.modules.irmc.boot
import ironic.drivers.modules.irmc.common
import ironic.drivers.modules.iscsi_deploy
import ironic.drivers.modules.oneview.common
import ironic.drivers.modules.pxe
import ironic.drivers.modules.seamicro
import ironic.drivers.modules.snmp
import ironic.drivers.modules.ssh
import ironic.drivers.modules.virtualbox
import ironic.netconf

_default_opt_lists = [
    ironic.api.app.api_opts,
    ironic.common.driver_factory.driver_opts,
    ironic.common.exception.exc_log_opts,
    ironic.common.hash_ring.hash_opts,
    ironic.common.images.image_opts,
    ironic.common.paths.path_opts,
    ironic.common.service.service_opts,
    ironic.common.utils.utils_opts,
    ironic.drivers.modules.image_cache.img_cache_opts,
    ironic.netconf.netconf_opts,
]

_opts = [
    ('DEFAULT', itertools.chain(*_default_opt_lists)),
    ('agent', itertools.chain(
        ironic.drivers.modules.agent.agent_opts,
        ironic.drivers.modules.agent_base_vendor.agent_opts,
        ironic.drivers.modules.agent_client.agent_opts)),
    ('amt', itertools.chain(
        ironic.drivers.modules.amt.common.opts,
        ironic.drivers.modules.amt.power.opts)),
    ('api', ironic.api.API_SERVICE_OPTS),
    ('cimc', ironic.conf.cimc.opts),
    ('cisco_ucs', ironic.conf.cisco_ucs.opts),
    ('conductor', ironic.conf.conductor.opts),
    ('console', ironic.conf.console.opts),
    ('database', ironic.conf.database.opts),
    ('deploy', ironic.drivers.modules.deploy_utils.deploy_opts),
    ('dhcp', ironic.conf.dhcp.opts),
    ('glance', itertools.chain(
        ironic.common.glance_service.v2.image_service.glance_opts,
        ironic.common.image_service.glance_opts)),
    ('iboot', ironic.drivers.modules.iboot.opts),
    ('ilo', itertools.chain(
        ironic.drivers.modules.ilo.common.opts,
        ironic.drivers.modules.ilo.deploy.clean_opts,
        ironic.drivers.modules.ilo.management.clean_step_opts,
        ironic.drivers.modules.ilo.power.opts)),
    ('inspector', ironic.drivers.modules.inspector.inspector_opts),
    ('ipmi', ironic.drivers.modules.ipminative.opts),
    ('irmc', itertools.chain(
        ironic.drivers.modules.irmc.boot.opts,
        ironic.drivers.modules.irmc.common.opts)),
    ('iscsi', ironic.drivers.modules.iscsi_deploy.iscsi_opts),
    ('keystone', ironic.common.keystone.keystone_opts),
    ('neutron', ironic.dhcp.neutron.neutron_opts),
    ('oneview', ironic.drivers.modules.oneview.common.opts),
    ('pxe', itertools.chain(
        ironic.drivers.modules.iscsi_deploy.pxe_opts,
        ironic.drivers.modules.pxe.pxe_opts)),
    ('seamicro', ironic.drivers.modules.seamicro.opts),
    ('snmp', ironic.drivers.modules.snmp.opts),
    ('ssh', ironic.drivers.modules.ssh.libvirt_opts),
    ('swift', ironic.common.swift.swift_opts),
    ('virtualbox', ironic.drivers.modules.virtualbox.opts),
]


def list_opts():
    """Return a list of oslo.config options available in Ironic code.

    The returned list includes all oslo.config options. Each element of
    the list is a tuple. The first element is the name of the group, the
    second element is the options.

    The function is discoverable via the 'ironic' entry point under the
    'oslo.config.opts' namespace.

    The function is used by Oslo sample config file generator to discover the
    options.

    :returns: a list of (group, options) tuples
    """
    return _opts
