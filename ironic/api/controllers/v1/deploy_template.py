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
from http import client as http_client

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest
from webob import exc as webob_exc

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
import ironic.conf
from ironic import objects

CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_RETURN_FIELDS = ['uuid', 'name']

TEMPLATE_SCHEMA = {
    'type': 'object',
    'properties': {
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'extra': {'type': ['object', 'null']},
        'name': api_utils.TRAITS_SCHEMA,
        'steps': {'type': 'array', 'items': api_utils.DEPLOY_STEP_SCHEMA,
                  'minItems': 1},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['steps', 'name'],
    'additionalProperties': False,
}

PATCH_ALLOWED_FIELDS = ['extra', 'name', 'steps', 'description']
STEP_PATCH_ALLOWED_FIELDS = ['args', 'interface', 'priority', 'step']


def duplicate_steps(name, value):
    """Argument validator to check template for duplicate steps"""
    # TODO(mgoddard): Determine the consequences of allowing duplicate
    # steps.
    # * What if one step has zero priority and another non-zero?
    # * What if a step that is enabled by default is included in a
    #   template? Do we override the default or add a second invocation?

    # Check for duplicate steps. Each interface/step combination can be
    # specified at most once.
    counter = collections.Counter((step['interface'], step['step'])
                                  for step in value['steps'])
    duplicates = {key for key, count in counter.items() if count > 1}
    if duplicates:
        duplicates = {"interface: %s, step: %s" % (interface, step)
                      for interface, step in duplicates}
        err = _("Duplicate deploy steps. A deploy template cannot have "
                "multiple deploy steps with the same interface and step. "
                "Duplicates: %s") % "; ".join(duplicates)
        raise exception.InvalidDeployTemplate(err=err)
    return value


TEMPLATE_VALIDATOR = args.and_valid(
    args.schema(TEMPLATE_SCHEMA),
    duplicate_steps,
    args.dict_valid(uuid=args.uuid)
)


def convert_steps(rpc_steps):
    for step in rpc_steps:
        yield {
            'interface': step['interface'],
            'step': step['step'],
            'args': step['args'],
            'priority': step['priority'],
        }


def convert_with_links(rpc_template, fields=None, sanitize=True):
    """Add links to the deploy template."""
    template = api_utils.object_to_dict(
        rpc_template,
        fields=('name', 'extra'),
        link_resource='deploy_templates',
    )
    template['steps'] = list(convert_steps(rpc_template.steps))

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, template)

    if sanitize:
        template_sanitize(template, fields)

    return template


def template_sanitize(template, fields):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter.

    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    """
    api_utils.sanitize_dict(template, fields)
    if template.get('steps'):
        for step in template['steps']:
            step_sanitize(step)


def step_sanitize(step):
    if step.get('args'):
        step['args'] = strutils.mask_dict_password(step['args'], "******")


def list_convert_with_links(rpc_templates, limit, fields=None, **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(t, fields=fields, sanitize=False)
               for t in rpc_templates],
        item_name='deploy_templates',
        url='deploy_templates',
        limit=limit,
        fields=fields,
        sanitize_func=template_sanitize,
        **kwargs
    )


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

    @METRICS.timer('DeployTemplatesController.get_all')
    @method.expose()
    @args.validate(marker=args.name, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
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
                                                     DEFAULT_RETURN_FIELDS)

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

        return list_convert_with_links(
            templates, limit, fields=fields, **parameters)

    @METRICS.timer('DeployTemplatesController.get_one')
    @method.expose()
    @args.validate(template_ident=args.uuid_or_name, fields=args.string_list)
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

        return convert_with_links(rpc_template, fields=fields)

    @METRICS.timer('DeployTemplatesController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('template')
    @args.validate(template=TEMPLATE_VALIDATOR)
    def post(self, template):
        """Create a new deploy template.

        :param template: a deploy template within the request body.
        """
        api_utils.check_policy('baremetal:deploy_template:create')

        context = api.request.context

        # NOTE(mgoddard): UUID is mandatory for notifications payload
        if not template.get('uuid'):
            template['uuid'] = uuidutils.generate_uuid()

        new_template = objects.DeployTemplate(context, **template)

        notify.emit_start_notification(context, new_template, 'create')
        with notify.handle_error_notification(context, new_template, 'create'):
            new_template.create()
        # Set the HTTP Location Header
        api.response.location = link.build_url('deploy_templates',
                                               new_template.uuid)
        api_template = convert_with_links(new_template)
        notify.emit_end_notification(context, new_template, 'create')
        return api_template

    @METRICS.timer('DeployTemplatesController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(template_ident=args.uuid_or_name, patch=args.patch)
    def patch(self, template_ident, patch=None):
        """Update an existing deploy template.

        :param template_ident: UUID or logical name of a deploy template.
        :param patch: a json PATCH document to apply to this deploy template.
        """
        api_utils.check_policy('baremetal:deploy_template:update')

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        context = api.request.context
        rpc_template = api_utils.get_rpc_deploy_template_with_suffix(
            template_ident)

        template = rpc_template.as_dict()

        # apply the patch
        template = api_utils.apply_jsonpatch(template, patch)

        # validate the result with the patch schema
        for step in template.get('steps', []):
            api_utils.patched_validate_with_schema(
                step, api_utils.DEPLOY_STEP_SCHEMA)
        api_utils.patched_validate_with_schema(
            template, TEMPLATE_SCHEMA, TEMPLATE_VALIDATOR)

        api_utils.patch_update_changed_fields(
            template, rpc_template, fields=objects.DeployTemplate.fields,
            schema=TEMPLATE_SCHEMA
        )

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

        api_template = convert_with_links(rpc_template)
        notify.emit_end_notification(context, rpc_template, 'update')

        return api_template

    @METRICS.timer('DeployTemplatesController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(template_ident=args.uuid_or_name)
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
