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

import datetime

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import timeutils
from pecan import rest

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
import ironic.conf
from ironic import objects

CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ('hostname', 'conductor_group', 'alive')


class Conductor(base.APIBase):
    """API representation of a bare metal conductor."""

    hostname = atypes.wsattr(str)
    """The hostname for this conductor"""

    conductor_group = atypes.wsattr(str)
    """The conductor group this conductor belongs to"""

    alive = types.boolean
    """Indicates whether this conductor is considered alive"""

    drivers = atypes.wsattr([str])
    """The drivers enabled on this conductor"""

    links = atypes.wsattr([link.Link])
    """A list containing a self link and associated conductor links"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Conductor.fields)
        # NOTE(kaifeng): alive is not part of objects.Conductor.fields
        # because it's an API-only attribute.
        fields.append('alive')

        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, atypes.Unset))

    @staticmethod
    def _convert_with_links(conductor, url, fields=None):
        conductor.links = [link.Link.make_link('self', url, 'conductors',
                                               conductor.hostname),
                           link.Link.make_link('bookmark', url, 'conductors',
                                               conductor.hostname,
                                               bookmark=True)]
        return conductor

    @classmethod
    def convert_with_links(cls, rpc_conductor, fields=None):
        conductor = Conductor(**rpc_conductor.as_dict())
        conductor.alive = not timeutils.is_older_than(
            conductor.updated_at, CONF.conductor.heartbeat_timeout)

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, conductor.as_dict())

        conductor = cls._convert_with_links(conductor,
                                            api.request.public_url,
                                            fields=fields)
        conductor.sanitize(fields)
        return conductor

    def sanitize(self, fields):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """
        if fields is not None:
            self.unset_fields_except(fields)

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        sample = cls(hostname='computer01',
                     conductor_group='',
                     alive=True,
                     drivers=['ipmi'],
                     created_at=time,
                     updated_at=time)
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class ConductorCollection(collection.Collection):
    """API representation of a collection of conductors."""

    conductors = [Conductor]
    """A list containing conductor objects"""

    def __init__(self, **kwargs):
        self._type = 'conductors'

    # NOTE(kaifeng) Override because conductors use hostname instead of uuid.
    @classmethod
    def get_key_field(cls):
        return 'hostname'

    @staticmethod
    def convert_with_links(conductors, limit, url=None, fields=None, **kwargs):
        collection = ConductorCollection()
        collection.conductors = [Conductor.convert_with_links(c, fields=fields)
                                 for c in conductors]
        collection.next = collection.get_next(limit, url=url, fields=fields,
                                              **kwargs)

        for conductor in collection.conductors:
            conductor.sanitize(fields)

        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        conductor = Conductor.sample(expand=False)
        sample.conductors = [conductor]
        return sample


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

        return ConductorCollection.convert_with_links(conductors, limit,
                                                      url=resource_url,
                                                      fields=fields,
                                                      **parameters)

    @METRICS.timer('ConductorsController.get_all')
    @expose.expose(ConductorCollection, types.name, int, str,
                   str, types.listtype, types.boolean)
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
                                                     _DEFAULT_RETURN_FIELDS)

        return self._get_conductors_collection(marker, limit, sort_key,
                                               sort_dir, fields=fields,
                                               detail=detail)

    @METRICS.timer('ConductorsController.get_one')
    @expose.expose(Conductor, types.name, types.listtype)
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
        return Conductor.convert_with_links(conductor, fields=fields)
