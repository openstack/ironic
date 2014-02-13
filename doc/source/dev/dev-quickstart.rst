.. _dev-quickstart:

=====================
Developer Quick-Start
=====================

This is a quick walkthrough to get you started developing code for Ironic.
This assumes you are already familiar with submitting code reviews to
an OpenStack project.

.. seealso::

    https://wiki.openstack.org/wiki/GerritWorkflow

Ironic source code should be pulled directly from git::

    cd <your source dir>
    git clone https://github.com/openstack/ironic
    cd ironic

Install prerequisites::

    # Ubuntu/Debian:
    sudo apt-get install python-dev swig libssl-dev python-pip libmysqlclient-dev libxml2-dev libxslt-dev libpq-dev git

    # Fedora/RHEL:
    sudo yum install python-devel swig openssl-devel python-pip mysql-devel libxml2-devel libxslt-devel postgresql-devel git

    sudo easy_install nose
    sudo pip install virtualenv setuptools-git flake8 tox

Setting up a local environment for development can be done with tox::

    # create virtualenv
    tox -evenv -- echo 'done'

    # activate the virtualenv
    source .tox/venv/bin/activate

    # install requirements within the virtualenv
    pip install -U -r requirements.txt test-requirements.txt

    # initialize testr
    testr init

To run the pep8/flake8 syntax and style checks::

    # run pep8/flake8 checks
    flake8

To run Ironic's unit test suite::

    # run all the unit tests
    testr run

    # to run specific tests only, specify the file, module or test name, eg:
    testr run test_conductor

When you're done::

    # deactivate the virtualenv
    deactivate

===============================
Exercising the Services Locally
===============================

If you would like to exercise the Ironic services in isolation within a local
virtual environment, you can do this without starting any other OpenStack
services. For example, this is useful for rapidly prototyping and debugging
interactions over the RPC channel, testing database migrations, and so forth.

First, install prerequisites::

    # install rabbit message broker
    # Ubuntu/Debian:
    sudo apt-get install rabbitmq-server

    # Fedora/RHEL:
    sudo yum install rabbitmq-server

    # install ironic CLI
    sudo pip install python-ironicclient

Then, activate the virtual environment created in the previous section, and run
everything else within that::

    # enter the ironic directory
    cd <your source dir>
    cd ironic

    # activate the virtualenv
    source .tox/venv/bin/activate
    
    # install ironic within the virtualenv
    python setup.py develop

    # initialize the ironic database; this defaults to storing data in
    # ./ironic/openstack/common/db/ironic.sqlite
    ironic-dbsync

    # copy sample config and modify it as necessary
    cp etc/ironic/ironic.conf.sample etc/ironic/ironic.conf.local
    cat >> etc/ironic/ironic.conf.local <<EOL
    host = test-host
    auth_strategy = noauth
    EOL

    # start services and observe their output
    # for each service, open a separate window and active the virtualenv in it
    ironic-api -v -d --config-file etc/ironic/ironic.conf.local
    ironic-conductor -v -d --config-file etc/ironic/ironic.conf.local

    # export ENV vars so ironic client connects to the local services
    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://localhost:6385/

    # you should now be able to query the Ironic API
    # and see a list of supported drivers on "test-host"
    ironic driver-list

    # enroll nodes with the "fake" driver, eg:
    ironic node-create -d fake

    # if you make some code changes and want to test their effects,
    # install again with "python setup.py develop", stop the services
    # with Ctrl-C, and restart them.

================================
Building developer documentation
================================

If you would like to build the documentation locally, eg. to test your
documentation changes before uploading them for review, you should install and
configure Apache to serve the output. Below are some basic instructions.  This
guide does not cover the many ways one can configure Apache, nor does it
address security issues with running a web server on your laptop.
(In other words, you might want to do this in a VM.)

::

    # Install Apache on Ubuntu/Debian
    sudo apt-get install apache2

    # Install Apache on Fedora/RHEL
    sudo yum install httpd
    sudo systemctl start httpd

    # Add symlink to build output. For this example, let's assume your
    # Apache DocumentRoot is /var/www and ironic source is at /opt/stack/ironic
    cd /var/www
    sudo ln -s /opt/stack/ironic/doc/build/html ironic
    cd /opt/stack/ironic

    # build the documentation
    source .tox/venv/bin/activate
    python setup.py build_sphinx

    # open a web browser pointed to http://localhost/ironic/index.html
