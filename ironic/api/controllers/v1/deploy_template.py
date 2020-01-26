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

import collections
import datetime
from http import client as http_client

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest
from webob import exc as webob_exc
import wsme

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import steps as conductor_steps
import ironic.conf
from ironic import objects

CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ('uuid', 'name')

_DEPLOY_INTERFACE_TYPE = atypes.Enum(
    str, *conductor_steps.DEPLOYING_INTERFACE_PRIORITY)


class DeployStepType(atypes.Base, base.AsDictMixin):
    """A type describing a deployment step."""

    interface = atypes.wsattr(_DEPLOY_INTERFACE_TYPE, mandatory=True)

    step = atypes.wsattr(str, mandatory=True)

    args = atypes.wsattr({str: types.jsontype}, mandatory=True)

    priority = atypes.wsattr(atypes.IntegerType(0), mandatory=True)

    def __init__(self, **kwargs):
        self.fields = ['interface', 'step', 'args', 'priority']
        for field in self.fields:
            value = kwargs.get(field, atypes.Unset)
            setattr(self, field, value)

    def sanitize(self):
        """Removes sensitive data."""
        if self.args != atypes.Unset:
            self.args = strutils.mask_dict_password(self.args, "******")


class DeployTemplate(base.APIBase):
    """API representation of a deploy template."""

    uuid = types.uuid
    """Unique UUID for this deploy template."""

    name = atypes.wsattr(str, mandatory=True)
    """The logical name for this deploy template."""

    steps = atypes.wsattr([DeployStepType], mandatory=True)
    """The deploy steps of this deploy template."""

    links = atypes.wsattr([link.Link])
    """A list containing a self link and associated deploy template links."""

    extra = {str: types.jsontype}
    """This deploy template's meta data"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.DeployTemplate.fields)

        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue

            value = kwargs.get(field, atypes.Unset)
            if field == 'steps' and value != atypes.Unset:
                value = [DeployStepType(**step) for step in value]
            self.fields.append(field)
            setattr(self, field, value)

    @staticmethod
    def validate(value):
        if value is None:
            return

        # The name is mandatory, but the 'mandatory' attribute support in
        # wsattr allows None.
        if value.name is None:
            err = _("Deploy template name cannot be None")
            raise exception.InvalidDeployTemplate(err=err)

        # The name must also be a valid trait.
        api_utils.validate_trait(
            value.name,
            error_prefix=_("Deploy template name must be a valid trait"))

        # There must be at least one step.
        if not value.steps:
            err = _("No deploy steps specified. A deploy template must have "
                    "at least one deploy step.")
            raise exception.InvalidDeployTemplate(err=err)

        # TODO(mgoddard): Determine the consequences of allowing duplicate
        # steps.
        # * What if one step has zero priority and another non-zero?
        # * What if a step that is enabled by default is included in a
        #   template? Do we override the default or add a second invocation?

        # Check for duplicate steps. Each interface/step combination can be
        # specified at most once.
        counter = collections.Counter((step.interface, step.step)
                                      for step in value.steps)
        duplicates = {key for key, count in counter.items() if count > 1}
        if duplicates:
            duplicates = {"interface: %s, step: %s" % (interface, step)
                          for interface, step in duplicates}
            err = _("Duplicate deploy steps. A deploy template cannot have "
                    "multiple deploy steps with the same interface and step. "
                    "Duplicates: %s") % "; ".join(duplicates)
            raise exception.InvalidDeployTemplate(err=err)
        return value

    @staticmethod
    def _convert_with_links(template, url, fields=None):
        template.links = [
            link.Link.make_link('self', url, 'deploy_templates',
                                template.uuid),
            link.Link.make_link('bookmark', url, 'deploy_templates',
                                template.uuid,
                                bookmark=True)
        ]
        return template

    @classmethod
    def convert_with_links(cls, rpc_template, fields=None, sanitize=True):
        """Add links to the deploy template."""
        template = DeployTemplate(**rpc_template.as_dict())

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, template.as_dict())

        template = cls._convert_with_links(template,
                                           api.request.public_url,
                                           fields=fields)
        if sanitize:
            template.sanitize(fields)

        return template

    def sanitize(self, fields):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """
        if self.steps != atypes.Unset:
            for step in self.steps:
                step.sanitize()

        if fields is not None:
            self.unset_fields_except(fields)

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        template_uuid = '534e73fa-1014-4e58-969a-814cc0cb9d43'
        template_name = 'CUSTOM_RAID1'
        template_steps = [{
            "interface": "raid",
            "step": "create_configuration",
            "args": {
                "logical_disks": [{
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "is_root_volume": True
                }],
                "delete_configuration": True
            },
            "priority": 10
        }]
        template_extra = {'foo': 'bar'}
        sample = cls(uuid=template_uuid,
                     name=template_name,
                     steps=template_steps,
                     extra=template_extra,
                     created_at=time,
                     updated_at=time)
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class DeployTemplatePatchType(types.JsonPatchType):

    _api_base = DeployTemplate


class DeployTemplateCollection(collection.Collection):
    """API representation of a collection of deploy templates."""

    _type = 'deploy_templates'

    deploy_templates = [DeployTemplate]
    """A list containing deploy template objects"""

    @staticmethod
    def convert_with_links(templates, limit, fields=None, **kwargs):
        collection = DeployTemplateCollection()
        collection.deploy_templates = [
            DeployTemplate.convert_with_links(t, fields=fields, sanitize=False)
            for t in templates]
        collection.next = collection.get_next(limit, fields=fields, **kwargs)

        for template in collection.deploy_templates:
            template.sanitize(fields)

        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        template = DeployTemplate.sample(expand=False)
        sample.deploy_templates = [template]
        return sample


class DeployTemplatesController(rest.RestController):
    """REST controller for deploy templates."""

    invalid_sort_key_list = ['extra', 'steps']

    @pecan.expose()
    def _route(self, args, request=None):
        if not api_utils.allow_deploy_templates():
            msg = _("The API version does not allow deploy templates")
            if api.request.method == "GET":
                raise webob_exc.HTTPNotFound(msg)
            else:
                raise webob_exc.HTTPMethodNotAllowed(msg)
        return super(DeployTemplatesController, self)._route(args, request)

    def _update_changed_fields(self, template, rpc_template):
        """Update rpc_template based on changed fields in a template."""
        for field in objects.DeployTemplate.fields:
            try:
                patch_val = getattr(template, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API.
                continue
            if patch_val == atypes.Unset:
                patch_val = None
            if rpc_template[field] != patch_val:
                if field == 'steps' and patch_val is not None:
                    # Convert from DeployStepType to dict.
                    patch_val = [s.as_dict() for s in patch_val]
                rpc_template[field] = patch_val

    @METRICS.timer('DeployTemplatesController.get_all')
    @expose.expose(DeployTemplateCollection, types.name, int, str,
                   str, types.listtype, types.boolean)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc',
                fields=None, detail=None):
        """Retrieve a list of deploy templates.

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
                       of deploy templates with detail.
        """
        api_utils.check_policy('baremetal:deploy_template:get')

        api_utils.check_allowed_fields(fields)
        api_utils.check_allowed_fields([sort_key])

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     _DEFAULT_RETURN_FIELDS)

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        marker_obj = None
        if marker:
            marker_obj = objects.DeployTemplate.get_by_uuid(
                api.request.context, marker)

        templates = objects.DeployTemplate.list(
            api.request.context, limit=limit, marker=marker_obj,
            sort_key=sort_key, sort_dir=sort_dir)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}

        if detail is not None:
            parameters['detail'] = detail

        return DeployTemplateCollection.convert_with_links(
            templates, limit, fields=fields, **parameters)

    @METRICS.timer('DeployTemplatesController.get_one')
    @expose.expose(DeployTemplate, types.uuid_or_name, types.listtype)
    def get_one(self, template_ident, fields=None):
        """Retrieve information about the given deploy template.

        :param template_ident: UUID or logical name of a deploy template.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        api_utils.check_policy('baremetal:deploy_template:get')

        api_utils.check_allowed_fields(fields)

        rpc_template = api_utils.get_rpc_deploy_template_with_suffix(
            template_ident)

        return DeployTemplate.convert_with_links(rpc_template, fields=fields)

    @METRICS.timer('DeployTemplatesController.post')
    @expose.expose(DeployTemplate, body=DeployTemplate,
                   status_code=http_client.CREATED)
    def post(self, template):
        """Create a new deploy template.

        :param template: a deploy template within the request body.
        """
        api_utils.check_policy('baremetal:deploy_template:create')

        context = api.request.context
        tdict = template.as_dict()
        # NOTE(mgoddard): UUID is mandatory for notifications payload
        if not tdict.get('uuid'):
            tdict['uuid'] = uuidutils.generate_uuid()

        new_template = objects.DeployTemplate(context, **tdict)

        notify.emit_start_notification(context, new_template, 'create')
        with notify.handle_error_notification(context, new_template, 'create'):
            new_template.create()
        # Set the HTTP Location Header
        api.response.location = link.build_url('deploy_templates',
                                               new_template.uuid)
        api_template = DeployTemplate.convert_with_links(new_template)
        notify.emit_end_notification(context, new_template, 'create')
        return api_template

    @METRICS.timer('DeployTemplatesController.patch')
    @wsme.validate(types.uuid, types.boolean, [DeployTemplatePatchType])
    @expose.expose(DeployTemplate, types.uuid_or_name, types.boolean,
                   body=[DeployTemplatePatchType])
    def patch(self, template_ident, patch=None):
        """Update an existing deploy template.

        :param template_ident: UUID or logical name of a deploy template.
        :param patch: a json PATCH document to apply to this deploy template.
        """
        api_utils.check_policy('baremetal:deploy_template:update')

        context = api.request.context
        rpc_template = api_utils.get_rpc_deploy_template_with_suffix(
            template_ident)

        template_dict = rpc_template.as_dict()
        template = DeployTemplate(
            **api_utils.apply_jsonpatch(template_dict, patch))
        template.validate(template)
        self._update_changed_fields(template, rpc_template)

        # NOTE(mgoddard): There could be issues with concurrent updates of a
        # template. This is particularly true for the complex 'steps' field,
        # where operations such as modifying a single step could result in
        # changes being lost, e.g. two requests concurrently appending a step
        # to the same template could result in only one of the steps being
        # added, due to the read/modify/write nature of this patch operation.
        # This issue should not be present for 'simple' string fields, or
        # complete replacement of the steps (the only operation supported by
        # the openstack baremetal CLI). It's likely that this is an issue for
        # other resources, even those modified in the conductor under a lock.
        # This is due to the fact that the patch operation is always applied in
        # the API. Ways to avoid this include passing the patch to the
        # conductor to apply while holding a lock, or a collision detection
        # & retry mechansim using e.g. the updated_at field.
        notify.emit_start_notification(context, rpc_template, 'update')
        with notify.handle_error_notification(context, rpc_template, 'update'):
            rpc_template.save()

        api_template = DeployTemplate.convert_with_links(rpc_template)
        notify.emit_end_notification(context, rpc_template, 'update')

        return api_template

    @METRICS.timer('DeployTemplatesController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
    def delete(self, template_ident):
        """Delete a deploy template.

        :param template_ident: UUID or logical name of a deploy template.
        """
        api_utils.check_policy('baremetal:deploy_template:delete')

        context = api.request.context
        rpc_template = api_utils.get_rpc_deploy_template_with_suffix(
            template_ident)
        notify.emit_start_notification(context, rpc_template, 'delete')
        with notify.handle_error_notification(context, rpc_template, 'delete'):
            rpc_template.destroy()
        notify.emit_end_notification(context, rpc_template, 'delete')
