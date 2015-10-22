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

"""Tests for custom SQLAlchemy types via Ironic DB."""

from oslo_db import exception as db_exc
from oslo_utils import uuidutils

import ironic.db.sqlalchemy.api as sa_api
from ironic.db.sqlalchemy import models
from ironic.tests.unit.db import base


class SqlAlchemyCustomTypesTestCase(base.DbTestCase):

    # NOTE(max_lobur): Since it's not straightforward to check this in
    #                  isolation these tests use existing db models.

    def test_JSONEncodedDict_default_value(self):
        # Create chassis w/o extra specified.
        ch1_id = uuidutils.generate_uuid()
        self.dbapi.create_chassis({'uuid': ch1_id})
        # Get chassis manually to test SA types in isolation from UOM.
        ch1 = sa_api.model_query(models.Chassis).filter_by(uuid=ch1_id).one()
        self.assertEqual({}, ch1.extra)

        # Create chassis with extra specified.
        ch2_id = uuidutils.generate_uuid()
        extra = {'foo1': 'test', 'foo2': 'other extra'}
        self.dbapi.create_chassis({'uuid': ch2_id, 'extra': extra})
        # Get chassis manually to test SA types in isolation from UOM.
        ch2 = sa_api.model_query(models.Chassis).filter_by(uuid=ch2_id).one()
        self.assertEqual(extra, ch2.extra)

    def test_JSONEncodedDict_type_check(self):
        self.assertRaises(db_exc.DBError,
                          self.dbapi.create_chassis,
                          {'extra': ['this is not a dict']})

    def test_JSONEncodedList_default_value(self):
        # Create conductor w/o extra specified.
        cdr1_id = 321321
        self.dbapi.register_conductor({'hostname': 'test_host1',
                                       'drivers': None,
                                       'id': cdr1_id})
        # Get conductor manually to test SA types in isolation from UOM.
        cdr1 = (sa_api
                .model_query(models.Conductor)
                .filter_by(id=cdr1_id)
                .one())
        self.assertEqual([], cdr1.drivers)

        # Create conductor with drivers specified.
        cdr2_id = 623623
        drivers = ['foo1', 'other driver']
        self.dbapi.register_conductor({'hostname': 'test_host2',
                                       'drivers': drivers,
                                       'id': cdr2_id})
        # Get conductor manually to test SA types in isolation from UOM.
        cdr2 = (sa_api
                .model_query(models.Conductor)
                .filter_by(id=cdr2_id)
                .one())
        self.assertEqual(drivers, cdr2.drivers)

    def test_JSONEncodedList_type_check(self):
        self.assertRaises(db_exc.DBError,
                          self.dbapi.register_conductor,
                          {'hostname': 'test_host3',
                           'drivers': {'this is not a list': 'test'}})
