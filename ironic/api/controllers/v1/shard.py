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

from oslo_config import cfg
import pecan

from ironic import api
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api import method
from ironic.api.schemas.v1 import shard as schema
from ironic.api import validation
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic import objects


CONF = cfg.CONF

METRICS = metrics_utils.get_metrics_logger(__name__)


class ShardController(pecan.rest.RestController):
    """REST controller for shards."""

    @METRICS.timer('ShardController.get_all')
    @method.expose()
    @validation.api_version(
        min_version=versions.MINOR_82_NODE_SHARD,
        message=_('The API version does not allow shards'),
    )
    @validation.request_query_schema(schema.index_request_query)
    @validation.response_body_schema(schema.index_response_body)
    def get_all(self):
        """Retrieve a list of shards.

        :returns: A list of shards.
        """
        api_utils.check_policy('baremetal:shards:get')

        return {
            'shards': objects.Conductor.get_shard_list(api.request.context),
        }

    @METRICS.timer('ShardController.get_one')
    @method.expose()
    @validation.api_version(
        min_version=versions.MINOR_82_NODE_SHARD,
        message=_('The API version does not allow shards'),
    )
    def get_one(self, _):
        """Explicitly do not support getting one."""
        pecan.abort(404)
