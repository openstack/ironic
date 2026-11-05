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

"""
Management and discoverability utility for ironic deployments.
"""

from importlib import metadata
import sys

from oslo_config import cfg

from ironic.common.i18n import _
from ironic.common.inspection_rules import tester
from ironic.common import service
from ironic.conf import CONF
from ironic.drivers import base as driver_base

HARDWARE_TYPES_GROUP = 'ironic.hardware.types'
INTERFACES_GROUP_TEMPLATE = 'ironic.hardware.interfaces.%s'


def _print_entry_point_group(group, config_option, title):
    """Print all entry points registered under an entry point group.

    :param group: name of the entry point group, e.g.
        "ironic.hardware.types".
    :param config_option: name of the [DEFAULT] configuration option the
        entry point names are valid values for.
    :param title: human-readable name for the group of entry points.
    """
    print('%s (for [DEFAULT]%s):' % (title, config_option))

    entry_points = sorted(metadata.entry_points(group=group),
                          key=lambda ep: ep.name)
    if not entry_points:
        print(_('  (no entry points found)'))
        return

    name_width = max(len(ep.name) for ep in entry_points)
    for ep in entry_points:
        try:
            plugin = ep.load()
        except Exception as exc:
            detail = _('(failed to load: %s)') % exc
        else:
            dist = getattr(ep, 'dist', None)
            detail = ep.value
            if dist is not None:
                detail += ' (%s)' % dist.name
            if not getattr(plugin, 'supported', True):
                detail += _(' (deprecated/unsupported)')
        print('  %s  %s' % (ep.name.ljust(name_width), detail))


def _print_interfaces(interface_types):
    """Print the entry points for the requested interface types.

    :param interface_types: list of interface types to display.
    """
    for index, iface_type in enumerate(interface_types):
        if index:
            print()
        _print_entry_point_group(
            INTERFACES_GROUP_TEMPLATE % iface_type,
            'enabled_%s_interfaces' % iface_type,
            '%s interfaces' % iface_type.capitalize())


def _select_interface_types(requested):
    """Validate the requested interface types.

    :param requested: list of interface types requested by the user. An
        empty list requests all interface types.
    :returns: the list of interface types to display.
    """
    unknown = set(requested) - driver_base.ALL_INTERFACES
    if unknown:
        sys.stderr.write(
            _('Unknown interface type(s): %s\n')
            % ', '.join(sorted(unknown)))
        sys.exit(2)
    if not requested:
        return sorted(driver_base.ALL_INTERFACES)
    # Preserve the requested order while removing duplicates.
    return list(dict.fromkeys(requested))


class InspectionRuleCommands(object):

    def check(self):
        node = CONF.command.node_file
        inventory = CONF.command.inventory_file

        if CONF.command.data_dir:
            if node or inventory:
                sys.stderr.write(
                    _('--data-dir cannot be combined with --node or '
                      '--inventory.\n'))
                sys.exit(2)
            sys.exit(tester.run_suite(CONF.command.data_dir,
                                      CONF.command.rules))

        if not (node and inventory):
            sys.stderr.write(
                _('Either --data-dir or both --node and --inventory are '
                  'required.\n'))
            sys.exit(2)
        sys.exit(tester.check_files(node, inventory, CONF.command.rules))


class DriverCommands(object):

    def hardware_types(self):
        _print_entry_point_group(HARDWARE_TYPES_GROUP,
                                 'enabled_hardware_types',
                                 'Hardware types')

    def interfaces(self):
        _print_interfaces(
            _select_interface_types(CONF.command.interface_types))


def add_command_parsers(subparsers):
    driver_commands = DriverCommands()

    parser = subparsers.add_parser(
        'drivers',
        help=_('Discover the driver entry points installed on this '
               'system.'))
    drivers_subparsers = parser.add_subparsers(
        title='Driver commands',
        dest='drivers_command')
    drivers_subparsers.required = True

    parser = drivers_subparsers.add_parser(
        'hardware-types',
        help=_('List the hardware types installed on this system, i.e. '
               'the valid values for the [DEFAULT]enabled_hardware_types '
               'configuration option.'))
    parser.set_defaults(func=driver_commands.hardware_types)

    parser = drivers_subparsers.add_parser(
        'interfaces',
        help=_('List the hardware interfaces installed on this system, '
               'i.e. the valid values for the '
               '[DEFAULT]enabled_<interface type>_interfaces '
               'configuration options. Optionally, pass one or more '
               'interface types (e.g. "deploy") to only list those '
               'types.'))
    parser.add_argument(
        'interface_types', nargs='*', metavar='<interface type>',
        help=_('Interface types to list, one of: %s. If not specified, '
               'all interface types are listed.')
        % ', '.join(sorted(driver_base.ALL_INTERFACES)))
    parser.set_defaults(func=driver_commands.interfaces)

    inspection_rule_commands = InspectionRuleCommands()

    parser = subparsers.add_parser(
        'inspection-rules',
        help=_('Work with inspection rules.'))
    inspection_subparsers = parser.add_subparsers(
        title='Inspection rules commands',
        dest='inspection_rules_command')
    inspection_subparsers.required = True

    parser = inspection_subparsers.add_parser(
        'check',
        help=_('Evaluate inspection rules against captured hardware data '
               'to see which rules match and what actions would be '
               'executed, without touching any real node. Pass either '
               '--node and --inventory for a single set of files, or '
               '--data-dir to run every test case in a directory tree.'))
    parser.add_argument(
        '--rules', required=True, metavar='<rules file>',
        help=_('YAML file with the inspection rules to evaluate.'))
    # NOTE: the dest is explicit because plain "node" and "inventory"
    # clash with configuration groups of the same name, which oslo.config
    # rejects when the sub-command namespace is accessed.
    parser.add_argument(
        '--node', dest='node_file', metavar='<node file>',
        help=_('JSON or YAML file with node data, e.g. from "openstack '
               'baremetal node show <node> -f json". Requires '
               '--inventory.'))
    parser.add_argument(
        '--inventory', dest='inventory_file', metavar='<inventory file>',
        help=_('JSON or YAML file with hardware inventory and plugin '
               'data, e.g. from "openstack baremetal node inventory '
               'save". Requires --node.'))
    parser.add_argument(
        '--data-dir', metavar='<directory>',
        help=_('Directory containing test case subdirectories. Each '
               'subdirectory must contain a node file (node.yaml or '
               'node.json) and an inventory file (inventory.yaml or '
               'inventory.json). Cannot be combined with --node and '
               '--inventory.'))
    parser.set_defaults(func=inspection_rule_commands.check)


def main():
    command_opt = cfg.SubCommandOpt('command',
                                    title='Command',
                                    help=_('Available commands'),
                                    handler=add_command_parsers)

    CONF.register_cli_opt(command_opt)

    service.prepare_command(sys.argv)
    CONF.command.func()


if __name__ == '__main__':
    sys.exit(main())
