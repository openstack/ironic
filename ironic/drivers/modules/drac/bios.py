#
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

"""
DRAC Bios specific methods
"""

import re
from xml.etree import ElementTree as ET

from oslo_log import log as logging
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _, _LE, _LW
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import client as wsman_client
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import resource_uris

LOG = logging.getLogger(__name__)


def _val_or_none(item):
    """Test to see if an XML element should be treated as None.

    If the element contains an XML Schema namespaced nil attribute that
    has a value of True, return None.  Otherwise, return whatever the
    text of the element is.

    :param item: an XML element.
    :returns: None or the test of the XML element.
    """

    if item is None:
        return
    itemnil = item.attrib.get('{%s}nil' % resource_uris.CIM_XmlSchema)
    if itemnil == "true":
        return
    else:
        return item.text


def _parse_common(item, ns):
    """Parse common values that all attributes must have.

    :param item: an XML element.
    :param ns: the namespace to search.
    :returns: a dictionary containing the parsed attributes of the element.
    :raises: DracOperationFailed if the given element had no AttributeName
             value.
    """
    searches = {'current_value': './{%s}CurrentValue' % ns,
                'read_only': './{%s}IsReadOnly' % ns,
                'pending_value': './{%s}PendingValue' % ns}
    LOG.debug("Handing %(ns)s for %(xml)s", {
        'ns': ns,
        'xml': ET.tostring(item),
    })
    name = item.findtext('./{%s}AttributeName' % ns)
    if not name:
        raise exception.DracOperationFailed(
            message=_('Item has no name: "%s"') % ET.tostring(item))
    res = {}
    res['name'] = name

    for k in searches:
        if k == 'read_only':
            res[k] = item.findtext(searches[k]) == 'true'
        else:
            res[k] = _val_or_none(item.find(searches[k]))
    return res


def _format_error_msg(invalid_attribs_msgs, read_only_keys):
    """Format a combined error message.

    This method creates a combined error message from a list of error messages
    and a list of read-only keys.

    :param invalid_attribs_msgs: a list of invalid attribute error messages.
    :param read_only_keys: a list of read only keys that were attempted to be
                           written to.
    :returns: a formatted error message.
    """
    msg = '\n'.join(invalid_attribs_msgs)
    if invalid_attribs_msgs and read_only_keys:
        msg += '\n'
    if read_only_keys:
        msg += (_('Cannot set read-only BIOS settings "%r"') % read_only_keys)
    return msg


def parse_enumeration(item, ns):
    """Parse an attribute that has a set of distinct values.

    :param item: an XML element.
    :param ns: the namespace to search.
    :returns: a dictionary containing the parsed attributes of the element.
    :raises: DracOperationFailed if the given element had no AttributeName
             value.
    """
    res = _parse_common(item, ns)
    res['possible_values'] = sorted(
        [v.text for v in item.findall('./{%s}PossibleValues' % ns)])

    return res


def parse_string(item, ns):
    """Parse an attribute that should be a freeform string.

    :param item: an XML element.
    :param ns: the namespace to search.
    :returns: a dictionary containing the parsed attributes of the element.
    :raises: DracOperationFailed if the given element had no AttributeName
             value.
    """
    res = _parse_common(item, ns)
    searches = {'min_length': './{%s}MinLength' % ns,
                'max_length': './{%s}MaxLength' % ns,
                'pcre_regex': './{%s}ValueExpression' % ns}
    for k in searches:
        if k == 'pcre_regex':
            res[k] = _val_or_none(item.find(searches[k]))
        else:
            res[k] = int(item.findtext(searches[k]))

    # Workaround for a BIOS bug in one of the 13 gen boxes
    badval = re.compile(r"MAX_ASSET_TAG_LEN")
    if (res['pcre_regex'] is not None and
        res['name'] == 'AssetTag' and
        badval.search(res['pcre_regex'])):
        res['pcre_regex'] = badval.sub("%d" % res['max_length'],
                                       res['pcre_regex'])
    return res


def parse_integer(item, ns):
    """Parse an attribute that should be an integer.

    :param item: an XML element.
    :param ns: the namespace to search.
    :returns: a dictionary containing the parsed attributes of the element.
    :raises: DracOperationFailed if the given element had no AttributeName
             value.
    """
    res = _parse_common(item, ns)
    for k in ['current_value', 'pending_value']:
        if res[k]:
            res[k] = int(res[k])
    searches = {'lower_bound': './{%s}LowerBound' % ns,
                'upper_bound': './{%s}UpperBound' % ns}
    for k in searches:
        res[k] = int(item.findtext(searches[k]))

    return res


def _get_config(node, resource):
    """Helper for get_config.

    Handles getting BIOS config values for a single namespace

    :param node: an ironic node object.
    :param resource: the namespace.
    :returns: a dictionary that maps the name of each attribute to a dictionary
              of values of that attribute.
    :raises: InvalidParameterValue if some information required to connnect
             to the DRAC is missing on the node or the value of one or more
             required parameters is invalid.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracOperationFailed if the specified resource is unknown.
    """
    res = {}
    client = wsman_client.get_wsman_client(node)
    try:
        doc = client.wsman_enumerate(resource)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to get BIOS settings '
                          'for resource %(resource)s '
                          'from node %(node_uuid)s. '
                          'Reason: %(error)s.'),
                      {'node_uuid': node.uuid,
                       'resource': resource,
                       'error': exc})
    items = doc.find('.//{%s}Items' % resource_uris.CIM_WSMAN)
    for item in items:
        if resource == resource_uris.DCIM_BIOSEnumeration:
            attribute = parse_enumeration(item, resource)
        elif resource == resource_uris.DCIM_BIOSString:
            attribute = parse_string(item, resource)
        elif resource == resource_uris.DCIM_BIOSInteger:
            attribute = parse_integer(item, resource)
        else:
            raise exception.DracOperationFailed(
                message=_('Unknown namespace %(ns)s for item: "%(item)s"') % {
                    'item': ET.tostring(item), 'ns': resource})
        res[attribute['name']] = attribute
    return res


def get_config(node):
    """Get the BIOS configuration from a Dell server using WSMAN

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman.
    :raises: DracOperationFailed when a BIOS setting cannot be parsed.
    :returns: a dictionary containing BIOS settings in the form of:
        {'EnumAttrib': {'name': 'EnumAttrib',
                        'current_value': 'Value',
                        'pending_value': 'New Value', # could also be None
                        'read_only': False,
                        'possible_values': ['Value', 'New Value', 'None']},
         'StringAttrib': {'name': 'StringAttrib',
                          'current_value': 'Information',
                          'pending_value': None,
                          'read_only': False,
                          'min_length': 0,
                          'max_length': 255,
                          'pcre_regex': '^[0-9A-Za-z]{0,255}$'},
         'IntegerAttrib': {'name': 'IntegerAttrib',
                           'current_value': 0,
                           'pending_value': None,
                           'read_only': True,
                           'lower_bound': 0,
                           'upper_bound': 65535}
        }

    The above values are only examples, of course.  BIOS attributes exposed via
    this API will always be either an enumerated attribute, a string attribute,
    or an integer attribute.  All attributes have the following parameters:
    :name: is the name of the BIOS attribute.
    :current_value: is the current value of the attribute.
                    It will always be either an integer or a string.
    :pending_value: is the new value that we want the attribute to have.
                    None means that there is no pending value.
    :read_only: indicates whether this attribute can be changed.  Trying to
                change a read-only value will result in an error.
                The read-only flag can change depending on other attributes.
                A future version of this call may expose the dependencies
                that indicate when that may happen.

    Enumerable attributes also have the following parameters:
    :possible_values: is an array of values it is permissible to set
                      the attribute to.

    String attributes also have the following parameters:
    :min_length: is the minimum length of the string.
    :max_length: is the maximum length of the string.
    :pcre_regex: is a PCRE compatible regular expression that the string
                 must match.  It may be None if the string is read only
                 or if the string does not have to match any particular
                 regular expression.

    Integer attributes also have the following parameters:
    :lower_bound: is the minimum value the attribute can have.
    :upper_bound: is the maximum value the attribute can have.

    """
    res = {}
    for ns in [resource_uris.DCIM_BIOSEnumeration,
               resource_uris.DCIM_BIOSString,
               resource_uris.DCIM_BIOSInteger]:
        attribs = _get_config(node, ns)
        if not set(res).isdisjoint(set(attribs)):
            raise exception.DracOperationFailed(
                message=_('Colliding attributes %r') % (
                    set(res) & set(attribs)))
        res.update(attribs)
    return res


@task_manager.require_exclusive_lock
def set_config(task, **kwargs):
    """Sets the pending_value parameter for each of the values passed in.

    :param task: an ironic task object.
    :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
    :raises: DracOperationFailed if any new values are invalid.
    :raises: DracOperationFailed if any of the attributes are read-only.
    :raises: DracOperationFailed if any of the attributes cannot be set for
             any other reason.
    :raises: DracClientError on an error from the pywsman library.
    :returns: A boolean indicating whether commit_config needs to be
              called to make the changes.

    """
    node = task.node
    management.check_for_config_job(node)
    current = get_config(node)
    unknown_keys = set(kwargs) - set(current)
    if unknown_keys:
        LOG.warning(_LW('Ignoring unknown BIOS attributes "%r"'),
                    unknown_keys)

    candidates = set(kwargs) - unknown_keys
    read_only_keys = []
    unchanged_attribs = []
    invalid_attribs_msgs = []
    attrib_names = []

    for k in candidates:
        if str(kwargs[k]) == str(current[k]['current_value']):
            unchanged_attribs.append(k)
        elif current[k]['read_only']:
            read_only_keys.append(k)
        else:
            if 'possible_values' in current[k]:
                if str(kwargs[k]) not in current[k]['possible_values']:
                    m = _('Attribute %(attr)s cannot be set to value %(val)s.'
                          ' It must be in %(ok)r') % {
                              'attr': k,
                              'val': kwargs[k],
                              'ok': current[k]['possible_values']}
                    invalid_attribs_msgs.append(m)
                    continue
            if ('pcre_regex' in current[k] and
                current[k]['pcre_regex'] is not None):
                regex = re.compile(current[k]['pcre_regex'])
                if regex.search(str(kwargs[k])) is None:
                    # TODO(victor-lowther)
                    # Leave untranslated for now until the unicode
                    # issues that the test suite exposes are straightened out.
                    m = ('Attribute %(attr)s cannot be set to value %(val)s.'
                         ' It must match regex %(re)s.') % {
                             'attr': k,
                             'val': kwargs[k],
                             're': current[k]['pcre_regex']}
                    invalid_attribs_msgs.append(m)
                    continue
            if 'lower_bound' in current[k]:
                lower = current[k]['lower_bound']
                upper = current[k]['upper_bound']
                val = int(kwargs[k])
                if val < lower or val > upper:
                    m = _('Attribute %(attr)s cannot be set to value %(val)d.'
                          ' It must be between %(lower)d and %(upper)d.') % {
                              'attr': k,
                              'val': val,
                              'lower': lower,
                              'upper': upper}
                    invalid_attribs_msgs.append(m)
                    continue
            attrib_names.append(k)

    if unchanged_attribs:
        LOG.warning(_LW('Ignoring unchanged BIOS settings %r'),
                    unchanged_attribs)

    if invalid_attribs_msgs or read_only_keys:
        raise exception.DracOperationFailed(
            _format_error_msg(invalid_attribs_msgs, read_only_keys))

    if not attrib_names:
        return False

    client = wsman_client.get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': 'BIOS.Setup.1-1',
                  'AttributeName': attrib_names,
                  'AttributeValue': map(lambda k: kwargs[k], attrib_names)}
    doc = client.wsman_invoke(resource_uris.DCIM_BIOSService,
                              'SetAttributes',
                              selectors,
                              properties)
    # Yes, we look for RebootRequired.  In this context, that actually means
    # that we need to create a lifecycle controller config job and then reboot
    # so that the lifecycle controller can commit the BIOS config changes that
    # we have proposed.
    set_results = doc.findall(
        './/{%s}RebootRequired' % resource_uris.DCIM_BIOSService)
    return any(str(res.text) == 'Yes' for res in set_results)


@task_manager.require_exclusive_lock
def commit_config(task, reboot=False):
    """Commits pending changes added by set_config

    :param task: is the ironic task for running the config job.
    :param reboot: indicates whether a reboot job should be automatically
                   created with the config job.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracPendingConfigJobExists if the job is already created.
    :raises: DracOperationFailed if the client received response with an
             error message.
    :raises: DracUnexpectedReturnValue if the client received a response
             with unexpected return value

    """
    node = task.node
    management.check_for_config_job(node)
    management.create_config_job(node, reboot)


@task_manager.require_exclusive_lock
def abandon_config(task):
    """Abandons uncommitted changes added by set_config

    :param task: is the ironic task for abandoning the changes.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracOperationFailed on error reported back by DRAC.
    :raises: DracUnexpectedReturnValue if the drac did not report success.

    """
    node = task.node
    client = wsman_client.get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': 'BIOS.Setup.1-1'}

    client.wsman_invoke(resource_uris.DCIM_BIOSService,
                        'DeletePendingConfiguration',
                        selectors,
                        properties,
                        wsman_client.RET_SUCCESS)
