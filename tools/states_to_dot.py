#!/usr/bin/env python

#    Copyright (C) 2014 Yahoo! Inc. All Rights Reserved.
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

import optparse
import os
import sys

from automaton.converters import pydot

from ironic.common import states

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir))
sys.path.insert(0, top_dir)


def print_header(text):
    print("*" * len(text))
    print(text)
    print("*" * len(text))


def map_color(text, key='fontcolor'):
    """Map the text to a color.

    The text is mapped to a color.

    :param text: string of text to be mapped to a color. 'error' and
                 'fail' in the text will map to 'red'.
    :param key: in returned dictionary, the key to use that corresponds to
                the color
    :returns: A dictionary with one entry, key = color. If no color is
              associated with the text, an empty dictionary.
    """

    # If the text contains 'error'/'fail' then we'll return red...
    if 'error' in text or 'fail' in text:
        return {key: 'red'}
    else:
        return {}


def main():
    parser = optparse.OptionParser()
    parser.add_option("-f", "--file", dest="filename",
                      help="write output to FILE", metavar="FILE")
    parser.add_option("-T", "--format", dest="format",
                      help="output in given format (default: png)",
                      default='png')
    parser.add_option("--no-labels", dest="labels",
                      help="do not include labels",
                      action='store_false', default=True)
    (options, args) = parser.parse_args()
    if options.filename is None:
        options.filename = 'states.%s' % options.format

    def node_attrs(state):
        """Attributes used for drawing the nodes (states).

        The user can perform actions on stable states (and in a few other
        cases), so we distinguish the stable states from the other states by
        highlighting the node. Non-stable states are labelled with gray.

        This is a callback method used by pydot.convert().

        :param state: name of state
        :returns: A dictionary with graphic attributes used for displaying
                  the state.
        """
        attrs = map_color(state)
        if source.is_stable(state):
            attrs['penwidth'] = 1.7
        else:
            if 'fontcolor' not in attrs:
                attrs['fontcolor'] = 'gray'
        return attrs

    def edge_attrs(start_state, event, end_state):
        """Attributes used for drawing the edges (transitions).

        There are two types of transitions; the ones that the user can
        initiate and the ones that are done internally by the conductor.
        The user-initiated ones are shown with '(via API'); the others are
        in gray.

        This is a callback method used by pydot.convert().

        :param start_state: name of the start state
        :param event: the event, a string
        :param end_state: name of the end state (unused)
        :returns: A dictionary with graphic attributes used for displaying
                  the transition.
        """
        if not options.labels:
            return {}

        translations = {'delete': 'deleted', 'deploy': 'active'}
        attrs = {}
        attrs['fontsize'] = 12
        attrs['label'] = translations.get(event, event)
        if (source.is_stable(start_state) or 'fail' in start_state
            or event in ('abort', 'delete')):
            attrs['label'] += " (via API)"
        else:
            attrs['fontcolor'] = 'gray'
        return attrs

    source = states.machine
    graph_name = '"Ironic states"'
    graph_attrs = {'size': 0}
    g = pydot.convert(source, graph_name, graph_attrs=graph_attrs,
                      node_attrs_cb=node_attrs, edge_attrs_cb=edge_attrs)

    print_header(graph_name)
    print(g.to_string().strip())

    g.write(options.filename, format=options.format)
    print_header("Created %s at '%s'" % (options.format, options.filename))


if __name__ == '__main__':
    main()
