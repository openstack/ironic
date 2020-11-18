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

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import timeutils
from pecan import rest

from ironic import api
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
import ironic.conf
from ironic import objects

CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_RETURN_FIELDS = ['hostname', 'conductor_group', 'alive']


def convert_with_links(rpc_conductor, fields=None, sanitize=True):
    conductor = api_utils.object_to_dict(
        rpc_conductor,
        uuid=False,
        fields=('hostname', 'conductor_group', 'drivers'),
        link_resource='conductors',
        link_resource_args=rpc_conductor.hostname
    )
    conductor['alive'] = not timeutils.is_older_than(
        rpc_conductor.updated_at, CONF.conductor.heartbeat_timeout)
    if fields is not None:
        api_utils.check_for_invalid_fields(fields, conductor)

    if sanitize:
        api_utils.sanitize_dict(conductor, fields)
    return conductor


def list_convert_with_links(rpc_conductors, limit, url=None, fields=None,
                            **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(c, fields=fields, sanitize=False)
               for c in rpc_conductors],
        item_name='conductors',
        limit=limit,
        url=url,
        fields=fields,
        key_field='hostname',
        sanitize_func=api_utils.sanitize_dict,
        **kwargs
    )


class ConductorsController(rest.RestController):
    """REST controller for conductors."""

    invalid_sort_key_list = ['alive', 'drivers']

    def _get_conductors_collection(self, marker, limit, sort_key, sort_dir,
                                   resource_url=None, fields=None,
                                   detail=None):

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        marker_obj = None
        if marker:
            marker_obj = objects.Conductor.get_by_hostname(
                api.request.context, marker, online=None)

        conductors = objects.Conductor.list(api.request.context, limit=limit,
                                            marker=marker_obj,
                                            sort_key=sort_key,
                                            sort_dir=sort_dir)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}

        if detail is not None:
            parameters['detail'] = detail

        return list_convert_with_links(conductors, limit, url=resource_url,
                                       fields=fields, **parameters)

    @METRICS.timer('ConductorsController.get_all')
    @method.expose()
    @args.validate(marker=args.name, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc',
                fields=None, detail=None):
        """Retrieve a list of conductors.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        :param detail: Optional, boolean to indicate whether retrieve a list
                       of conductors with detail.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:conductor:get', cdict, cdict)

        if not api_utils.allow_expose_conductors():
            raise exception.NotFound()

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)
        api_utils.check_allowed_fields([sort_key])

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     DEFAULT_RETURN_FIELDS)

        return self._get_conductors_collection(marker, limit, sort_key,
                                               sort_dir, fields=fields,
                                               detail=detail)

    @METRICS.timer('ConductorsController.get_one')
    @method.expose()
    @args.validate(hostname=args.name, fields=args.string_list)
    def get_one(self, hostname, fields=None):
        """Retrieve information about the given conductor.

        :param hostname: hostname of a conductor.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:conductor:get', cdict, cdict)

        if not api_utils.allow_expose_conductors():
            raise exception.NotFound()

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)

        conductor = objects.Conductor.get_by_hostname(api.request.context,
                                                      hostname, online=None)
        return convert_with_links(conductor, fields=fields)
