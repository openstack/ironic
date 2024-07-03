Exercising Ironic Services Locally
==================================

It can sometimes be helpful to run Ironic services locally, without needing a
full devstack environment or a server in a remote datacenter.

If you would like to exercise the Ironic services in isolation within your local
environment, you can do this without starting any other OpenStack services. For
example, this is useful for rapidly prototyping and debugging interactions between
client and API, exploring the Ironic API for the first time, and basic testing.

This guide assumes you have already installed all required Ironic prerequisites,
as documented in the prerequisites section of :ref:`unit`.

Using tox
_________
Ironic provides a tox environment suitable for running a single-process Ironic
against sqlite. This utilizes the config in ``tools/ironic.conf.localdev`` to
setup a simple, all-in-one Ironic service useful for testing.

By default, this configuration uses sqlite with a backing file
``ironic/ironic.sqlite``. Deleting this file and restarting ironic will reset
you to a blank state.

Setup
-----

#. If you haven't already downloaded the source code, do that first::

    cd ~
    git clone https://opendev.org/openstack/ironic
    cd ironic

#. Run the ironic all-in-one process::

    tox -elocal-ironic-dev

#. In another window, utilize the client inside the tox venv::

    . .tox/local-ironic-dev/bin/activate
    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://127.0.0.1:6385
    baremetal driver list

#. Press CTRL+C in the window running ``tox -elocal-ironic-dev`` when you
   are done.

Manually
________

You may wish to do this manually in order to give you more granular control
over library versions and configurations, to enable usage of a database
server backend, or to spin up a non-all-in-one Ironic.

Step 1: Create a Python virtualenv
----------------------------------

#. If you haven't already downloaded the source code, do that first::

    cd ~
    git clone https://opendev.org/openstack/ironic
    cd ironic

#. Create the Python virtualenv::

    tox -elocal-ironic-dev --notest --develop -r

#. Activate the virtual environment::

    . .tox/local-ironic-dev/bin/activate

   .. note:: This installs ``python-openstackclient`` and
             ``python-ironicclient`` from pypi. You can instead install them
             from source by cloning the git repository, activating the venv,
             and running `pip install -e .` while in the root of the git
             repo.

#. Export some ENV vars so the client will connect to the local services
   that you'll start in the next section::

    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://localhost:6385/

Step 2: Install System Dependencies Locally
--------------------------------------------

This step will install MySQL on your local system. This may not be desirable
in some situations (eg, you're developing from a laptop and do not want to run
a MySQL server on it all the time).

#. Install mysql-server:

   Ubuntu/Debian::

       sudo apt-get install mysql-server

   RHEL/CentOS/Fedora::

       sudo dnf install mariadb mariadb-server
       sudo systemctl start mariadb.service

   openSUSE/SLE::
       sudo zypper install mariadb
       sudo systemctl start mysql.service

   If using MySQL, you need to create the initial database::

       mysql -u root -pMYSQL_ROOT_PWD -e "create schema ironic"

#. Use the localdev config as a template, and modify it::

    # copy sample config and modify it as necessary
    cp tools/ironic.conf.localdev etc/ironic/ironic.conf.local

    # Add mysql database connection information to config
    echo -e "\n[database]" >> etc/ironic/ironic.conf.local
    echo -e "connection = mysql+pymysql://root:MYSQL_ROOT_PWD@localhost/ironic" >> etc/ironic/ironic.conf.local

    # disable single-process mode and enable json-rpc
    sed -i "s/rpc_transport = none/rpc_transport = json-rpc/" etc/ironic/ironic.conf.local

Step 3: Start the Services
--------------------------

From within the python virtualenv, run the following command to prepare the
database before you start the ironic services::

    # initialize the database for ironic
    ironic-dbsync --config-file etc/ironic/ironic.conf.local create_schema

Next, open two new terminals for this section, and run each of the examples
here in a separate terminal. In this way, the services will *not* be run as
daemons; you can observe their output and stop them with Ctrl-C at any time.

#. Start the API service in debug mode and watch its output::

    cd ~/ironic
    . .tox/local-ironic-dev/bin/activate
    ironic-api -d --config-file etc/ironic/ironic.conf.local

#. Start the Conductor service in debug mode and watch its output::

    cd ~/ironic
    . .tox/local-ironic-dev/bin/activate
    ironic-conductor -d --config-file etc/ironic/ironic.conf.local

Step 4: Interact with the running services
------------------------------------------

You should now be able to interact with ironic via the python client, which is
present in the python virtualenv, and observe both services' debug outputs in
the other two windows. This is a good way to test new features or play with the
functionality without necessarily starting DevStack.

To get started, export the following variables to point the client at the
local instance of ironic::

    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://127.0.0.1:6385

Then list the available commands and resources::

    # get a list of available commands
    baremetal help

    # get the list of drivers currently supported by the available conductor(s)
    baremetal driver list

    # get a list of nodes (should be empty at this point)
    baremetal node list

Here is an example walkthrough of creating a node::

    # enroll the node with the fake hardware type and IPMI-based power and
    # management interfaces. Note that driver info may be added at node
    # creation time with "--driver-info"
    NODE=$(baremetal node create --driver fake-hardware -f value -c uuid)

    # node info may also be added or updated later on
    baremetal node set $NODE --driver-info fake_driver_info=fake
    baremetal node set $NODE --extra extradata=isfun

    # view the information for the node
    baremetal node show $NODE

    # request that the node's driver validate the supplied information
    baremetal node validate $NODE

    # you have now enrolled a node sufficiently to be able to control
    # its power state from ironic!
    baremetal node power on $NODE

If you make some code changes and want to test their effects, simply stop the
services with Ctrl-C and restart them.

Step 5: Fixing your test environment
------------------------------------

If you are testing changes that add or remove python entrypoints, or making
significant changes to ironic's python modules, or simply keep the virtualenv
around for a long time, your development environment may reach an inconsistent
state. It may help to delete cached ".pyc" files, update dependencies,
reinstall ironic, or even recreate the virtualenv. The following commands may
help with that, but are not an exhaustive troubleshooting guide::

  # clear cached pyc files
  cd ~/ironic/ironic
  find ./ -name '*.pyc' | xargs rm

  # reinstall ironic modules
  cd ~/ironic
  . .tox/local-ironic-dev/bin/activate
  pip uninstall ironic
  pip install -e .

  # install and upgrade ironic and all python dependencies
  cd ~/ironic
  . .tox/local-ironic-dev/bin/activate
  pip install -U -e .

