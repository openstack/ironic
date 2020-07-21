# Copyright 2013 Red Hat, Inc.
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

from ironic import api


def build_url(resource, resource_args, bookmark=False, base_url=None):
    if base_url is None:
        base_url = api.request.public_url

    template = '%(url)s/%(res)s' if bookmark else '%(url)s/v1/%(res)s'
    # FIXME(lucasagomes): I'm getting a 404 when doing a GET on
    # a nested resource that the URL ends with a  '/'.
    # https://groups.google.com/forum/#!topic/pecan-dev/QfSeviLg5qs
    template += '%(args)s' if resource_args.startswith('?') else '/%(args)s'
    return template % {'url': base_url, 'res': resource, 'args': resource_args}


def make_link(rel_name, url, resource, resource_args,
              bookmark=False, type=None):
    """Build a dict representing a link"""
    href = build_url(resource, resource_args,
                     bookmark=bookmark, base_url=url)
    l = {
        'href': href,
        'rel': rel_name
    }
    if type:
        l['type'] = type
    return l
