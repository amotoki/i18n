# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os

from oslotest import base
import requests_mock

from openstack_i18n.zanata import zanata_stats


def load_test_data(filename, load_json=True):
    current_dir = os.path.dirname(__file__)
    datafile = os.path.join(current_dir, 'test_data', filename)
    with open(datafile) as f:
        data = f.read()
    if load_json:
        return json.loads(data)
    else:
        return data


class ZanataUtilityTestCase(base.BaseTestCase):

    # Ensure to use non-existing URL
    FAKE_URI = 'http://localhost:22222/'

    def setUp(self):
        super(ZanataUtilityTestCase, self).setUp()
        self.zanata = zanata_stats.ZanataUtility(self.FAKE_URI)

    @requests_mock.Mocker()
    def test_read_uri(self, m):
        test_url = self.FAKE_URI + 'foo'
        headers = {'Header-1': 'Value'}
        m.get(test_url, headers=headers, text='response')
        self.assertEqual('response',
                         self.zanata.read_uri(test_url, headers=headers))

    @requests_mock.Mocker()
    def test_get_projects(self, m):
        data = load_test_data('projects.json', load_json=False)
        m.get(self.FAKE_URI + 'projects', text=data)
        self.assertEqual(['aodh', 'api-site', 'barbican'],
                         self.zanata.get_projects())

    @requests_mock.Mocker()
    def test_get_project_versions(self, m):
        data = load_test_data('project_versions.json', load_json=False)
        m.get(self.FAKE_URI + 'projects/p/aodh', text=data)
        self.assertEqual(['master', 'stable-liberty', 'stable-newton'],
                         self.zanata.get_project_versions('aodh'))


class ZanataStatsUserTestCase(base.BaseTestCase):

    def test_sort_users(self):
        u1 = zanata_stats.User('user-a', 'lang-x')
        u2 = zanata_stats.User('user-b', 'lang-x')
        u3 = zanata_stats.User('user-a', 'lang-y')
        users = [u3, u2, u1]
        sorted_users = sorted(users)
        expected = [u1, u2, u3]
        self.assertEqual([(u.user_id, u.lang) for u in sorted_users],
                         [(u.user_id, u.lang) for u in expected])

    def _get_zanata_stats(self, user=None, lang=None,
                          no_translation_stats=False, no_review_stats=False):
        if no_translation_stats and no_review_stats:
            data = load_test_data('user_stats_no_contributions.json')
        elif no_review_stats:
            data = load_test_data('user_stats_translations_only.json')
        elif no_translation_stats:
            data = load_test_data('user_stats_review_only.json')
        else:
            data = load_test_data('user_stats_translations_and_reviews.json')
        data['username'] = user or 'user-a'
        if data['contributions']:
            data['contributions'][0]['locale'] = lang or 'lang-a'
        return data

    def test_read_from_zanata_stats(self):
        stats = self._get_zanata_stats()
        user = zanata_stats.User('user-a', 'lang-a')
        user.read_from_zanata_stats(stats, 'proj-1', 'master')
        self.assertEqual({'translation-stats': {'translated': 3,
                                                'needReview': 6,
                                                'approved': 27,
                                                'rejected': 1,
                                                'total': 37},
                          'review-stats': {'approved': 277,
                                           'rejected': 10,
                                           'total': 287}},
                         user.stats['proj-1']['master'])

    def test_read_from_zanata_stats_no_review_stats(self):
        stats = self._get_zanata_stats(no_review_stats=True)
        user = zanata_stats.User('user-a', 'lang-a')
        user.read_from_zanata_stats(stats, 'proj-1', 'master')
        self.assertEqual({'translation-stats': {'translated': 1460,
                                                'needReview': 5,
                                                'approved': 459,
                                                'rejected': 2,
                                                'total': 1926},
                          'review-stats': {}},
                         user.stats['proj-1']['master'])

    def test_read_from_zanata_stats_no_translation_stats(self):
        stats = self._get_zanata_stats(no_translation_stats=True)
        user = zanata_stats.User('user-a', 'lang-a')
        user.read_from_zanata_stats(stats, 'proj-1', 'master')
        self.assertEqual({'translation-stats': {},
                          'review-stats': {'approved': 250,
                                           'rejected': 31,
                                           'total': 281}},
                         user.stats['proj-1']['master'])

    def test_read_from_zanata_stats_no_contribution(self):
        stats = self._get_zanata_stats(no_translation_stats=True,
                                       no_review_stats=True)
        user = zanata_stats.User('user-a', 'lang-a')
        user.read_from_zanata_stats(stats, 'proj-1', 'master')
        self.assertFalse(user.stats)

    def test_read_from_zanata_stats_other_language_not_processed(self):
        stats = self._get_zanata_stats()
        user = zanata_stats.User('user-a', 'other')
        user.read_from_zanata_stats(stats, 'proj-1', 'master')
        self.assertFalse(user.stats)

    def _setup_stats(self):
        user = zanata_stats.User('user-a', 'lang-a')
        user.read_from_zanata_stats(
            self._get_zanata_stats(), 'proj-1', 'master')
        user.read_from_zanata_stats(
            self._get_zanata_stats(no_review_stats=True),
            'proj-1', 'stable/ocata')
        user.read_from_zanata_stats(
            self._get_zanata_stats(no_translation_stats=True),
            'proj-2', 'master')
        return user

    def test_populate_total_stats(self):
        user = self._setup_stats()
        user.populate_total_stats()
        self.assertEqual({'translation-stats': {'translated': 1463,
                                                'needReview': 11,
                                                'approved': 486,
                                                'rejected': 3,
                                                'total': 1963},
                          'review-stats': {'approved': 527,
                                           'rejected': 41,
                                           'total': 568}},
                         user.stats['__total__'])

    def test_convert_to_flattened_data(self):
        user = self._setup_stats()
        self.assertEqual([['user-a', 'lang-a',
                           '-', '-',
                           1963, 1463, 11, 486, 3,
                           568, 527, 41]],
                         user.convert_to_flattened_data())

    def test_convert_to_serialized_data(self):
        user = self._setup_stats()
        self.assertEqual(
            {'user_id': 'user-a',
             'lang': 'lang-a',
             'stats': {'translation-stats': {'translated': 1463,
                                             'needReview': 11,
                                             'approved': 486,
                                             'rejected': 3,
                                             'total': 1963},
                       'review-stats': {'approved': 527,
                                        'rejected': 41,
                                        'total': 568}}
             },
            user.convert_to_serializable_data())
