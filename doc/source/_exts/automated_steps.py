# All Rights Reserved.
#
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

from collections import defaultdict
import inspect
import itertools
import operator
import os.path

from docutils import nodes
from docutils.parsers import rst
from docutils.parsers.rst import directives
from docutils.statemachine import ViewList
from sphinx.util import logging
from sphinx.util.nodes import nested_parse_with_titles
import stevedore

from ironic.common import driver_factory

LOG = logging.getLogger(__name__)

# Enable this locally if you need debugging output
DEBUG = False

def _list_table(add, headers, data, title='', columns=None):
    """Build a list-table directive.

    :param add: Function to add one row to output.
    :param headers: List of header values.
    :param data: Iterable of row data, yielding lists or tuples with rows.
    """
    add('.. list-table:: %s' % title)
    add('   :header-rows: 1')
    if columns:
        add('   :widths: %s' % (','.join(str(c) for c in columns)))
    add('')
    add('   - * %s' % headers[0])
    for h in headers[1:]:
        add('     * %s' % h)
    for row in data:
        add('   - * %s' % row[0])
        for r in row[1:]:
            lines = str(r).splitlines()
            if not lines:
                # empty string
                add('     * ')
            else:
                # potentially multi-line string
                add('     * %s' % lines[0])
                for l in lines[1:]:
                    add('       %s' % l)
    add('')


def _format_doc(doc):
    "Format one method docstring to be shown in the step table."
    paras = doc.split('\n\n')
    if paras[-1].startswith(':'):
        # Remove the field table that commonly appears at the end of a
        # docstring.
        paras = paras[:-1]
    return '\n\n'.join(paras)


_clean_steps = {}


def _init_steps_by_driver():
    "Load step information from drivers."

    # NOTE(dhellmann): This reproduces some of the logic of
    # ironic.drivers.base.BaseInterface.__new__ and
    # ironic.common.driver_factory but does so without
    # instantiating the interface classes, which means that if
    # some of the preconditions aren't met we can still inspect
    # the methods of the class.

    for interface_name in sorted(driver_factory.driver_base.ALL_INTERFACES):
        if DEBUG:
            LOG.info('[{}] probing available plugins for interface {}'.format(
                __name__, interface_name))

        loader = stevedore.ExtensionManager(
            'ironic.hardware.interfaces.{}'.format(interface_name),
            invoke_on_load=False,
        )

        for plugin in loader:
            if plugin.name == 'fake':
                continue

            steps = []

            for method_name, method in inspect.getmembers(plugin.plugin):
                if not getattr(method, '_is_clean_step', False):
                    continue
                step = {
                    'step': method.__name__,
                    'priority': method._clean_step_priority,
                    'abortable': method._clean_step_abortable,
                    'argsinfo': method._clean_step_argsinfo,
                    'interface': interface_name,
                    'doc': _format_doc(inspect.getdoc(method)),
                }
                if DEBUG:
                    LOG.info('[{}] interface {!r} driver {!r} STEP {}'.format(
                        __name__, interface_name, plugin.name, step))
                steps.append(step)

            if steps:
                if interface_name not in _clean_steps:
                    _clean_steps[interface_name] = {}
                _clean_steps[interface_name][plugin.name] = steps


def _format_args(argsinfo):
    argsinfo = argsinfo or {}
    return '\n\n'.join(
        '``{}``{}{} {}'.format(
            argname,
            ' (*required*)' if argdetail.get('required') else '',
            ' --' if argdetail.get('description') else '',
            argdetail.get('description', ''),
        )
        for argname, argdetail in sorted(argsinfo.items())
    )


class AutomatedStepsDirective(rst.Directive):

    option_spec = {
        'phase': directives.unchanged,
    }

    def run(self):
        series = self.options.get('series', 'cleaning')

        if series != 'cleaning':
            raise NotImplementedError('Showing deploy steps not implemented')

        source_name = '<{}>'.format(__name__)

        result = ViewList()

        for interface_name in ['power', 'management', 'deploy', 'bios', 'raid']:
            interface_info = _clean_steps.get(interface_name, {})
            if not interface_info:
                continue

            title = '{} Interface'.format(interface_name.capitalize())
            result.append(title, source_name)
            result.append('~' * len(title), source_name)

            for driver_name, steps in sorted(interface_info.items()):

                _list_table(
                    title='{} cleaning steps'.format(driver_name),
                    add=lambda x: result.append(x, source_name),
                    headers=['Name', 'Details', 'Priority', 'Stoppable', 'Arguments'],
                    columns=[20, 30, 10, 10, 30],
                    data=(
                        ('``{}``'.format(s['step']),
                         s['doc'],
                         s['priority'],
                         'yes' if s['abortable'] else 'no',
                         _format_args(s['argsinfo']),
                         )
                        for s in steps
                    ),
                )

        # NOTE(dhellmann): Useful for debugging.
        # print('\n'.join(result))

        node = nodes.section()
        node.document = self.state.document
        nested_parse_with_titles(self.state, result, node)
        return node.children


def setup(app):
    app.add_directive('show-steps', AutomatedStepsDirective)
    _init_steps_by_driver()
