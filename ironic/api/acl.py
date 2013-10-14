# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
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

"""Access Control Lists (ACL's) control access the API server."""

from keystoneclient.middleware import auth_token as keystone_auth_token
from oslo.config import cfg

from ironic.api.middleware import auth_token


OPT_GROUP_NAME = 'keystone_authtoken'


def register_opts(conf):
    """Register keystoneclient middleware options

    :param conf: Ironic settings.
    """
    conf.register_opts(keystone_auth_token.opts, group=OPT_GROUP_NAME)
    keystone_auth_token.CONF = conf


register_opts(cfg.CONF)


def install(app, conf, public_routes):
    """Install ACL check on application.

    :param app: A WSGI applicatin.
    :param conf: Settings. Must include OPT_GROUP_NAME section.
    :param public_routes: The list of the routes which will be allowed to
                          access without authentication.
    :return: The same WSGI application with ACL installed.

    """
    keystone_config = dict(conf.get(OPT_GROUP_NAME))
    return auth_token.AuthTokenMiddleware(app,
                                          conf=keystone_config,
                                          public_api_routes=public_routes)
