# Copyright 2020 Red Hat, Inc.
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

from ironic.api import functions
from ironic.tests import base as test_base


class TestFunctionDefinition(test_base.TestCase):

    def test_get_arg(self):
        def myfunc(self, a):
            pass

        fd = functions.FunctionDefinition(myfunc)
        fd.arguments.append(functions.FunctionArgument('a', int, True, 0))
        arg = fd.get_arg('a')
        self.assertEqual(int, arg.datatype)
        self.assertEqual('a', arg.name)
        self.assertEqual(True, arg.mandatory)
        self.assertEqual(0, arg.default)
        self.assertIsNone(fd.get_arg('b'))

    def test_set_arg_types(self):
        def myfunc(self, string, integer, boolean=True):
            pass

        fd = functions.FunctionDefinition(myfunc)
        argspec = functions.getargspec(myfunc)
        fd.set_arg_types(argspec, [str, int, bool])

        arg = fd.get_arg('string')
        self.assertEqual(str, arg.datatype)
        self.assertEqual('string', arg.name)
        self.assertEqual(True, arg.mandatory)
        self.assertIsNone(arg.default)

        arg = fd.get_arg('integer')
        self.assertEqual(int, arg.datatype)
        self.assertEqual('integer', arg.name)
        self.assertEqual(True, arg.mandatory)
        self.assertIsNone(arg.default)

        arg = fd.get_arg('boolean')
        self.assertEqual(bool, arg.datatype)
        self.assertEqual('boolean', arg.name)
        self.assertEqual(False, arg.mandatory)
        self.assertTrue(arg.default)

    def test_signature(self):
        @functions.signature(str, str, int, bool)
        def myfunc(self, string, integer, boolean=True):
            '''Do the thing with the thing '''
            return 'result'

        fd = myfunc._wsme_definition
        self.assertEqual('myfunc', fd.name)
        self.assertEqual('Do the thing with the thing ', fd.doc)
        self.assertEqual(str, fd.return_type)

        arg = fd.get_arg('string')
        self.assertEqual(str, arg.datatype)
        self.assertEqual('string', arg.name)
        self.assertEqual(True, arg.mandatory)
        self.assertIsNone(arg.default)

        arg = fd.get_arg('integer')
        self.assertEqual(int, arg.datatype)
        self.assertEqual('integer', arg.name)
        self.assertEqual(True, arg.mandatory)
        self.assertIsNone(arg.default)

        arg = fd.get_arg('boolean')
        self.assertEqual(bool, arg.datatype)
        self.assertEqual('boolean', arg.name)
        self.assertEqual(False, arg.mandatory)
        self.assertTrue(arg.default)
