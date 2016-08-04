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

import ironic.drivers.modules.amt.common
import ironic.drivers.modules.amt.power
import ironic.drivers.modules.iscsi_deploy
import ironic.drivers.modules.pxe

_default_opt_lists = [
    ironic.conf.default.api_opts,
    ironic.conf.default.driver_opts,
    ironic.conf.default.exc_log_opts,
    ironic.conf.default.hash_opts,
    ironic.conf.default.image_opts,
    ironic.conf.default.img_cache_opts,
    ironic.conf.default.netconf_opts,
    ironic.conf.default.path_opts,
    ironic.conf.default.service_opts,
    ironic.conf.default.utils_opts,
]

_opts = [
    ('DEFAULT', itertools.chain(*_default_opt_lists)),
    ('agent', ironic.conf.agent.opts),
    ('amt', itertools.chain(
        ironic.drivers.modules.amt.common.opts,
        ironic.drivers.modules.amt.power.opts)),
    ('api', ironic.conf.api.opts),
    ('audit', ironic.conf.audit.opts),
    ('cimc', ironic.conf.cimc.opts),
    ('cisco_ucs', ironic.conf.cisco_ucs.opts),
    ('conductor', ironic.conf.conductor.opts),
    ('console', ironic.conf.console.opts),
    ('database', ironic.conf.database.opts),
    ('deploy', ironic.conf.deploy.opts),
    ('dhcp', ironic.conf.dhcp.opts),
    ('glance', ironic.conf.glance.list_opts()),
    ('iboot', ironic.conf.iboot.opts),
    ('ilo', ironic.conf.ilo.opts),
    ('inspector', ironic.conf.inspector.list_opts()),
    ('ipmi', ironic.conf.ipmi.opts),
    ('irmc', ironic.conf.irmc.opts),
    ('iscsi', ironic.drivers.modules.iscsi_deploy.iscsi_opts),
    ('keystone', ironic.conf.keystone.opts),
    ('metrics', ironic.conf.metrics.opts),
    ('metrics_statsd', ironic.conf.metrics_statsd.opts),
    ('neutron', ironic.conf.neutron.list_opts()),
    ('oneview', ironic.conf.oneview.opts),
    ('pxe', itertools.chain(
        ironic.drivers.modules.iscsi_deploy.pxe_opts,
        ironic.drivers.modules.pxe.pxe_opts)),
    ('seamicro', ironic.conf.seamicro.opts),
    ('service_catalog', ironic.conf.service_catalog.list_opts()),
    ('snmp', ironic.conf.snmp.opts),
    ('ssh', ironic.conf.ssh.opts),
    ('swift', ironic.conf.swift.list_opts()),
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
