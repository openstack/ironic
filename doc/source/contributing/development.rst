.. _development:

===========
Development
===========

This is a quick walkthrough to get you started developing code for Ironic.
For a guide on using OpenStack's code review system (Gerrit), see:

    https://wiki.openstack.org/wiki/GerritWorkflow

===========
Walkthrough
===========

Ironic source code should be pulled directly from git::

    cd <your source dir>
    git clone https://github.com/openstack/ironic
    cd ironic

Install prerequisites::

    # Ubuntu/Debian:
    sudo apt-get install python-dev swig libssl-dev python-pip libmysqlclient-dev libxml2-dev libxslt-dev

    # Fedora/RHEL:
    sudo yum install python-devel swig openssl-devel python-pip mysql-libs libxml2-devel libxslt-devel

    sudo easy_install nose
    sudo pip install virtualenv setuptools-git flake8 tox

Setting up a local environment for development can be done with tox::

    # create virtualenv
    tox -evenv -- echo 'done'

    # activate the virtualenv
    source .tox/venv/bin/activate

    # run testr init
    testr init

To run the pep8/flake8 syntax and style checks::

    # run pep8/flake8 checks
    flake8

To run Ironic's unit test suite::

    # run unit tests
    testr run

When you're done, to leave the venv::

    # deactivate the virtualenv
    deactivate
