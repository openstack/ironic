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

from ironic_lib import metrics_utils
from oslo_config import cfg
import pecan
from webob import exc as webob_exc

from ironic import api
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common.i18n import _


CONF = cfg.CONF

METRICS = metrics_utils.get_metrics_logger(__name__)


class ShardController(pecan.rest.RestController):
    """REST controller for shards."""

    @pecan.expose()
    def _route(self, argv, request=None):
        if not api_utils.allow_shards_endpoint():
            msg = _("The API version does not allow shards")
            if api.request.method in "GET":
                raise webob_exc.HTTPNotFound(msg)
            else:
                raise webob_exc.HTTPMethodNotAllowed(msg)
        return super(ShardController, self)._route(argv, request)

    @METRICS.timer('ShardController.get_all')
    @method.expose()
    def get_all(self):
        """Retrieve a list of shards.

        :returns: A list of shards.
        """
        api_utils.check_policy('baremetal:shards:get')

        return {
            'shards': api.request.dbapi.get_shard_list(),
        }

    @METRICS.timer('ShardController.get_one')
    @method.expose()
    def get_one(self, __):
        """Explicitly do not support getting one."""
        pecan.abort(404)
