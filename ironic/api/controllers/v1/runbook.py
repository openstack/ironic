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

import copy
from http import client as http_client

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
from ironic.common import metrics_utils
import ironic.conf
from ironic import objects


CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_RETURN_FIELDS = ['uuid', 'name']

# JSON schema for the runbook name when API version >= 1.112.
# Names must still be valid RFC 3986 unreserved-character strings so that they
# can be resolved by name in URL paths (ALPHA / DIGIT / "-" / "." / "_" / "~").
RUNBOOK_NAME_SCHEMA = {
    'type': 'string',
    'minLength': 1,
    'maxLength': 255,
    'pattern': r'^[A-Za-z0-9\-._~]+$',
}

RUNBOOK_SCHEMA = {
    'type': 'object',
    'properties': {
        'uuid': {'type': ['string', 'null']},
        'name': api_utils.TRAITS_SCHEMA,
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

# Schema for API version >= 1.112: name may be any logical string, and
# a 'traits' list is included in GET responses only.
RUNBOOK_SCHEMA_V112 = copy.deepcopy(RUNBOOK_SCHEMA)
RUNBOOK_SCHEMA_V112['properties']['name'] = RUNBOOK_NAME_SCHEMA
RUNBOOK_SCHEMA_V112['properties']['description'] = {
    'type': ['string', 'null'], 'maxLength': 255}
RUNBOOK_SCHEMA_V112['properties']['traits'] = {
    'type': 'array',
    'items': api_utils.TRAITS_SCHEMA,
}

# Schema used for both CREATE and PATCH operations in API version >= 1.112.
# Traits are not allowed in these operations (use the /traits sub-resource
# instead).
RUNBOOK_MUTATION_SCHEMA_V112 = copy.deepcopy(RUNBOOK_SCHEMA_V112)
RUNBOOK_MUTATION_SCHEMA_V112['properties'].pop('traits')

# Schema for trait body on PUT /runbooks/{ident}/traits
RUNBOOK_TRAITS_SCHEMA = {
    'type': 'object',
    'properties': {
        'traits': {
            'type': 'array',
            'items': api_utils.TRAITS_SCHEMA
        },
    },
    'additionalProperties': False,
}

_PATCH_ALLOWED_FIELDS_BASE = [
    'extra',
    'name',
    'owner',
    'public',
    'steps',
]
# 'description' is only patchable in API version >= 1.112.
STEP_PATCH_ALLOWED_FIELDS = ['args', 'interface', 'order', 'step']


def _get_patch_allowed_fields():
    if api_utils.allow_runbook_traits():
        return _PATCH_ALLOWED_FIELDS_BASE + ['description']
    return _PATCH_ALLOWED_FIELDS_BASE


def _get_runbook_schema():
    """Return the appropriate runbook schema for the current API version.

    This is used for creation and mutation, so traits are not allowed
    even in v1.112+ (use /traits sub-resource instead).
    """
    if api_utils.allow_runbook_traits():
        return RUNBOOK_MUTATION_SCHEMA_V112
    return RUNBOOK_SCHEMA


def _get_runbook_validator():
    """Return a validator for the current API version."""
    schema = _get_runbook_schema()
    return args.and_valid(
        args.schema(schema),
        api_utils.duplicate_steps,
        args.dict_valid(uuid=args.uuid)
    )


def convert_with_links(rpc_runbook, fields=None, sanitize=True):
    """Add links to the runbook."""
    base_fields = ['name', 'extra', 'public', 'owner', 'disable_ramdisk']
    if api_utils.allow_runbook_traits():
        base_fields.append('description')
    runbook = api_utils.object_to_dict(
        rpc_runbook,
        fields=tuple(base_fields),
        link_resource='runbooks',
    )
    runbook['steps'] = list(api_utils.convert_steps(rpc_runbook.steps))

    if api_utils.allow_runbook_traits():
        runbook['traits'] = rpc_runbook.traits

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


class RunbookTraitsController(rest.RestController):
    """REST controller for runbook traits."""

    def __init__(self, runbook_ident):
        super(RunbookTraitsController, self).__init__()
        self.runbook_ident = runbook_ident

    @METRICS.timer('RunbookTraitsController.get_all')
    @method.expose()
    def get_all(self):
        """List runbook traits."""
        rpc_runbook = api_utils.check_runbook_policy_and_retrieve(
            'baremetal:runbook:get', self.runbook_ident)
        return {'traits': rpc_runbook.traits}

    @METRICS.timer('RunbookTraitsController.put')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('body')
    @args.validate(trait=args.schema(api_utils.TRAITS_SCHEMA),
                   body=args.schema(RUNBOOK_TRAITS_SCHEMA))
    def put(self, trait=None, body=None):
        """Add a trait to a runbook, or replace all traits.

        :param trait: String value; trait to add to the runbook, or None.
            Mutually exclusive with 'traits'. If not None, adds this
            trait to the runbook.
        :param body: dict with 'traits' key; if provided, replaces all traits.
            Mutually exclusive with 'trait'.
        """
        context = api.request.context
        rpc_runbook = api_utils.check_runbook_policy_and_retrieve(
            'baremetal:runbook:update', self.runbook_ident)

        traits = None
        if body and 'traits' in body:
            traits = body['traits']

        has_single = bool(trait)
        has_list = traits is not None

        if has_single == has_list:
            msg = _("A single runbook trait may be added via PUT "
                    "/v1/runbooks/<runbook identifier>/traits/<trait> with "
                    "no body, or all runbook traits may be replaced via PUT "
                    "/v1/runbooks/<runbook identifier>/traits with the list "
                    "of traits specified in the request body.")
            raise exception.Invalid(msg)

        if trait:
            if api.request.body and api.request.json_body:
                msg = _("No body should be provided when adding a trait")
                raise exception.Invalid(msg)
            new_trait = objects.RunbookTrait(context,
                                             runbook_id=rpc_runbook.id,
                                             trait=trait)
            new_trait.create()
            # Set the HTTP Location Header
            url_args = '/'.join((self.runbook_ident, 'traits', trait))
            api.response.location = link.build_url('runbooks', url_args)
        else:
            objects.RunbookTraitList.create(context, rpc_runbook.id, traits)

    @METRICS.timer('RunbookTraitsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(trait=args.string)
    def delete(self, trait=None):
        """Remove one or all traits from a runbook.

        :param trait: String value; trait to remove from the runbook, or None.
            If None, all traits are removed.
        """
        context = api.request.context
        rpc_runbook = api_utils.check_runbook_policy_and_retrieve(
            'baremetal:runbook:update', self.runbook_ident)

        if trait:
            try:
                objects.RunbookTrait.destroy(
                    context, rpc_runbook.id, trait)
            except exception.RunbookTraitNotFound:
                # Deleting a trait that doesn't exist is a no-op.
                pass
        else:
            objects.RunbookTraitList.destroy(context, rpc_runbook.id)


class RunbooksController(rest.RestController):
    """REST controller for runbooks."""

    invalid_sort_key_list = ['extra', 'steps', 'traits']

    @pecan.expose()
    def _lookup(self, runbook_ident, *remainder):
        if not remainder:
            return
        if remainder[0] == 'traits':
            if not api_utils.allow_runbook_traits():
                msg = _("The API version does not allow runbook traits")
                raise webob_exc.HTTPNotFound(msg)
            return RunbookTraitsController(runbook_ident), remainder[1:]

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
    def post(self, runbook):
        """Create a new runbook.

        :param runbook: a runbook within the request body.
        """
        if not api_utils.allow_runbooks():
            raise exception.NotFound()

        context = api.request.context
        api_utils.check_policy('baremetal:runbook:create')

        # Validate with the appropriate schema for this API version
        validator = _get_runbook_validator()
        validator('runbook', runbook)

        cdict = context.to_policy_values()
        if cdict.get('system_scope') != 'all':
            project_id = None
            requested_owner = runbook.get('owner', None)
            if cdict.get('project_id', False):
                project_id = cdict.get('project_id')

            if requested_owner and requested_owner != project_id:
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

        # Ensure traits and disable_ramdisk are always set so the
        # notification payload can be populated (RunbookCRUDPayload.SCHEMA
        # includes both fields).
        runbook.setdefault('traits', [])
        runbook.setdefault('disable_ramdisk', False)

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

        api_utils.patch_validate_allowed_fields(patch,
                                                _get_patch_allowed_fields())

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

        # Always use the mutation schema (no traits field) so that
        # patch_update_changed_fields does not try to overwrite traits, and
        # so that runbooks with v1.112-style names remain patchable on older
        # API versions (RUNBOOK_SCHEMA validates name against TRAITS_SCHEMA,
        # which would reject stored names that were created via v1.112+).
        # description is blocked for pre-v1.112 by
        # patch_validate_allowed_fields before schema validation runs.
        patch_schema = RUNBOOK_MUTATION_SCHEMA_V112
        for step in runbook.get('steps', []):
            api_utils.patched_validate_with_schema(
                step, api_utils.RUNBOOK_STEP_SCHEMA)
        api_utils.patched_validate_with_schema(
            runbook, patch_schema,
            args.and_valid(
                args.schema(patch_schema),
                api_utils.duplicate_steps,
                args.dict_valid(uuid=args.uuid)
            ))

        api_utils.patch_update_changed_fields(
            runbook, rpc_runbook, fields=objects.Runbook.fields,
            schema=patch_schema
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
