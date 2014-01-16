#!/usr/bin/env python
# follow the frog

from setuptools import setup
from pip.req import parse_requirements

# parse_requirements() returns generator of pip.req.InstallRequirement objects
install_reqs = parse_requirements('requirements.txt')

# reqs is a list of requirement
# e.g. ['flask==0.9', 'sqlalchemye==0.8.1']
reqs = [str(ir.req) for ir in install_reqs]

setup(
    name='labs-migration-assistant',
    version='0.0.1',
    description='A simple script to assess how ready a Wikimedia Labs instance is to be migrated from the Tampa dc to the Eqiad dc. ',
    url='http://www.github.com/dvanliere/labs-migration-assistant',
    author='Diederik van Liere',
    packages=[
        'labs-migration-assistant',
    ],
    install_requires=reqs,
    # entry_points={
    #     'console_scripts': [
    #         'wikimetrics = wikimetrics.run:main'
    #     ]
    # },
)
