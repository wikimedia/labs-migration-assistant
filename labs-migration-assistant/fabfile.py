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
env.colorize_errors = True
env.abort_on_prompts = True
env.connection_attempts = 3
env.disable_known_hosts = True
env.reject_unknown_hosts = False
env.gateway = 'bastion.wmflabs.org'
env.key_filename = os.path.join(os.path.expanduser('~'), '.ssh/id_rsa')


class LabInstance:

    def __init__(self, name, project, datacenter):
        self.tasks = ['detect_self_puppetmaster', 'detect_last_puppet_run',
                      'detect_shared_storage_for_projects', 'detect_shared_storage_for_home']
        self.name = name
        self.project = project
        self.datacenter = datacenter
        self.connect = None
        for task in self.tasks:
            setattr(self, task, True)

    def __str__(self):
        return '%s.%s.wmflabs' % (self.name, self.datacenter)

    def __repr__(self):
        return str(self)

    def count_errors(self):
        return sum([1 for task in self.tasks if getattr(self, task) is False])


def check_connection(func, *args, **kwargs):
    '''Check connection decorator'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print kwargs
        print args
        output = func(*args, **kwargs)
        print output
    # if not labinstances[env.host_string].connect:
        #   logging.info('Skipping task because during first task was not able to connect to labsinstance.')
    return output
    return wrapper


def logged(func):
    '''Logging decorator.'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with hide('output'):
            output = func(*args, **kwargs)
        logging.info(output)
        return output
    return wrapper


def parse_lab_instances(labinstances):
    results = {}
    for group in labinstances:
        for resource, labinstance in group.get('results', {}).iteritems():
            names = labinstance.get('printouts', {}).get('Instance Name', None)
            project = labinstance.get('printouts', {}).get('Project', None)
            dc = resource.split('.')[1]
            for name in names:
                if not name.startswith('tools'):
                    # ignore all tool-labs instances as they are managed by
                    # WMF.
                    labinstance = LabInstance(name, project, dc)
                    results[str(labinstance)] = labinstance
    return results


def fetch_lab_instances():
    projects_url = 'https://wikitech.wikimedia.org/w/api.php?action=ask&query=[[Member::User:%s]]&format=json' % env.wiki_username
    verify = False
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


@task
def detect_self_puppetmaster(labinstances):
    try:
        result = run(
            'grep "^server = virt0.wikimedia.org" /etc/puppet/puppet.conf | wc -l')
        if result == '0':
            logging.info('You are not using a self-hosted puppet master. [OK]')
        else:
            logging.error(
                'You are running your own self-hosted puppet master. [FAIL]')
            labinstances[env.host_string].detect_self_puppetmaster = False
            labinstances[env.host_string].connect = True
    except SystemExit:
        logging.error('Could not connect to %s.' % env.host_string)
        # we only to set this once if we cannot connect to the instance.
        labinstances[env.host_string].connect = False


@task
def detect_last_puppet_run(labinstances):
    '''
    TODO: refactor this check into a decorator function, but Fabric is not really cooperating
    '''
    if not labinstances[env.host_string].connect:
        if not labinstances[env.host_string].connect:
            logging.info(
                'Skipping task because during first task was not able to connect to labsinstance.')
        return

    try:
        result = sudo('cat /var/lib/puppet/state/last_run_summary.yaml')
        doc = yaml.load(result)
        epoch = doc.get('time', {}).get('last_run', 0)
        if epoch == 0:
            logging.error(
                'We could not determine the last time puppet was run. [FAIL]')
        else:
            epoch = datetime.fromtimestamp(epoch)
            now = datetime.now()
            dt = now - epoch
            if dt.days > 29:
                logging.error(
                    'The last puppet run was %d days ago, please run puppet. [FAIL]' % dt.days)
                labinstances[env.host_string].detect_last_puppet_run = False
            else:
                logging.info('Puppet is up-to-date. [OK]')
    except SystemExit:
        logging.error('Could not connect to %s.' % env.host_string)


@task
def detect_shared_storage_for_projects(labinstances):
    '''
    TODO: refactor this check into a decorator function, but Fabric is not really cooperating
    '''
    if not labinstances[env.host_string].connect:
        if not labinstances[env.host_string].connect:
            logging.info(
                'Skipping task because during first task was not able to connect to labsinstance.')
        return

    try:
        result = run('ls -l | wc -l')
        result = int(result)
        if result == 0:
            logging.info(
                'You seem not to be using your home folder for storing files. [OK]')
        else:
            logging.error(
                'You seem to be using your home folder for storing files and folders. Please migrate your files to /data/projects/. [FAIL]')
            labinstances[
                env.host_string].detect_shared_storage_for_projects = False
    except SystemExit:
        logging.error('Could not connect to %s.' % env.host_string)


@task
def detect_shared_storage_for_home(labinstances):
    '''
    TODO: refactor this check into a decorator function, but Fabric is not really cooperating
    '''
    if not labinstances[env.host_string].connect:
        if not labinstances[env.host_string].connect:
            logging.info(
                'Skipping task because during first task was not able to connect to labsinstance.')
        return

    try:
        result = run('df $HOME')
        result = result.splitlines()[1]
        if result.find(':') > -1:
            logging.info(
                'You seem to be using the shared storage space for your home folder. [OK]')
        else:
            logging.error(
                'You do not seem to be using the shared storage space for your home folder. [FAIL]')
            labinstances[
                env.host_string].detect_shared_storage_for_home = False
    except SystemExit:
        logging.error('Could not connect to %s.' % env.host_string)


@task(default=True)
def migrate_ready():
    if 'debug' in env and env.debug is True:
        test_instance = LabInstance('limn0', 'analytics', 'pmtpa')
        labinstances = {'limn0.pmtpa.wmflabs': test_instance}
    else:
        labinstances = fetch_lab_instances()
        labinstances = parse_lab_instances(labinstances)
    hosts = ['%s.%s.wmflabs' % (labinstance.name, labinstance.datacenter)
             for labinstance in labinstances.values()]

    if len(hosts) == 0:
        logging.error(
            'I was either not able to parse the Wikitech page containing your lab instances or you are not the administrator for any lab instance.')
        exit(-1)

    with settings(warn_only=True):
        execute(detect_self_puppetmaster, hosts=hosts,
                labinstances=labinstances)
        execute(detect_last_puppet_run, hosts=hosts, labinstances=labinstances)
        execute(detect_shared_storage_for_projects,
                hosts=hosts, labinstances=labinstances)
        execute(detect_shared_storage_for_home,
                hosts=hosts, labinstances=labinstances)

    for labsinstance in labinstances.values():
        if not labsinstance.connect:
            logging.error(
                'There were problems connecting to instance %s, please fix those problems first and then rerun this script.' %
                labsinstance)
        else:
            logging.error(
                '%s does not yet seem to be ready for migration to eqiad. Please fix the %d identified problems.' %
                (labsinstance, labsinstance.count_errors()))
            logging.info('Summary of failed tasks:')
            problems = 1
            for task in labinstance.tasks:
                result = getattr(labsinstance, task)
                if not result:
                    logging.info('Problem %d: task %s [FAIL]' %
                                 (problems, task))
                    problems += 1
            if problems == 1:
                logging.info('Congratulations! %s seems ready for migration!' %
                             labinstance)


run = logged(run)


def main():
    print 'You should not run this script directly but instead call it as:'
    print 'fab migrate_ready --set wiki_username=YOUR_WIKI_USERNAME'
    print
    print 'The wiki that we are referring to is Wikitech.'
    print 'You might need to pass additional paramaters like your password for your SSH key, but this'
    print 'depends on the actual setup of your system.'
    print 'For an overview of possible parameters run fab --help'
    exit(-1)

if __name__ == '__main__':
    main()
