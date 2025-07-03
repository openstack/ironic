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

from ironic.common import metrics_utils
from oslo_log import log
from oslo_utils import uuidutils
from pecan import rest
from webob import exc as webob_exc

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api import method
from ironic.api import validation
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import validation as ir_validation
import ironic.conf
from ironic import objects


CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_RETURN_FIELDS = ['uuid', 'priority', 'phase', 'description']


def convert_actions(rpc_actions):
    converted_actions = []
    for action in rpc_actions:
        result = {
            'op': action['op'],
            'args': action['args']
        }

        if action.get('loop', []):
            result['loop'] = action['loop']

        converted_actions.append(result)
    return converted_actions


def convert_conditions(rpc_conditions):
    converted_conditions = []
    for condition in rpc_conditions:
        result = {
            'op': condition['op'],
            'args': condition['args']
        }

        if condition.get('loop', []):
            result['loop'] = condition['loop']
            result['multiple'] = condition.get('multiple', 'any')

        converted_conditions.append(result)
    return converted_conditions


def rules_sanitize(inspection_rule, fields):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter.

    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    """
    if inspection_rule.get('sensitive'):
        inspection_rule['conditions'] = None
        inspection_rule['actions'] = None
    api_utils.sanitize_dict(inspection_rule, fields)


def convert_with_links(rpc_rule, fields=None, sanitize=True):
    """Add links to the inspection rule."""
    inspection_rule = api_utils.object_to_dict(
        rpc_rule,
        fields=('description', 'priority', 'sensitive', 'phase', 'conditions',
                'actions'),
        link_resource='inspection',
    )

    inspection_rule['actions'] = convert_actions(rpc_rule.actions)
    inspection_rule['conditions'] = convert_conditions(rpc_rule.conditions)

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, inspection_rule)

    if sanitize:
        rules_sanitize(inspection_rule, fields)

    return inspection_rule


def list_convert_with_links(rpc_rules, limit, fields=None, **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(t, fields=fields, sanitize=False)
               for t in rpc_rules],
        item_name='inspection_rules',
        url='inspection',
        limit=limit,
        fields=fields,
        sanitize_func=rules_sanitize,
        **kwargs
    )


class InspectionRuleController(rest.RestController):
    """REST controller for inspection rules."""

    invalid_sort_key_list = ['actions', 'conditions']

    @METRICS.timer('InspectionRuleController.get_all')
    @method.expose()
    @validation.api_version(
        min_version=versions.MINOR_96_INSPECTION_RULES,
        message=_('The API version does not allow inspection rules'),
    )
    @args.validate(marker=args.name, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc',
                fields=None, detail=None, phase=None):
        """Retrieve a list of inspection rules.

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
                       of inspection rules with detail.
        """
        api_utils.check_policy('baremetal:inspection_rule:get')
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
            marker_obj = objects.InspectionRule.get_by_uuid(
                api.request.context, marker)

        rules = objects.InspectionRule.list(
            api.request.context, limit=limit, marker=marker_obj,
            sort_key=sort_key, sort_dir=sort_dir)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}

        if detail is not None:
            parameters['detail'] = detail

        filters = {}
        if phase:
            filters['phase'] = phase

        return list_convert_with_links(
            rules, limit, fields=fields, filters=filters, **parameters)

    @METRICS.timer('InspectionRuleController.get_one')
    @method.expose()
    @validation.api_version(
        min_version=versions.MINOR_96_INSPECTION_RULES,
        message=_('The API version does not allow inspection rules'),
    )
    @args.validate(inspection_rule_uuid=args.uuid, fields=args.string_list)
    def get_one(self, inspection_rule_uuid, fields=None):
        """Retrieve information about the given inspection rule.

        :param inspection_rule_uuid: UUID of an inspection rule.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        api_utils.check_policy('baremetal:inspection_rule:get')
        inspection_rule = objects.InspectionRule.get_by_uuid(
            api.request.context, inspection_rule_uuid)

        api_utils.check_allowed_fields(fields)
        return convert_with_links(inspection_rule, fields=fields)

    @METRICS.timer('InspectionRuleController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('inspection_rule')
    @validation.api_version(
        min_version=versions.MINOR_96_INSPECTION_RULES,
        message=_('The API version does not allow inspection rules'),
        exception_class=webob_exc.HTTPMethodNotAllowed,
    )
    @args.validate(inspection_rule=ir_validation.VALIDATOR)
    def post(self, inspection_rule):
        """Create a new inspection rule.

        :param inspection_rule: a inspection rule within the request body.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:inspection_rule:create')
        ir_validation.validate_rule(inspection_rule)

        if not inspection_rule.get('uuid'):
            inspection_rule['uuid'] = uuidutils.generate_uuid()
        new_rule = objects.InspectionRule(context, **inspection_rule)

        notify.emit_start_notification(context, new_rule, 'create')
        with notify.handle_error_notification(context, new_rule, 'create'):
            new_rule.create()

        api.response.location = link.build_url('inspection_rules',
                                               new_rule.uuid)
        api_rule = convert_with_links(new_rule)
        notify.emit_end_notification(context, new_rule, 'create')
        return api_rule

    @METRICS.timer('InspectionRuleController.patch')
    @method.expose()
    @method.body('patch')
    @validation.api_version(
        min_version=versions.MINOR_96_INSPECTION_RULES,
        message=_('The API version does not allow inspection rules'),
        exception_class=webob_exc.HTTPMethodNotAllowed,
    )
    @args.validate(inspection_rule_uuid=args.uuid, patch=args.patch)
    def patch(self, inspection_rule_uuid, patch=None):
        """Update an existing inspection rule.

        :param inspection_rule_uuid: UUID of the rule to update.
        :param patch: a json PATCH document to apply to this inspection rule.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:inspection_rule:update')

        rpc_rule = objects.InspectionRule.get_by_uuid(context,
                                                      inspection_rule_uuid)
        rule = rpc_rule.as_dict()

        sensitive_patch = api_utils.get_patch_values(patch, '/sensitive')
        sensitive = sensitive_patch[0] if sensitive_patch else None
        if (not sensitive) and sensitive is not None:
            if rpc_rule['sensitive']:
                msg = _("Inspection rules cannot have "
                        "the sensitive flag unset.")
                raise exception.PatchError(patch=patch, reason=msg)

        rule = api_utils.apply_jsonpatch(rule, patch)

        api_utils.patched_validate_with_schema(
            rule, ir_validation.SCHEMA,
            ir_validation.VALIDATOR)

        ir_validation.validate_rule(rule)

        api_utils.patch_update_changed_fields(
            rule, rpc_rule, fields=objects.InspectionRule.fields,
            schema=ir_validation.SCHEMA
        )

        notify.emit_start_notification(context, rpc_rule, 'update')
        with notify.handle_error_notification(context, rpc_rule, 'update'):
            rpc_rule.save()

        api_rule = convert_with_links(rpc_rule)
        notify.emit_end_notification(context, rpc_rule, 'update')

        return api_rule

    @METRICS.timer('InspectionRuleController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @validation.api_version(
        min_version=versions.MINOR_96_INSPECTION_RULES,
        message=_('The API version does not allow inspection rules'),
        exception_class=webob_exc.HTTPMethodNotAllowed,
    )
    @args.validate(inspection_rule_uuid=args.uuid)
    def delete(self, inspection_rule_uuid):
        """Delete an inspection rule.

        :param inspection_rule_uuid: UUID of an inspection rule.
        :param confirm: Confirmation string. Must be 'true' for bulk deletion.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:inspection_rule:delete')
        inspection_rule = objects.InspectionRule.get_by_uuid(
            context, inspection_rule_uuid)
        notify.emit_start_notification(context, inspection_rule, 'delete')
        with notify.handle_error_notification(context, inspection_rule,
                                              'delete'):
            inspection_rule.destroy()
        notify.emit_end_notification(context, inspection_rule, 'delete')
