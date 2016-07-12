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
import ironic.common.hash_ring
import ironic.common.images
import ironic.common.neutron
import ironic.common.paths
import ironic.common.service
import ironic.common.utils
import ironic.drivers.modules.agent
import ironic.drivers.modules.agent_base_vendor
import ironic.drivers.modules.agent_client
import ironic.drivers.modules.amt.common
import ironic.drivers.modules.amt.power
import ironic.drivers.modules.deploy_utils
import ironic.drivers.modules.image_cache
import ironic.drivers.modules.iscsi_deploy
import ironic.drivers.modules.pxe
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
    ('glance', ironic.conf.glance.opts),
    ('iboot', ironic.conf.iboot.opts),
    ('ilo', ironic.conf.ilo.opts),
    ('inspector', ironic.conf.inspector.opts),
    ('ipmi', ironic.conf.ipmi.opts),
    ('irmc', ironic.conf.irmc.opts),
    ('iscsi', ironic.drivers.modules.iscsi_deploy.iscsi_opts),
    ('keystone', ironic.conf.keystone.opts),
    ('neutron', ironic.common.neutron.neutron_opts),
    ('oneview', ironic.conf.oneview.opts),
    ('pxe', itertools.chain(
        ironic.drivers.modules.iscsi_deploy.pxe_opts,
        ironic.drivers.modules.pxe.pxe_opts)),
    ('seamicro', ironic.conf.seamicro.opts),
    ('snmp', ironic.conf.snmp.opts),
    ('ssh', ironic.conf.ssh.opts),
    ('swift', ironic.conf.swift.opts),
    ('virtualbox', ironic.conf.virtualbox.opts),
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
