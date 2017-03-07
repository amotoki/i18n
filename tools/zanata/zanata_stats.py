#!/usr/bin/python

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

from __future__ import print_function

import argparse
import csv
import datetime
import io
import json
import random
import re
import sys

from oslo_log import log as logging
import requests
import six
import yaml

ZANATA_URI = 'https://translate.openstack.org/rest/%s'
LOG = logging.getLogger(__name__)

ZANATA_VERSION_PATTERN = re.compile(r'^(master[-,a-z]*|stable-[a-z]+)$')


class ZanataUtility(object):
    """Utilities to invoke Zanata REST API."""

    user_agents = [
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64) Gecko/20100101 Firefox/32.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_6) AppleWebKit/537.78.2',
        'Mozilla/5.0 (Windows NT 6.3; WOW64) Gecko/20100101 Firefox/32.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/37.0.2062.120',
        'Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko'
    ]

    def read_uri(self, uri, headers):
        try:
            headers['User-Agent'] = random.choice(ZanataUtility.user_agents)
            req = requests.get(uri, headers=headers)
            return req.text
        except Exception as e:
            print('exception happen', e)
            LOG.warning('Error "%(error)s" while reading uri %(uri)s',
                        {'error': e, 'uri': uri})
            raise

    def read_json_from_uri(self, uri):
        data = self.read_uri(uri, {'Accept': 'application/json'})
        try:
            return json.loads(data)
        except Exception as e:
            LOG.warning('Error "%(error)s" parsing json from uri %(uri)s',
                        {'error': e, 'uri': uri})
            raise

    def get_projects(self):
        uri = ZANATA_URI % ('projects')
        LOG.debug("Reading projects from %s" % uri)
        projects_data = self.read_json_from_uri(uri)
        return [project['id'] for project in projects_data]

    @staticmethod
    def _is_valid_version(version):
        return bool(ZANATA_VERSION_PATTERN.match(version))

    def get_project_versions(self, project_id):
        uri = ZANATA_URI % ('projects/p/%s' % project_id)
        LOG.debug("Reading iterations for project %s" % project_id)
        project_data = self.read_json_from_uri(uri)
        if 'iterations' in project_data:
            return [interation_data['id']
                    for interation_data in project_data['iterations']
                    if self._is_valid_version(interation_data['id'])]
        else:
            return []

    def get_user_stats(self, project_id, iteration_id, zanata_user_id,
                       start_date, end_date):
        uri = ZANATA_URI % ('stats/project/%s/version/%s/contributor/%s/%s..%s'
                            % (project_id, iteration_id, zanata_user_id,
                               start_date, end_date))
        return self.read_json_from_uri(uri)


class LanguageTeam(object):

    def __init__(self, language_code, team_info):
        self.language_code = language_code
        self.language = team_info['language']
        # Zanata ID which only consists of numbers is a valid ID in Zanata.
        # Such entry is interpreted as integer unless it is quoted
        # in the YAML file. Ensure to stringify them.
        self.translators = [str(i) for i in team_info['translators']]
        self.reviewers = [str(i) for i in team_info.get('reviewers', [])]
        self.coordinators = [str(i) for i in team_info.get('coordinators', [])]

    @classmethod
    def load_from_language_team_yaml(cls, translation_team_uri, lang_list):
        LOG.debug('Process list of language team from uri: %s',
                  translation_team_uri)

        content = yaml.safe_load(io.open(translation_team_uri, 'r'))

        if lang_list:
            lang_notfound = [lang_code for lang_code in lang_list
                             if lang_code not in content]
            if lang_notfound:
                print('Language %s not tound in %s.' %
                      (', '.join(lang_notfound),
                       translation_team_uri))
                sys.exit(1)

        return [cls(lang_code, team_info)
                for lang_code, team_info in content.items()
                if not lang_list or lang_code in lang_list]


class User(object):

    def __init__(self, user_id, language_code):
        self.user_id = user_id
        self.lang = language_code
        self.translation_stats = {}
        self.review_stats = {}

    def __str__(self):
        return ("<%s: user_id=%s, lang=%s, "
                "translation_stats=%s, review_stats=%s" %
                (self.__class__.__name__,
                 self.user_id, self.lang,
                 self.translation_stats,
                 self.review_stats))

    def __repr__(self):
        return repr(self.convert_to_serializable_data())

    def __lt__(self, other):
        if self.lang != other.lang:
            return self.lang < other.lang
        else:
            return self.user_id < other.user_id

    def read_from_zanata_stats(self, zanata_stats):
        # data format (Zanata 3.9.6)
        # {
        #     "username": "amotoki",
        #     "contributions": [
        #         {
        #             "locale": "ja",
        #             "translation-stats": {
        #                 "translated": 7360,
        #                 "needReview": 0,
        #                 "approved": 152,
        #                 "rejected": 0
        #             },
        #             "review-stats": {
        #                 "approved": 220,
        #                 "rejected": 0
        #             }
        #         }
        #     ]
        # }
        stats = [d for d in zanata_stats['contributions']
                 if d['locale'] == self.lang]
        if not stats:
            return

        stats = stats[0]
        trans_stats = stats.get('translation-stats')
        if trans_stats:
            trans_stats['total'] = sum(trans_stats.values())
            self.translation_stats = trans_stats
        review_stats = stats.get('review-stats')
        if review_stats:
            review_stats['total'] = sum(review_stats.values())
            self.review_stats = review_stats

    def needs_output(self, include_no_activities):
        if include_no_activities:
            return True
        elif self.translation_stats or self.review_stats:
            return True
        else:
            return False

    @staticmethod
    def get_flattened_data_title():
        return [
            'user_id',
            'lang',
            'translation-total',
            'translated',
            'needReview',
            'approved',
            'rejected',
            'review-total',
            'review-approved',
            'review-rejected'
        ]

    def convert_to_flattened_data(self):
        return [
            self.user_id,
            self.lang,
            self.translation_stats.get('total', 0),
            self.translation_stats.get('translated', 0),
            self.translation_stats.get('needReview', 0),
            self.translation_stats.get('approved', 0),
            self.translation_stats.get('rejected', 0),
            self.review_stats.get('total', 0),
            self.review_stats.get('approved', 0),
            self.review_stats.get('rejected', 0),
        ]

    def convert_to_serializable_data(self):
        return {'user_id': self.user_id,
                'lang': self.lang,
                'translation-stats': self.translation_stats,
                'review-stats': self.review_stats}


def get_zanata_stats(start_date, end_date, language_teams, project_list,
                     version_list, user_list):
    print('Getting Zanata contributors statistics (from %s to %s) ...' %
          (start_date, end_date))
    zanataUtil = ZanataUtility()
    users = []
    for team in language_teams:
        users += [User(user_id, team.language_code)
                  for user_id in team.translators]

    if not project_list:
        project_list = zanataUtil.get_projects()
    for project_id in project_list:
        for version in zanataUtil.get_project_versions(project_id):
            if version_list and version not in version_list:
                continue
            for user in users:
                if user_list and user.user_id not in user_list:
                    continue
                print('Getting %(project_id)s %(version)s '
                      'for user %(user_id)s %(user_lang)s'
                      % {'project_id': project_id,
                         'version': version,
                         'user_id': user.user_id,
                         'user_lang': user.lang})
                statisticdata = zanataUtil.get_user_stats(
                    project_id, version, user.user_id, start_date, end_date)
                print('Got: %s' % statisticdata)
                user.read_from_zanata_stats(statisticdata)
                print('=> %s' % user)

    return users


def write_stats_to_file(users, output_file, file_format,
                        include_no_activities):
    stats = sorted([user for user in users
                    if user.needs_output(include_no_activities)])
    if file_format == 'csv':
        _write_stats_to_csvfile(stats, output_file)
    else:
        _write_stats_to_jsonfile(stats, output_file)
    print('Stats has been written to %s' % output_file)


def _write_stats_to_csvfile(stats, output_file):
    mode = 'w' if six.PY3 else 'wb'
    with open(output_file, mode) as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(User.get_flattened_data_title())
        for stat in stats:
            writer.writerow(stat.convert_to_flattened_data())


def _write_stats_to_jsonfile(stats, output_file):
    stats = [stat.convert_to_serializable_data() for stat in stats]
    with open(output_file, 'w') as f:
        f.write(json.dumps(stats, indent=4, sort_keys=True))


def _comma_separated_list(s):
    return s.split(',')


def main():

    default_end_date = datetime.datetime.now()
    default_start_date = default_end_date - datetime.timedelta(days=180)
    default_start_date = default_start_date.strftime('%Y-%m-%d')
    default_end_date = default_end_date.strftime('%Y-%m-%d')

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--start-date",
                        default=default_start_date,
                        help=("Specify the start date. "
                              "Default:%s" % default_start_date))
    parser.add_argument("-e", "--end-date",
                        default=default_end_date,
                        help=("Specify the end date. "
                              "Default:%s" % default_end_date))
    parser.add_argument("-o", "--output-file",
                        help=("Specify the output file. "
                              "Default: zanata_stats_output.{csv,json}."))
    parser.add_argument("-p", "--project",
                        type=_comma_separated_list,
                        required=True,
                        help=("Specify project(s). Comma-separated list. "
                              "Otherwise all Zanata projects are processed."))
    parser.add_argument("-l", "--lang",
                        type=_comma_separated_list,
                        help=("Specify language(s). Comma-separated list. "
                              "Language code like zh-CN, ja needs to be used. "
                              "Otherwise all languages are processed."))
    parser.add_argument("-t", "--target-version",
                        type=_comma_separated_list,
                        required=True,
                        help=("Specify version(s). Comma-separated list. "
                              "Otherwise all available versions are "
                              "processed."))
    parser.add_argument("-u", "--user",
                        type=_comma_separated_list,
                        help=("Specify user(s). Comma-separated list. "
                              "Otherwise all users are processed."))
    parser.add_argument("--include-no-activities",
                        action='store_true',
                        help=("If specified, stats for users with no "
                              "activities are output as well."
                              "By default, stats only for users with "
                              "any activities are output."))
    parser.add_argument("-f", "--format",
                        default='csv', choices=['csv', 'json'],
                        help="Output file format.")
    parser.add_argument("user_yaml",
                        help="YAML file of the user list")
    options = parser.parse_args()

    # Currently only single version is supported
    # due to the implemenation. (bug 1670640)
    if len(options.target_version) > 1 or len(options.project) > 1:
        print('It is not supported to specify multiple target versions or '
              'multiple projects',
              file=sys.stderr)
        sys.exit(1)
    versions = [v.replace('/', '-') for v in options.target_version]

    language_teams = LanguageTeam.load_from_language_team_yaml(
        options.user_yaml, options.lang)

    users = get_zanata_stats(options.start_date, options.end_date,
                             language_teams, options.project,
                             versions, options.user)

    output_file = (options.output_file or
                   'zanata_stats_output.%s' % options.format)

    write_stats_to_file(users, output_file, options.format,
                        options.include_no_activities)


if __name__ == '__main__':
    main()
