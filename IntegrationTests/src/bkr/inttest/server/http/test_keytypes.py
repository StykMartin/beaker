# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import requests

from bkr.inttest import DatabaseTestCase, data_setup, get_server_base
from bkr.inttest.server.requests_utils import login, patch_json, post_json
from bkr.server.model import Key, Key_Value_String, session


class KeyTypesHTTPTest(DatabaseTestCase):

    def setUp(self):
        self.key_name = data_setup.unique_name(u'KEY%s')
        with session.begin():
            session.add(Key(self.key_name))
            self.user = data_setup.create_user(password=u'notadmin')
        self.s = requests.Session()

    def test_lists_key_types(self):
        response = self.s.get(get_server_base() + 'keytypes',
                              headers={'Accept': 'application/json'})
        response.raise_for_status()
        names = [entry['key_name'] for entry in response.json()['entries']]
        self.assertIn(self.key_name, names)

    def test_filters_key_types_by_query(self):
        response = self.s.get(get_server_base() + 'keytypes',
                              params={'q': 'key_name:%s' % self.key_name},
                              headers={'Accept': 'application/json'})
        response.raise_for_status()
        names = [entry['key_name'] for entry in response.json()['entries']]
        self.assertEqual([self.key_name], names)

    def test_gets_one_key_type(self):
        response = self.s.get(get_server_base() + 'keytypes/' + self.key_name)
        response.raise_for_status()
        self.assertEqual({'key_name': self.key_name, 'numeric': False},
                         response.json())

    def test_unknown_key_type_is_not_found(self):
        response = self.s.get(get_server_base() + 'keytypes/NOSUCHKEY')
        self.assertEqual(404, response.status_code)

    def test_creates_key_type(self):
        login(self.s)
        new_name = data_setup.unique_name(u'NEW%s')
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': new_name})
        self.assertEqual(201, response.status_code)
        self.assertEqual({'key_name': new_name, 'numeric': False},
                         response.json())
        self.assertEqual(get_server_base() + 'keytypes/' + new_name,
                         response.headers['Location'])
        with session.begin():
            self.assertFalse(Key.by_name(new_name).numeric)

    def test_creates_numeric_key_type(self):
        login(self.s)
        new_name = data_setup.unique_name(u'NUM%s')
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': new_name, 'numeric': True})
        self.assertEqual(201, response.status_code)
        self.assertTrue(response.json()['numeric'])
        with session.begin():
            self.assertTrue(Key.by_name(new_name).numeric)

    def test_cannot_create_duplicate_key_type(self):
        login(self.s)
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': self.key_name})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Key type %s already exists' % self.key_name,
                         response.text)

    def test_cannot_create_key_type_with_unsafe_name(self):
        login(self.s)
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': u'bad name'})
        self.assertEqual(400, response.status_code)

    def test_anonymous_cannot_create_key_type(self):
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': u'ANON'})
        self.assertEqual(401, response.status_code)

    def test_non_admin_cannot_create_key_type(self):
        login(self.s, user=self.user.user_name, password=u'notadmin')
        response = post_json(get_server_base() + 'keytypes', session=self.s,
                             data={'key_name': u'NOTADMIN'})
        self.assertEqual(403, response.status_code)

    def test_renames_key_type(self):
        login(self.s)
        new_name = data_setup.unique_name(u'RENAMED%s')
        response = patch_json(get_server_base() + 'keytypes/' + self.key_name,
                              session=self.s, data={'key_name': new_name})
        response.raise_for_status()
        self.assertEqual(new_name, response.json()['key_name'])
        with session.begin():
            self.assertEqual(new_name, Key.by_name(new_name).key_name)

    def test_sets_numeric(self):
        login(self.s)
        response = patch_json(get_server_base() + 'keytypes/' + self.key_name,
                              session=self.s, data={'numeric': True})
        response.raise_for_status()
        self.assertTrue(response.json()['numeric'])
        with session.begin():
            self.assertTrue(Key.by_name(self.key_name).numeric)

    def test_cannot_rename_onto_existing_key_type(self):
        with session.begin():
            other = data_setup.unique_name(u'OTHER%s')
            session.add(Key(other))
        login(self.s)
        response = patch_json(get_server_base() + 'keytypes/' + self.key_name,
                              session=self.s, data={'key_name': other})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Key type %s already exists' % other, response.text)

    def test_non_admin_cannot_update_key_type(self):
        login(self.s, user=self.user.user_name, password=u'notadmin')
        response = patch_json(get_server_base() + 'keytypes/' + self.key_name,
                              session=self.s, data={'numeric': True})
        self.assertEqual(403, response.status_code)

    def test_deletes_key_type(self):
        login(self.s)
        response = self.s.delete(get_server_base() + 'keytypes/' + self.key_name)
        self.assertEqual(204, response.status_code)
        with session.begin():
            self.assertEqual(0, Key.query.filter_by(key_name=self.key_name).count())

    def test_deleting_key_type_also_deletes_its_values(self):
        with session.begin():
            system = data_setup.create_system()
            key = Key.by_name(self.key_name)
            system.key_values_string.append(Key_Value_String(key, u'somevalue'))
            system_id = system.id
        login(self.s)
        response = self.s.delete(get_server_base() + 'keytypes/' + self.key_name)
        self.assertEqual(204, response.status_code)
        with session.begin():
            self.assertEqual(0, Key_Value_String.query
                             .filter_by(system_id=system_id).count())

    def test_non_admin_cannot_delete_key_type(self):
        login(self.s, user=self.user.user_name, password=u'notadmin')
        response = self.s.delete(get_server_base() + 'keytypes/' + self.key_name)
        self.assertEqual(403, response.status_code)
