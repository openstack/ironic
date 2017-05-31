# Copyright (c) 2011 Citrix Systems, Inc.
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

from glanceclient import exc as glance_exc


NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"


class StubGlanceClient(object):

    def __init__(self, images=None):
        self._images = []
        _images = images or []
        map(lambda image: self.create(**image), _images)

        # NOTE(bcwaldon): HACK to get client.images.* to work
        self.images = lambda: None
        for fn in ('get', 'data'):
            setattr(self.images, fn, getattr(self, fn))

    def get(self, image_id):
        for image in self._images:
            if image.id == str(image_id):
                return image
        raise glance_exc.NotFound(image_id)

    def data(self, image_id):
        self.get(image_id)
        return []


class FakeImage(object):
    def __init__(self, metadata):
        IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                            'container_format', 'checksum', 'id',
                            'name',
                            'deleted', 'status',
                            'min_disk', 'min_ram', 'is_public']
        raw = dict.fromkeys(IMAGE_ATTRIBUTES)
        raw.update(metadata)
        # raw['created_at'] = NOW_GLANCE_FORMAT
        # raw['updated_at'] = NOW_GLANCE_FORMAT
        self.__dict__['raw'] = raw

    def __getattr__(self, key):
        try:
            return self.__dict__['raw'][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        try:
            self.__dict__['raw'][key] = value
        except KeyError:
            raise AttributeError(key)
