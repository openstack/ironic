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

top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir))
sys.path.insert(0, top_dir)

# To get this installed you may have to follow:
# https://code.google.com/p/pydot/issues/detail?id=93 (until fixed).
import pydot

from ironic.common import states


def print_header(text):
    print("*" * len(text))
    print(text)
    print("*" * len(text))


def map_color(text):
    # If the text contains 'error' then we'll return red...
    if 'error' in text:
        return 'red'
    else:
        return None


def format_state(state):
    # Changes a state (mainly NOSTATE which is the None object) into
    # a nicer string...
    if state == states.NOSTATE:
        state = 'no-state'
    return state


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

    source = states.machine
    graph_name = "Ironic states"
    g = pydot.Dot(graph_name=graph_name, rankdir='LR',
                  nodesep='0.25', overlap='false',
                  ranksep="0.5", size="11x8.5",
                  splines='true', ordering='in')
    node_attrs = {
        'fontsize': '11',
    }
    nodes = {}
    for (start_state, on_event, end_state) in source:
        start_state = format_state(start_state)
        end_state = format_state(end_state)
        if start_state not in nodes:
            start_node_attrs = node_attrs.copy()
            text_color = map_color(start_state)
            if text_color:
                start_node_attrs['fontcolor'] = text_color
            nodes[start_state] = pydot.Node(start_state, **start_node_attrs)
            g.add_node(nodes[start_state])
        if end_state not in nodes:
            end_node_attrs = node_attrs.copy()
            text_color = map_color(end_state)
            if text_color:
                end_node_attrs['fontcolor'] = text_color
            nodes[end_state] = pydot.Node(end_state, **end_node_attrs)
            g.add_node(nodes[end_state])
        edge_attrs = {}
        if options.labels:
            edge_attrs['label'] = "on_%s" % on_event
            edge_color = map_color(on_event)
            if edge_color:
                edge_attrs['fontcolor'] = edge_color
        g.add_edge(pydot.Edge(nodes[start_state], nodes[end_state],
                              **edge_attrs))

    # Make nice start states...
    starts = [
        format_state(source.start_state),
    ]
    for i, s in enumerate(starts):
        name = "__start_%s__" % i
        start = pydot.Node(name, shape="point", width="0.1",
                           xlabel='start', fontcolor='green', **node_attrs)
        g.add_node(start)
        g.add_edge(pydot.Edge(start, nodes[s], style='dotted'))

    print_header(graph_name)
    print(g.to_string().strip())

    g.write(options.filename, format=options.format)
    print_header("Created %s at '%s'" % (options.format, options.filename))

    # To make the svg more pretty use the following:
    # $ xsltproc ../diagram-tools/notugly.xsl ./states.svg > pretty-states.svg
    # Get diagram-tools from https://github.com/vidarh/diagram-tools.git


if __name__ == '__main__':
    main()
