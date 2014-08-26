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

from xml.etree import ElementTree


def build_soap_xml(items, namespace=None):
    """Build a SOAP XML.

    :param items: a dictionary where key is the element name and the
                  value is the element text.
    :param namespace: the namespace for the elements, None for no
                      namespace. Defaults to None
    :returns: a XML string.

    """
    soap_namespace = "http://www.w3.org/2003/05/soap-envelope"
    envelope_element = ElementTree.Element("{%s}Envelope" % soap_namespace)
    body_element = ElementTree.Element("{%s}Body" % soap_namespace)

    for i in items:
        xml_string = i
        if namespace:
            xml_string = "{%(namespace)s}%(item)s" % {'namespace': namespace,
                                                      'item': xml_string}

        element = ElementTree.Element(xml_string)
        element.text = items[i]
        body_element.append(element)

    envelope_element.append(body_element)
    return ElementTree.tostring(envelope_element)
