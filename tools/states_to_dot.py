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


def map_color(text):
    # If the text contains 'error'/'fail' then we'll return red...
    if 'error' in text or 'fail' in text:
        return 'red'
    else:
        return None


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
        attrs = {}
        text_color = map_color(state)
        if text_color:
            attrs['fontcolor'] = text_color
        return attrs

    def edge_attrs(start_state, event, end_state):
        attrs = {}
        if options.labels:
            attrs['label'] = "on_%s" % event
            edge_color = map_color(event)
            if edge_color:
                attrs['fontcolor'] = edge_color
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
