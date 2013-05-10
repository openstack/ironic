# -*- encoding: utf-8 -*-
#
# Copyright © 2013 New Dream Network, LLC (DreamHost)
#
# Author: Doug Hellmann <doug.hellmann@dreamhost.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
Model classes for use in the storage API.
"""


class Model(object):
    """Base class for storage API models.
    """

    def __init__(self, **kwds):
        self.fields = list(kwds)
        for k, v in kwds.iteritems():
            setattr(self, k, v)

    def as_dict(self):
        d = {}
        for f in self.fields:
            v = getattr(self, f)
            if isinstance(v, Model):
                v = v.as_dict()
            elif isinstance(v, list) and v and isinstance(v[0], Model):
                v = [sub.as_dict() for sub in v]
            d[f] = v
        return d

    def __eq__(self, other):
        return self.as_dict() == other.as_dict()


class Node(Model):
    """Representation of a bare metal node."""

    def __init__(self, uuid, power_info, task_state, image_path,
                    instance_uuid, instance_name, extra):
        Model.__init__(uuid=uuid,
                       power_info=power_info,
                       task_state=task_state,
                       image_path=image_path,
                       instance_uuid=instance_uuid,
                       instance_name=instance_name,
                       extra=extra,
                       )


class Iface(Model):
    """Representation of a NIC."""

    def __init__(self, mac, node_id, extra):
        Model.__init__(mac=mac,
                       node_id=node_id,
                       extra=extra,
                       )
