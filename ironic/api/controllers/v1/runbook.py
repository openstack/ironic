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

RUNBOOK_SCHEMA = {
    'type': 'object',
    'properties': {
        'uuid': {'type': ['string', 'null']},
        'name': api_utils.TRAITS_SCHEMA,
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'steps': {
            'type': 'array',
            'items': api_utils.RUNBOOK_STEP_SCHEMA,
            'minItems': 1},
        'disable_ramdisk': {'type': ['boolean', 'null']},
        'extra': {'type': ['object', 'null']},
        'public': {'type': ['boolean', 'null']},
        'owner': {'type': ['string', 'null'], 'maxLength': 255}
    },
    'required': ['steps', 'name'],
    'additionalProperties': False,
}

PATCH_ALLOWED_FIELDS = [
    'extra',
    'name',
    'steps',
    'description',
    'public',
    'owner'
]
STEP_PATCH_ALLOWED_FIELDS = ['args', 'interface', 'order', 'step']


RUNBOOK_VALIDATOR = args.and_valid(
    args.schema(RUNBOOK_SCHEMA),
    api_utils.duplicate_steps,
    args.dict_valid(uuid=args.uuid)
)


def convert_with_links(rpc_runbook, fields=None, sanitize=True):
    """Add links to the runbook."""
    runbook = api_utils.object_to_dict(
        rpc_runbook,
        fields=('name', 'extra', 'public', 'owner', 'disable_ramdisk'),
        link_resource='runbooks',
    )
    runbook['steps'] = list(api_utils.convert_steps(rpc_runbook.steps))

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, runbook)

    if sanitize:
        runbook_sanitize(runbook, fields)

    return runbook


def runbook_sanitize(runbook, fields):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter.

    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    """
    api_utils.sanitize_dict(runbook, fields)
    if runbook.get('steps'):
        for step in runbook['steps']:
            step_sanitize(step)


def step_sanitize(step):
    if step.get('args'):
        step['args'] = strutils.mask_dict_password(step['args'], "******")


def list_convert_with_links(rpc_runbooks, limit, fields=None, **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(t, fields=fields, sanitize=False)
               for t in rpc_runbooks],
        item_name='runbooks',
        url='runbooks',
        limit=limit,
        fields=fields,
        sanitize_func=runbook_sanitize,
        **kwargs
    )


class RunbooksController(rest.RestController):
    """REST controller for runbooks."""

    invalid_sort_key_list = ['extra', 'steps']

    @pecan.expose()
    def _route(self, args, request=None):
        if not api_utils.allow_runbooks():
            msg = _("The API version does not allow runbooks")
            if api.request.method == "GET":
                raise webob_exc.HTTPNotFound(msg)
            else:
                raise webob_exc.HTTPMethodNotAllowed(msg)
        return super(RunbooksController, self)._route(args, request)

    @METRICS.timer('RunbooksController.get_all')
    @method.expose()
    @args.validate(marker=args.name, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean, project=args.boolean)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc',
                fields=None, detail=None, project=None):
        """Retrieve a list of runbooks.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param project: Optional string value that set the project
                        whose runbooks are to be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        :param detail: Optional, boolean to indicate whether retrieve a list
                       of runbooks with detail.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        project_id = api_utils.check_list_policy('runbook', project)

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

        filters = {}
        if project_id:
            filters['project'] = project_id

        marker_obj = None
        if marker:
            marker_obj = objects.Runbook.get_by_uuid(
                api.request.context, marker)

        runbooks = objects.Runbook.list(
            api.request.context, limit=limit, marker=marker_obj,
            sort_key=sort_key, sort_dir=sort_dir, filters=filters)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}

        if detail is not None:
            parameters['detail'] = detail

        return list_convert_with_links(
            runbooks, limit, fields=fields, **parameters)

    @METRICS.timer('RunbooksController.get_one')
    @method.expose()
    @args.validate(runbook_ident=args.uuid_or_name, fields=args.string_list)
    def get_one(self, runbook_ident, fields=None):
        """Retrieve information about the given runbook.

        :param runbook_ident: UUID or logical name of a runbook.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        try:
            rpc_runbook = api_utils.check_runbook_policy_and_retrieve(
                'baremetal:runbook:get', runbook_ident)
        except exception.NotAuthorized:
            # If the user is not authorized to access the runbook,
            # check also, if the runbook is public
            rpc_runbook = api_utils.check_and_retrieve_public_runbook(
                runbook_ident)

        api_utils.check_allowed_fields(fields)
        return convert_with_links(rpc_runbook, fields=fields)

    @METRICS.timer('RunbooksController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('runbook')
    @args.validate(runbook=RUNBOOK_VALIDATOR)
    def post(self, runbook):
        """Create a new runbook.

        :param runbook: a runbook within the request body.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        context = api.request.context
        api_utils.check_policy('baremetal:runbook:create')

        cdict = context.to_policy_values()
        if cdict.get('system_scope') != 'all':
            project_id = None
            requested_owner = runbook.get('owner', None)
            if cdict.get('project_id', False):
                project_id = cdict.get('project_id')

            if requested_owner and requested_owner != project_id:
                # Translation: If project scoped, and an owner has been
                # requested, and that owner does not match the requester's
                # project ID value.
                msg = _("Cannot create a runbook as a project scoped admin "
                        "with an owner other than your own project.")
                raise exception.Invalid(msg)

            if project_id and runbook.get('public', False):
                msg = _("Cannot create a public runbook as a project scoped "
                        "admin.")
                raise exception.Invalid(msg)
            # Finally, note the project ID
            runbook['owner'] = project_id

        if not runbook.get('uuid'):
            runbook['uuid'] = uuidutils.generate_uuid()
        new_runbook = objects.Runbook(context, **runbook)

        notify.emit_start_notification(context, new_runbook, 'create')
        with notify.handle_error_notification(context, new_runbook, 'create'):
            new_runbook.create()

        # Set the HTTP Location Header
        api.response.location = link.build_url('runbooks', new_runbook.uuid)
        api_runbook = convert_with_links(new_runbook)
        notify.emit_end_notification(context, new_runbook, 'create')
        return api_runbook

    def _authorize_patch_and_get_runbook(self, runbook_ident, patch):
        # deal with attribute-specific policy rules
        policy_checks = []
        generic_update = False

        paths_to_policy = (
            ('/owner', 'baremetal:runbook:update:owner'),
            ('/public', 'baremetal:runbook:update:public'),
        )
        for p in patch:
            # Process general direct path to policy map
            rule_match_found = False
            for check_path, policy_name in paths_to_policy:
                if p['path'].startswith(check_path):
                    policy_checks.append(policy_name)
                    # Break, policy found
                    rule_match_found = True
                    break
            if not rule_match_found:
                generic_update = True

        if generic_update or not policy_checks:
            # If we couldn't find specific policy to apply,
            # apply the update policy check.
            policy_checks.append('baremetal:runbook:update')
        return api_utils.check_multiple_runbook_policies_and_retrieve(
            policy_checks, runbook_ident)

    @METRICS.timer('RunbooksController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(runbook_ident=args.uuid_or_name, patch=args.patch)
    def patch(self, runbook_ident, patch=None):
        """Update an existing runbook.

        :param runbook_ident: UUID or logical name of a runbook.
        :param patch: a json PATCH document to apply to this runbook.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        context = api.request.context

        rpc_runbook = self._authorize_patch_and_get_runbook(runbook_ident,
                                                            patch)
        runbook = rpc_runbook.as_dict()

        owner = api_utils.get_patch_values(patch, '/owner')
        public = api_utils.get_patch_values(patch, '/public')

        if owner:
            # NOTE(cid): There should not be an owner for a public runbook,
            # but an owned runbook can be set to non-public and assigned an
            # owner atomically
            public_value = public[0] if public else False
            if runbook.get('public') and (not public) or public_value:
                msg = _("There cannot be an owner for a public runbook")
                raise exception.PatchError(patch=patch, reason=msg)

        if public:
            runbook['owner'] = None

        # apply the patch
        runbook = api_utils.apply_jsonpatch(runbook, patch)

        # validate the result with the patch schema
        for step in runbook.get('steps', []):
            api_utils.patched_validate_with_schema(
                step, api_utils.RUNBOOK_STEP_SCHEMA)
        api_utils.patched_validate_with_schema(
            runbook, RUNBOOK_SCHEMA, RUNBOOK_VALIDATOR)

        api_utils.patch_update_changed_fields(
            runbook, rpc_runbook, fields=objects.Runbook.fields,
            schema=RUNBOOK_SCHEMA
        )

        notify.emit_start_notification(context, rpc_runbook, 'update')
        with notify.handle_error_notification(context, rpc_runbook, 'update'):
            rpc_runbook.save()

        api_runbook = convert_with_links(rpc_runbook)
        notify.emit_end_notification(context, rpc_runbook, 'update')

        return api_runbook

    @METRICS.timer('RunbooksController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(runbook_ident=args.uuid_or_name)
    def delete(self, runbook_ident):
        """Delete a runbook.

        :param runbook_ident: UUID or logical name of a runbook.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        rpc_runbook = api_utils.check_runbook_policy_and_retrieve(
            policy_name='baremetal:runbook:delete',
            runbook_ident=runbook_ident)

        context = api.request.context
        notify.emit_start_notification(context, rpc_runbook, 'delete')
        with notify.handle_error_notification(context, rpc_runbook, 'delete'):
            rpc_runbook.destroy()
        notify.emit_end_notification(context, rpc_runbook, 'delete')
