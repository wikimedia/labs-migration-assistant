#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
labs-migration-assistant: a script to assess the readyness of
a Wikimedia Labs instance to be migrated from the Tampa dc to
the Ashburn dc.

Copyright (C) 2014  Diederik van Liere, Wikimedia Foundation

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
'''

import os
import logging
import functools

import yaml
import requests

from fabric.api import *
from datetime import datetime
from ansistrm import ColorizingStreamHandler


logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler = ColorizingStreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)
'''
Fabric logging messages have their own hardcoded format and will thus not follow the
formatter format. See also https://github.com/fabric/fabric/issues/163
'''

# fabric settings
env.timeout = 10
env.forward_agent = True
env.skip_bad_hosts = True
env.colorize_errors = True
env.abort_on_prompts = True
env.connection_attempts = 3
env.disable_known_hosts = True
env.reject_unknown_hosts = False
env.gateway = 'bastion.wmflabs.org'
env.ignored_hosts = env.ignored_hosts.split(';')
env.key_filename = os.path.join(os.path.expanduser('~'), '.ssh/id_rsa')


class LabInstance:

    def __init__(self, name, project, datacenter):
        self.tasks = ['detect_self_puppetmaster', 'detect_last_puppet_run',
                      'detect_shared_storage_for_projects', 'detect_shared_storage_for_home',
                      'detect_databases', 'detect_mediawiki']
        self.name = name
        self.project = project
        self.datacenter = datacenter
        self.connect = None
        for task in self.tasks:
            setattr(self, task, 'FAIL')

    def __str__(self):
        return '%s.%s.wmflabs' % (self.name, self.datacenter)

    def __repr__(self):
        return str(self)

    def count_errors(self):
        return sum([1 for task in self.tasks if getattr(self, task) == 'FAIL' or getattr(self, task) == 'WARNING'])


def load_lab_instances():
    '''
    Entry point for collecting all lab instances of specified user
    TODO: maybe filter for those instances where the user is admin?
    '''
    if 'debug' in env and env.debug is True:
        test_instance = LabInstance('limn0', 'analytics', 'pmtpa')
        labinstances = {'limn0.pmtpa.wmflabs': test_instance}
    else:
        labinstances = fetch_lab_instances()
        labinstances = parse_lab_instances(labinstances)

    if len(labinstances) == 0:
        logging.error(
            'I was either not able to parse the Wikitech page containing your lab instances or you are not the administrator for any lab instance.')

    return labinstances


def parse_lab_instances(labinstances):
    results = {}
    for group in labinstances:
        for resource, labinstance in group.get('results', {}).iteritems():
            names = labinstance.get('printouts', {}).get('Instance Name', None)
            project = labinstance.get('printouts', {}).get('Project', None)
            dc = resource.split('.')[1]
            # TODO: only analyse instances in Tampa, make this configurable?
            if dc == 'pmtpa':
                for name in names:
                    if not name.startswith('tools') and not name.startswith('bastion') and not name in env.ignored_hosts:
                        # ignore all tool-labs instances as they are managed by
                        # WMF.
                        labinstance = LabInstance(name, project, dc)
                        results[str(labinstance)] = labinstance
    return results


def fetch_lab_instances():
    logging.info('Fetching labinstances from wikitech')
    projects_url = 'https://wikitech.wikimedia.org/w/api.php?action=ask&query=[[Member::User:%s]]&format=json' % env.wiki_username
    verify = False  # TODO: make this configurable?
    labinstances = []
    try:
        request = requests.get(projects_url, verify=verify)
        projects = request.json().get('query', {}).get('results', {})
        for project in projects:
            project = project.split(':')[1].lower()
            instances_url = 'https://wikitech.wikimedia.org/w/api.php?action=ask&query=[[Resource Type::instance]][[Project::%s]]|?Instance Name|?Project&format=json' % project
            request = requests.get(instances_url, verify=verify)
            labinstances.append(request.json().get('query', {}))
    except requests.exceptions.ConnectionError, e:
        logging.error(e)
    except Exception, e:
        logging.error('Caught unexpected error')
        logging.error(e)
    finally:
        pass
    return labinstances


def output_settings():
    keys = env.keys()
    keys.sort()
    for key in keys:
        if not key.startswith('password'):
            # let's make sure that people do not accidentally expose their
            # passwords in a gist or something like that
            logging.info('%s: \t %s' % (key, env.get(key, None)))


def output_summary():
    for labsinstance in env.labinstances.values():
        logging.info('***** Summary of tests for %s *****' % labsinstance)
        logging.info('Please fix the %d identified problems.' %
                     labsinstance.count_errors())
        problems = 0
        if not labsinstance.connect:
            problems += 1
            logging.error(
                'There were problems connecting to instance %s, please fix those problems first and then rerun this script.' %
                labsinstance)

        for test, task in enumerate(labsinstance.tasks):
            result = getattr(labsinstance, task)
            logging.info('Test %d: task %s: %s' % (test, task, result))
            if result == 'FAIL' or result == 'WARNING':
                problems += 1
        if problems == 0:
            logging.info('Congratulations! %s seems ready for migration!' %
                         labsinstance)
        else:
            logging.error(
                '%s does not yet seem to be ready for migration to eqiad. ' % labsinstance)
        logging.info('***** End of summary for %s *****' % labsinstance)
        print  # empty line to make it easier to read summary output


def logged(func):
    '''Logging decorator.'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with hide('output'):
            output = func(*args, **kwargs)
        logging.info(output)
        return output
    return wrapper


@task
def check_connection(func, *args, **kwargs):
    '''Check connection decorator'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if env.host_string is None:
            return wrapper
        if env.labinstances[env.host_string].connect is None:
            # execute a simple command to verify that we have succesfully
            # logged into the labs instance
            try:
                int(run('whoami | wc -l'))
                env.labinstances[env.host_string].connect = True
                func(*args, **kwargs)
            except SystemExit:
                env.labinstances[env.host_string].connect = False
            except ValueError:
                env.labinstances[env.host_string].connect = False
        elif env.labinstances[env.host_string].connect is False:
            logging.warning(
                'Skipping task because during first test I was not able to connect to labsinstance %s.' % env.host_string)
        else:
            func(*args, **kwargs)
    return wrapper


@task
@check_connection
def detect_self_puppetmaster():
    result = int(run(
        'grep "^server = virt0.wikimedia.org" /etc/puppet/puppet.conf | wc -l'))
    if result == 0:
        # anything else than virt0.wikimedia.org is considered a self-hosted
        # puppetmaster
        logging.info('You are not using a self-hosted puppet master. [OK]')
        env.labinstances[env.host_string].detect_self_puppetmaster = 'PASS'
    else:
        logging.error(
            'You are running your own self-hosted puppet master. [FAIL]')
        env.labinstances[env.host_string].detect_self_puppetmaster = 'FAIL'


@task
@check_connection
def detect_last_puppet_run():
    result = sudo('cat /var/lib/puppet/state/last_run_summary.yaml')
    doc = yaml.load(result)
    epoch = doc.get('time', {}).get('last_run', 0)
    if epoch == 0:
        logging.error(
            'We could not determine the last time puppet was run. [FAIL]')
        env.labinstances[env.host_string].detect_last_puppet_run = 'FAIL'
    else:
        epoch = datetime.fromtimestamp(epoch)
        now = datetime.now()
        dt = now - epoch
        if dt.total_seconds() > 86400:
            logging.error(
                'The last puppet run was at least %d days ago, please run puppet. [FAIL]' % dt.days)
            env.labinstances[env.host_string].detect_last_puppet_run = 'FAIL'
        else:
            logging.info('Puppet is up-to-date. [OK]')
            env.labinstances[env.host_string].detect_last_puppet_run = 'PASS'


@task
@check_connection
def detect_shared_storage_for_projects():
    result = int(run('ls -l | wc -l'))
    if result == 0:
        logging.info(
            'You seem not to be using your home folder for storing files. [OK]')
        env.labinstances[
            env.host_string].detect_shared_storage_for_projects = 'PASS'
    else:
        logging.error(
            'You seem to be using your home folder for storing files and folders. Please migrate your files to /data/projects/. [FAIL]')
        env.labinstances[
            env.host_string].detect_shared_storage_for_projects = 'FAIL'


@task
@check_connection
def detect_shared_storage_for_home():
    result = run('df $HOME')
    result = result.splitlines()[1]
    if result.find(':') > -1:
        logging.info(
            'You seem to be using the shared storage space for your home folder. [OK]')
        env.labinstances[
            env.host_string].detect_shared_storage_for_home = 'PASS'
    else:
        logging.warn(
            'You do not seem to be using the shared storage space for your home folder. Please make sure that you have backups. [WARNING]')
        env.labinstances[
            env.host_string].detect_shared_storage_for_home = 'FAIL'


@task
@check_connection
def detect_databases():
    try:
        result = int(run('ls /etc/init.d | grep mysql | wc -l'))
        if result == 0:
            logging.info(
                'You are not running a MySQL instance and hence you do not have to make any backups. [OK]')
            env.labinstances[env.host_string].detect_databases = 'PASS'
        else:
            running = run('service mysql status')
            if running.find('not') > -1:
                logging.warning(
                    'Your MySQL instance is not running and hence I cannot detemine if you need to make backups. [WARNING]')
                env.labinstances[env.host_string].detect_databases = 'WARNING'
            else:
                result = int(run('mysql -e "show databases" | wc -l'))
                if result > 1:
                    # ignore information_schema database
                    logging.warn(
                        'You are running a MySQL instance and hence you should probably make a backup. [WARNING]')
                    env.labinstances[
                        env.host_string].detect_databases = 'WARNING'
                else:
                    logging.info(
                        'You are running a MySQL database instance but it does not seem to have any databases. [OK]')
                    env.labinstances[env.host_string].detect_databases = 'PASS'
    except ValueError:
        logging.error(
            'Could not log in to your MySQL instance using default credentials, your current username and no password. [ERROR]')
        logging.error(
            'Please make sure that in your home folder on your lab instance there is a .my.cnf file that contains your credentials.')
        logging.error(
            'See for instructions http://dev.mysql.com/doc/refman/5.1/en/option-files.html')
        env.labinstances[env.host_string].detect_databases = 'WARNING'


@task
@check_connection
def detect_mediawiki():
    try:
        result = int(
            run('test -d /var/lib/mediawiki && echo "Mediawiki install folder exists." | wc -l'))
        if result == 1:
            logging.warning(
                'We detected an installation of Mediawiki, please make sure you have a backup. [WARNING]')
            env.labinstances[env.host_string].detect_mediawiki = 'WARNING'
    except ValueError:
        logging.info(
            'You do not have an installation of Mediawiki hence you do not have to make backups. [OK]')
        env.labinstances[env.host_string].detect_mediawiki = 'PASS'


@task
@check_connection
def test():
    with settings(warn_only=True):
        execute(detect_databases)
        execute(detect_mediawiki)
        execute(detect_self_puppetmaster)
        execute(detect_last_puppet_run)
        execute(detect_shared_storage_for_projects)
        execute(detect_shared_storage_for_home)
    output_summary()
    '''
    TODO: There is a weird bug in probably my code where if you call test then it will keep looping over all
    hosts and not exit (infinite loop afaict). The statement below is to force an exit, if you know a
    solution to this problems then let me know.
    '''
    exit(0)


run = logged(run)

env.labinstances = load_lab_instances()
env.hosts.extend(['%s.%s.wmflabs' % (labinstance.name, labinstance.datacenter)
                  for labinstance in env.labinstances.values()])
logging.info('Going to test %d instances...' % len(env.hosts))
output_settings()


def main():
    print 'You should not run this script directly but instead call it as:'
    print 'fab test --set wiki_username=YOUR_WIKI_USERNAME'
    print
    print 'The wiki that we are referring to is Wikitech.'
    print 'You might need to pass additional paramaters like your password for your SSH key, but this'
    print 'depends on the actual setup of your system.'
    print 'For an overview of possible parameters run fab --help'
    exit(-1)

if __name__ == '__main__':
    main()
