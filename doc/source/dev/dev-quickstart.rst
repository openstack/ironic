.. _dev-quickstart:

=====================
Developer Quick-Start
=====================

This is a quick walkthrough to get you started developing code for Ironic.
This assumes you are already familiar with submitting code reviews to
an OpenStack project.

.. seealso::

    https://wiki.openstack.org/wiki/GerritWorkflow

Install prerequisites::

    # Ubuntu/Debian:
    sudo apt-get install python-dev libssl-dev python-pip libmysqlclient-dev libxml2-dev libxslt-dev libpq-dev git git-review

    # Fedora/RHEL:
    sudo yum install python-devel openssl-devel python-pip mysql-devel libxml2-devel libxslt-devel postgresql-devel git git-review

    sudo easy_install nose
    sudo pip install virtualenv setuptools-git flake8 tox testrepository

You may need to explicitly upgrade virtualenv if you've installed the one
from your OS distribution and it is too old (tox will complain). You can
upgrade it individually, if you need to::

    sudo pip install -U virtualenv

Ironic source code should be pulled directly from git::

    # from your home or source directory
    cd ~
    git clone https://git.openstack.org/openstack/ironic
    cd ironic

Set up a local environment for development and testing should be done with tox::

    # create a virtualenv for development
    tox -evenv -- echo 'done'

Activate the virtual environment whenever you want to work in it.
All further commands in this section should be run with the venv active::

    source .tox/venv/bin/activate

All unit tests should be run using tox. To run Ironic's entire test suite::

    # run all tests (unit and pep8)
    tox

To run a specific test, use a positional argument for the unit tests::

    # run a specific test for both Python 2.6 and 2.7
    tox -epy26,py27 -- test_conductor

You may pass options to the test programs using positional arguments::

    # run all the Python 2.7 unit tests (in parallel!)
    tox -epy27 -- --parallel

To run only the pep8/flake8 syntax and style checks::

    tox -epep8

When you're done, deactivate the virtualenv::

    deactivate

===============================
Exercising the Services Locally
===============================

If you would like to exercise the Ironic services in isolation within a local
virtual environment, you can do this without starting any other OpenStack
services. For example, this is useful for rapidly prototyping and debugging
interactions over the RPC channel, testing database migrations, and so forth.

First, install a few system prerequisites::

    # install rabbit message broker
    # Ubuntu/Debian:
    sudo apt-get install rabbitmq-server

    # Fedora/RHEL:
    sudo yum install rabbitmq-server
    sudo service rabbitmq-server start

    # optionally, install mysql-server

    # Ubuntu/Debian:
    # sudo apt-get install mysql-server

    # Fedora/RHEL:
    # sudo yum install mysql-server
    # sudo service mysqld start

Next, clone the client and install it within a virtualenv as well::

    # from your home or source directory
    cd ~
    git clone https://git.openstack.org/openstack/python-ironicclient
    cd python-ironicclient
    tox -evenv -- echo 'done'
    source .tox/venv/bin/activate
    python setup.py develop

Export some ENV vars so the client will connect to the local services
that you'll start in the next section::

    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://localhost:6385/

Open another window (or screen session) and activate the virtual environment
created in the previous section to run everything else within::

    # activate the virtualenv
    cd ironic
    source .tox/venv/bin/activate

    # install ironic within the virtualenv
    python setup.py develop

    # copy sample config and modify it as necessary
    cp etc/ironic/ironic.conf.sample etc/ironic/ironic.conf.local

    # disable auth since we are not running keystone here
    sed -i "s/#auth_strategy=keystone/auth_strategy=noauth/" etc/ironic/ironic.conf.local

    # set a fake host name [useful if you want to test multiple services on the same host]
    sed -i "s/#host=.*/host=test-host/" etc/ironic/ironic.conf.local

    # initialize the ironic database
    # this defaults to storing data in ./ironic/openstack/common/db/ironic.sqlite

    # If using MySQL, you need to create the initial database
    # mysql -u root -e "create schema ironic"
    # and switch the DB connection from sqlite to something else, eg. mysql
    # sed -i "s/#connection=.*/connection=mysql:\/\/root@localhost\/ironic/" etc/ironic/ironic.conf.local

    ironic-dbsync --config-file etc/ironic/ironic.conf.local

Start the API service in debug mode and watch its output::

    # start the API service
    ironic-api -v -d --config-file etc/ironic/ironic.conf.local

Open one more window (or screen session), again activate the venv, and then
start the conductor service and watch its output::

    # activate the virtualenv
    cd ironic
    source .tox/venv/bin/activate

    # start the conductor service
    ironic-conductor -v -d --config-file etc/ironic/ironic.conf.local

You should now be able to interact with Ironic via the python client (installed
in the first window) and observe both services' debug outputs in the other two
windows. This is a good way to test new features or play with the functionality
without necessarily starting devstack.

To get started, list the available commands and resources::

    # get a list of available commands
    ironic help

    # get the list of drivers currently supported by the available conductor(s)
    ironic driver-list

    # get a list of nodes (should be empty at this point)
    ironic node-list

Here is an example walkthrough of creating a node::

    MAC="aa:bb:cc:dd:ee:ff"   # replace with the MAC of a data port on your node
    IPMI_ADDR="1.2.3.4"       # replace with a real IP of the node BMC
    IPMI_USER="admin"         # replace with the BMC's user name
    IPMI_PASS="pass"          # replace with the BMC's password

    # enroll the node with the "fake" deploy driver and the "ipmitool" power driver
    # Note that driver info may be added at node creation time with "-i"
    NODE=$(ironic node-create -d fake_ipmitool -i ipmi_address=$IPMI_ADDR -i ipmi_username=$IPMI_USER | grep ' uuid ' | awk '{print $4}')

    # driver info may also be added or updated later on
    ironic node-update $NODE add driver_info/ipmi_password=$IPMI_PASS

    # add a network port
    ironic port-create -n $NODE -a $MAC

    # view the information for the node
    ironic node-show $NODE

    # request that the node's driver validate the supplied information
    ironic node-validate $NODE

    # you have now enrolled a node sufficiently to be able to control
    # its power state from ironic!
    ironic node-set-power-state $NODE on

If you make some code changes and want to test their effects,
install again with "python setup.py develop", stop the services
with Ctrl-C, and restart them.

================================
Building developer documentation
================================

If you would like to build the documentation locally, eg. to test your
documentation changes before uploading them for review, run these
commands to build the documentation set::

    # activate your development virtualenv
    source .tox/venv/bin/activate

    # build the docs
    python setup.py build_sphinx

Now use your browser to open the top-level index.html located at::

    ironic/doc/build/html/index.html
