# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
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

from xml import etree

import mock


def build_soap_xml(items, namespace=None):
    """Build a SOAP XML.

    :param items: a list of dictionaries where key is the element name
                  and the value is the element text.
    :param namespace: the namespace for the elements, None for no
                      namespace. Defaults to None
    :returns: a XML string.

    """

    def _create_element(name, value=None):
        xml_string = name
        if namespace:
            xml_string = "{%(namespace)s}%(item)s" % {'namespace': namespace,
                                                      'item': xml_string}

        element = etree.ElementTree.Element(xml_string)
        element.text = value
        return element

    soap_namespace = "http://www.w3.org/2003/05/soap-envelope"
    envelope_element = etree.ElementTree.Element(
        "{%s}Envelope" % soap_namespace)
    body_element = etree.ElementTree.Element("{%s}Body" % soap_namespace)

    for item in items:
        for i in item:
            insertion_point = _create_element(i)
            if isinstance(item[i], dict):
                for j, value in item[i].items():
                    insertion_point.append(_create_element(j, value))
            else:
                insertion_point.text = item[i]

            body_element.append(insertion_point)

    envelope_element.append(body_element)
    return etree.ElementTree.tostring(envelope_element)


def mock_wsman_root(return_value):
    """Helper function to mock the root() from wsman client."""
    mock_xml_root = mock.Mock(spec_set=['string'])
    mock_xml_root.string.return_value = return_value

    mock_xml = mock.Mock(spec_set=['context', 'root'])
    mock_xml.context.return_value = None
    mock_xml.root.return_value = mock_xml_root

    return mock_xml
