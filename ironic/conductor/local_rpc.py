# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import atexit
import secrets
import socket
import tempfile

from keystoneauth1 import loading as ks_loading
from oslo_log import log

from ironic.common import auth_basic
from ironic.common.json_rpc import client
from ironic.common import tls_utils
from ironic.common import utils
from ironic.conf import CONF


LOG = log.getLogger(__name__)


_PASSWORD_BYTES = 64
_VALID_FOR_DAYS = 9999  # rotation not possible
_USERNAME = 'ironic'


def _lo_has_ipv6():
    """Check if IPv6 is available by attempting to bind to ::1."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('::1', 0))
            return True
    except (OSError, socket.error) as e:
        LOG.debug('IPv6 is not available on localhost: %s', e)
        return False


def _create_tls_files(ip):
    with tempfile.NamedTemporaryFile(
            delete=False, dir=CONF.local_rpc.temp_dir) as fp:
        cert_file = fp.name
    with tempfile.NamedTemporaryFile(
            delete=False, dir=CONF.local_rpc.temp_dir) as fp:
        key_file = fp.name

    tls_utils.generate_tls_certificate(cert_file, key_file,
                                       common_name='ironic',
                                       ip_address=ip,
                                       valid_for_days=_VALID_FOR_DAYS)
    return cert_file, key_file


def _create_htpasswd(password):
    with tempfile.NamedTemporaryFile(
            mode="w+t", delete=False, dir=CONF.local_rpc.temp_dir) as fp:
        auth_basic.write_password(fp, _USERNAME, password)
        return fp.name


def configure():
    """Configure the local JSON RPC bus (if enabled)."""
    if CONF.rpc_transport != 'none':
        return

    ip = '::1' if _lo_has_ipv6() else '127.0.0.1'
    LOG.debug('Configuring local RPC bus on %s:%d', ip, CONF.json_rpc.port)

    if CONF.local_rpc.use_ssl:
        cert_file, key_file = _create_tls_files(ip)

        def _cleanup():
            utils.unlink_without_raise(cert_file)
            utils.unlink_without_raise(key_file)

        atexit.register(_cleanup)
    else:
        cert_file, key_file = None, None
    password = secrets.token_urlsafe(_PASSWORD_BYTES)
    htpasswd_path = _create_htpasswd(password)

    # NOTE(dtantsur): it is not possible to override username/password  without
    # registering http_basic options first.
    opts = ks_loading.get_auth_plugin_conf_options('http_basic')
    CONF.register_opts(opts, group='json_rpc')

    for key, value in [
        ('use_ssl', CONF.local_rpc.use_ssl),
        # Client options
        ('auth_type', 'http_basic'),
        ('cafile', cert_file),
        ('username', _USERNAME),
        ('password', password),
        # Server options
        ('auth_strategy', 'http_basic'),
        ('http_basic_auth_user_file', htpasswd_path),
        ('host_ip', ip),
        ('cert_file', cert_file),
        ('key_file', key_file),
    ]:
        CONF.set_override(key, value, group='json_rpc')


class LocalClient(client.Client):
    """JSON RPC client that always connects to the server's host IP."""

    def prepare(self, topic, version=None):
        # TODO(dtantsur): check that topic matches the expected host name
        # (which is not host_ip, by the way, it's CONF.host).
        return self.prepare_for_target(CONF.json_rpc.host_ip)
