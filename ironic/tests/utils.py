# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack Foundation
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

"""Common utilities used in testing"""

import os
import tempfile

import fixtures
from oslo.config import cfg
import testtools

from ironic.openstack.common.fixture import moxstubout


class BaseTestCase(testtools.TestCase):

    def setUp(self, conf=cfg.CONF):
        super(BaseTestCase, self).setUp()
        moxfixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = moxfixture.mox
        self.stubs = moxfixture.stubs
        self.conf = conf
        self.useFixture(fixtures.FakeLogger('openstack.common'))
        self.useFixture(fixtures.Timeout(30, True))
        self.config(fatal_exception_format_errors=True)
        self.useFixture(fixtures.NestedTempfile())
        self.tempdirs = []

        self.addCleanup(self.conf.reset)
        self.addCleanup(self.conf.reset)
        self.addCleanup(self.stubs.UnsetAll)
        self.addCleanup(self.stubs.SmartUnsetAll)

    def create_tempfiles(self, files, ext='.conf'):
        tempfiles = []
        for (basename, contents) in files:
            if not os.path.isabs(basename):
                (fd, path) = tempfile.mkstemp(prefix=basename, suffix=ext)
            else:
                path = basename + ext
                fd = os.open(path, os.O_CREAT | os.O_WRONLY)
            tempfiles.append(path)
            try:
                os.write(fd, contents)
            finally:
                os.close(fd)
        return tempfiles

    def config(self, **kw):
        """Override some configuration values.

        The keyword arguments are the names of configuration options to
        override and their values.

        If a group argument is supplied, the overrides are applied to
        the specified configuration option group.

        All overrides are automatically cleaned up at the end of the
        current test.
        """
        group = kw.pop('group', None)
        for k, v in kw.iteritems():
            self.conf.set_override(k, v, group)
