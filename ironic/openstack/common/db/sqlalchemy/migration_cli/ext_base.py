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

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class MigrationExtensionBase(object):

    #used to sort migration in logical order
    order = 0

    @property
    def enabled(self):
        """Used for availability verification of a plugin.

        :rtype: bool
        """
        return False

    @abc.abstractmethod
    def upgrade(self, version):
        """Used for upgrading database.

        :param version: Desired database version
        :type version: string
        """

    @abc.abstractmethod
    def downgrade(self, version):
        """Used for downgrading database.

        :param version: Desired database version
        :type version: string
        """

    @abc.abstractmethod
    def version(self):
        """Current database version.

        :returns: Databse version
        :rtype: string
        """

    def revision(self, *args, **kwargs):
        """Used to generate migration script.

        In migration engines that support this feature, it should generate
        new migration script.

        Accept arbitrary set of arguments.
        """
        raise NotImplementedError()

    def stamp(self, *args, **kwargs):
        """Stamps database based on plugin features.

        Accept arbitrary set of arguments.
        """
        raise NotImplementedError()

    def __cmp__(self, other):
        """Used for definition of plugin order.

        :param other: MigrationExtensionBase instance
        :rtype: bool
        """
        return self.order > other.order
