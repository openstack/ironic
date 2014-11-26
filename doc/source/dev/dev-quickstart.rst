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
    sudo apt-get install python-dev libssl-dev python-pip libmysqlclient-dev libxml2-dev libxslt-dev libpq-dev git git-review libffi-dev gettext python-tox

    # Fedora/RHEL:
    sudo yum install python-devel openssl-devel python-pip mysql-devel libxml2-devel libxslt-devel postgresql-devel git git-review libffi-devel gettext ipmitool

    # openSUSE/SLE 12:
    sudo zypper install git git-review libffi-devel libmysqlclient-devel libopenssl-devel libxml2-devel libxslt-devel postgresql-devel python-devel python-flake8 python-nose python-pip python-setuptools-git python-testrepository python-tox python-virtualenv gettext-runtime

    sudo easy_install nose
    sudo pip install virtualenv setuptools-git flake8 tox testrepository

If using RHEL and yum reports “No package python-pip available” and “No
package git-review available”, use the EPEL software repository. Instructions
can be found at `<http://fedoraproject.org/wiki/EPEL/FAQ#howtouse>`_.

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

    # run a specific test for Python 2.7
    tox -epy27 -- test_conductor

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

    # openSUSE/SLE 12:
    sudo zypper install rabbitmq-server
    sudo systemctl start rabbitmq-server.service

    # optionally, install mysql-server

    # Ubuntu/Debian:
    # sudo apt-get install mysql-server

    # Fedora/RHEL:
    # sudo yum install mysql-server
    # sudo service mysqld start

    # openSUSE/SLE 12:
    # sudo zypper install mariadb
    # sudo systemctl start mysql.service

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

    # Use the 'fake_ipmitool' test driver
    sed -i "s/#enabled_drivers=pxe_ipmitool/enabled_drivers=fake_ipmitool/" etc/ironic/ironic.conf.local

    # set a fake host name [useful if you want to test multiple services on the same host]
    sed -i "s/#host=.*/host=test-host/" etc/ironic/ironic.conf.local

    # turn off the periodic sync_power_state task, to avoid getting NodeLocked exceptions
    sed -i "s/#sync_power_state_interval=60/sync_power_state_interval=-1/" etc/ironic/ironic.conf.local

    # initialize the ironic database
    # this defaults to storing data in ./ironic/ironic.sqlite

    # If using MySQL, you need to create the initial database
    # mysql -u root -e "create schema ironic"
    # and switch the DB connection from sqlite to something else, eg. mysql
    # sed -i "s/#connection=.*/connection=mysql:\/\/root@localhost\/ironic/" etc/ironic/ironic.conf.local

    # This creates the database tables.
    ironic-dbsync --config-file etc/ironic/ironic.conf.local create_schema

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
without necessarily starting DevStack.

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
Deploying Ironic with DevStack
================================

DevStack may be configured to deploy Ironic, setup Nova to use the Ironic
driver and provide hardware resources (network, baremetal compute nodes)
using a combination of OpenVSwitch and libvirt.  It is highly recommended
to deploy on an expendable virtual machine and not on your personal work
station.  Deploying Ironic with DevStack requires a machine running Ubuntu
14.04 (or later) or Fedora 20 (or later).

.. seealso::

    https://devstack.org

Devstack will no longer create the user 'stack' with the desired
permissions, but does provide a script to perform the task::

    git clone https://github.com/openstack-dev/devstack.git devstack
    sudo ./devstack/tools/create-stack-user.sh

Switch to the stack user and clone DevStack::

    sudo su stack
    cd ~
    git clone https://github.com/openstack-dev/devstack.git devstack

Create devstack/localrc with minimal settings required to enable Ironic.
Note that Ironic under devstack can only support running *either* the PXE
or the agent driver, not both.::

    cd devstack
    cat >localrc <<END
    # Credentials
    ADMIN_PASSWORD=password
    DATABASE_PASSWORD=password
    RABBIT_PASSWORD=password
    SERVICE_PASSWORD=password
    SERVICE_TOKEN=password

    # Enable Ironic API and Ironic Conductor
    enable_service ironic
    enable_service ir-api
    enable_service ir-cond

    # Enable Neutron which is required by Ironic and disable nova-network.
    disable_service n-net
    enable_service q-svc
    enable_service q-agt
    enable_service q-dhcp
    enable_service q-l3
    enable_service q-meta
    enable_service neutron

    # Create 3 virtual machines to pose as Ironic's baremetal nodes.
    IRONIC_VM_COUNT=3
    IRONIC_VM_SSH_PORT=22
    IRONIC_BAREMETAL_BASIC_OPS=True

    # The parameters below represent the minimum possible values to create
    # functional nodes.
    IRONIC_VM_SPECS_RAM=1024
    IRONIC_VM_SPECS_DISK=10

    # Size of the ephemeral partition in GB. Use 0 for no ephemeral partition.
    IRONIC_VM_EPHEMERAL_DISK=0

    VIRT_DRIVER=ironic

    # By default, DevStack creates a 10.0.0.0/24 network for instances.
    # If this overlaps with the hosts network, you may adjust with the
    # following.
    NETWORK_GATEWAY=10.1.0.1
    FIXED_RANGE=10.1.0.0/24
    FIXED_NETWORK_SIZE=256

    # Log all output to files
    LOGFILE=$HOME/devstack.log
    SCREEN_LOGDIR=$HOME/logs
    IRONIC_VM_LOG_DIR=$HOME/ironic-bm-logs

    END

If running with the agent driver::

    cat >>localrc <<END
    # Agent driver requires swift with tempurls
    # Enable swift services
    enable_service s-proxy
    enable_service s-object
    enable_service s-container
    enable_service s-account

    # Enable tempurls and set credentials
    SWIFT_HASH=password
    SWIFT_TEMPURL_KEY=password
    SWIFT_ENABLE_TEMPURLS=True

    # Enable agent driver
    IRONIC_ENABLED_DRIVERS=fake,agent_ssh,agent_ipmitool
    IRONIC_DEPLOY_DRIVER=agent_ssh

    # To build your own IPA ramdisk from source, set this to True
    IRONIC_BUILD_DEPLOY_RAMDISK=False

    END

Run stack.sh::

    ./stack.sh

Source credentials, create a key, and spawn an instance::

    source ~/devstack/openrc

    # query the image id of the default cirros image
    image=$(nova image-list | egrep "$DEFAULT_IMAGE_NAME"'[^-]' | awk '{ print $2 }')

    # create keypair
    ssh-keygen
    nova keypair-add default --pub-key ~/.ssh/id_rsa.pub

    # spawn instance
    nova boot --flavor baremetal --image $image --key-name default testing

As the demo tenant, you should now see a Nova instance building::

    nova list
    +--------------------------------------+---------+--------+------------+-------------+----------+
    | ID                                   | Name    | Status | Task State | Power State | Networks |
    +--------------------------------------+---------+--------+------------+-------------+----------+
    | a2c7f812-e386-4a22-b393-fe1802abd56e | testing | BUILD  | spawning   | NOSTATE     |          |
    +--------------------------------------+---------+--------+------------+-------------+----------+

Nova will be interfacing with Ironic conductor to spawn the node.  On the
Ironic side, you should see an Ironic node associated with this Nova instance.
It should be powered on and in a 'wait call-back' provisioning state::

    # Note that 'ironic' calls must be made with admin credentials
    . ~/devstack/openrc admin admin
    ironic node-list
    +--------------------------------------+--------------------------------------+-------------+--------------------+
    | UUID                                 | Instance UUID                        | Power State | Provisioning State |
    +--------------------------------------+--------------------------------------+-------------+--------------------+
    | 9e592cbe-e492-4e4f-bf8f-4c9e0ad1868f | None                                 | power off   | None               |
    | ec0c6384-cc3a-4edf-b7db-abde1998be96 | None                                 | power off   | None               |
    | 4099e31c-576c-48f8-b460-75e1b14e497f | a2c7f812-e386-4a22-b393-fe1802abd56e | power on    | wait call-back     |
    +--------------------------------------+--------------------------------------+-------------+--------------------+

At this point, Ironic conductor has called to libvirt via SSH to power on a
virtual machine, which will PXE + TFTP boot from the conductor node and
progress through the Ironic provisioning workflow.  One libvirt domain should
be active now::

    sudo virsh list --all
     Id    Name                           State
    ----------------------------------------------------
     2     baremetalbrbm_2                running
     -     baremetalbrbm_0                shut off
     -     baremetalbrbm_1                shut off

This provisioning process may take some time depending on the performance of
the host system, but Ironic should eventually show the node as having an
'active' provisioning state::

    ironic node-list
    +--------------------------------------+--------------------------------------+-------------+--------------------+
    | UUID                                 | Instance UUID                        | Power State | Provisioning State |
    +--------------------------------------+--------------------------------------+-------------+--------------------+
    | 9e592cbe-e492-4e4f-bf8f-4c9e0ad1868f | None                                 | power off   | None               |
    | ec0c6384-cc3a-4edf-b7db-abde1998be96 | None                                 | power off   | None               |
    | 4099e31c-576c-48f8-b460-75e1b14e497f | a2c7f812-e386-4a22-b393-fe1802abd56e | power on    | active             |
    +--------------------------------------+--------------------------------------+-------------+--------------------+

This should also be reflected in the Nova instance state, which at this point
should be ACTIVE, Running and an associated private IP::

    # Note that 'nova' calls must be made with the credentials of the demo tenant
    . ~/devstack/openrc demo demo
    nova list
    +--------------------------------------+---------+--------+------------+-------------+------------------+
    | ID                                   | Name    | Status | Task State | Power State | Networks         |
    +--------------------------------------+---------+--------+------------+-------------+------------------+
    | a2c7f812-e386-4a22-b393-fe1802abd56e | testing | ACTIVE | -          | Running     | private=10.1.0.4 |
    +--------------------------------------+---------+--------+------------+-------------+------------------+

The server should now be accessible via SSH::

    ssh cirros@10.1.0.4
    $

================================
Building developer documentation
================================

If you would like to build the documentation locally, eg. to test your
documentation changes before uploading them for review, run these
commands to build the documentation set::

    # activate your development virtualenv
    source .tox/venv/bin/activate

    # build the docs
    tox -egendocs

Now use your browser to open the top-level index.html located at::

    ironic/doc/build/html/index.html
