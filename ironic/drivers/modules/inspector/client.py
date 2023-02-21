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

"""Client helper for ironic-inspector."""

from keystoneauth1 import exceptions as ks_exception
import openstack

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import CONF


_INSPECTOR_SESSION = None


def _get_inspector_session(**kwargs):
    global _INSPECTOR_SESSION
    if not _INSPECTOR_SESSION:
        if CONF.auth_strategy != 'keystone':
            # NOTE(dtantsur): using set_default instead of set_override because
            # the native keystoneauth option must have priority.
            CONF.set_default('auth_type', 'none', group='inspector')
        service_auth = keystone.get_auth('inspector')
        _INSPECTOR_SESSION = keystone.get_session('inspector',
                                                  auth=service_auth,
                                                  **kwargs)
    return _INSPECTOR_SESSION


def get_client(context):
    """Helper to get inspector client instance."""
    session = _get_inspector_session()
    # NOTE(dtantsur): openstacksdk expects config option groups to match
    # service name, but we use just "inspector".
    conf = dict(CONF)
    conf['ironic-inspector'] = conf.pop('inspector')
    # TODO(pas-ha) investigate possibility of passing user context here,
    # similar to what neutron/glance-related code does
    try:
        return openstack.connection.Connection(
            session=session,
            oslo_conf=conf).baremetal_introspection
    except ks_exception.DiscoveryFailure as exc:
        raise exception.ConfigInvalid(
            _("Could not contact ironic-inspector for version discovery: %s")
            % exc)
