#!/usr/bin/env python

from distutils.core import setup

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name='vagrant_worker',
    version='0.5.2',
    description='Service to call vagrant actions',
    author='Pierre Paul Lefebvre',
    author_email='info@pierre-paul.com',
    install_requires=required,
    url='https://jeto.io',
    packages=['vagrant_worker'],
    data_files=[
        ('bin', ['vagrant_worker/worker.py']),
    ],
)
