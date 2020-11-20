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
from ironic.api.controllers import link


def has_next(collection, limit):
    """Return whether collection has more items."""
    return len(collection) and len(collection) == limit


def list_convert_with_links(items, item_name, limit, url=None, fields=None,
                            sanitize_func=None, key_field='uuid', **kwargs):
    """Build a collection dict including the next link for paging support.

    :param items:
        List of unsanitized items to include in the collection
    :param item_name:
        Name of dict key for items value
    :param limit:
        Paging limit
    :param url:
        Base URL for building next link
    :param fields:
        Optional fields to use for sanitize function
    :param sanitize_func:
        Optional sanitize function run on each item
    :param key_field:
        Key name for building next URL
    :param kwargs:
        other arguments passed to ``get_next``
    :returns:
        A dict containing ``item_name`` and ``next`` values
    """
    items_dict = {
        item_name: items
    }
    next_uuid = get_next(
        items, limit, url=url, fields=fields, key_field=key_field, **kwargs)
    if next_uuid:
        items_dict['next'] = next_uuid

    if sanitize_func:
        for item in items:
            sanitize_func(item, fields=fields)

    return items_dict


def get_next(collection, limit, url=None, key_field='uuid', **kwargs):
    """Return a link to the next subset of the collection."""
    if not has_next(collection, limit):
        return None

    fields = kwargs.pop('fields', None)
    # NOTE(saga): If fields argument is present in kwargs and not None. It
    # is a list so convert it into a comma seperated string.
    if fields:
        kwargs['fields'] = ','.join(fields)
    q_args = ''.join(['%s=%s&' % (key, kwargs[key]) for key in kwargs])

    last_item = collection[-1]
    # handle items which are either objects or dicts
    if hasattr(last_item, key_field):
        marker = getattr(last_item, key_field)
    else:
        marker = last_item.get(key_field)

    next_args = '?%(args)slimit=%(limit)d&marker=%(marker)s' % {
        'args': q_args, 'limit': limit,
        'marker': marker}

    return link.make_link('next', api.request.public_url,
                          url, next_args)['href']
