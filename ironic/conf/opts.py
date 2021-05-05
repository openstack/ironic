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

from oslo_log import log

import ironic.conf


_opts = [
    ('DEFAULT', ironic.conf.default.list_opts()),
    ('agent', ironic.conf.agent.opts),
    ('ansible', ironic.conf.ansible.opts),
    ('api', ironic.conf.api.opts),
    ('audit', ironic.conf.audit.opts),
    ('cinder', ironic.conf.cinder.list_opts()),
    ('conductor', ironic.conf.conductor.opts),
    ('console', ironic.conf.console.opts),
    ('database', ironic.conf.database.opts),
    ('deploy', ironic.conf.deploy.opts),
    ('dhcp', ironic.conf.dhcp.opts),
    ('drac', ironic.conf.drac.opts),
    ('glance', ironic.conf.glance.list_opts()),
    ('healthcheck', ironic.conf.healthcheck.opts),
    ('ilo', ironic.conf.ilo.opts),
    ('inspector', ironic.conf.inspector.list_opts()),
    ('ipmi', ironic.conf.ipmi.opts),
    ('irmc', ironic.conf.irmc.opts),
    ('anaconda', ironic.conf.anaconda.opts),
    ('metrics', ironic.conf.metrics.opts),
    ('metrics_statsd', ironic.conf.metrics_statsd.opts),
    ('molds', ironic.conf.molds.opts),
    ('neutron', ironic.conf.neutron.list_opts()),
    ('nova', ironic.conf.nova.list_opts()),
    ('pxe', ironic.conf.pxe.opts),
    ('redfish', ironic.conf.redfish.opts),
    ('service_catalog', ironic.conf.service_catalog.list_opts()),
    ('snmp', ironic.conf.snmp.opts),
    ('swift', ironic.conf.swift.list_opts()),
    ('xclarity', ironic.conf.xclarity.opts),
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


def update_opt_defaults():
    log.set_defaults(
        default_log_levels=[
            'amqp=WARNING',
            'amqplib=WARNING',
            'qpid.messaging=INFO',
            # This comes in two flavors
            'oslo.messaging=INFO',
            'oslo_messaging=INFO',
            'sqlalchemy=WARNING',
            'stevedore=INFO',
            'eventlet.wsgi.server=INFO',
            'iso8601=WARNING',
            'requests=WARNING',
            'glanceclient=WARNING',
            'urllib3.connectionpool=WARNING',
            'keystonemiddleware.auth_token=INFO',
            'keystoneauth.session=INFO',
            'openstack=WARNING',
        ]
    )
