Exercising Ironic Services Locally
==================================

It can sometimes be helpful to run Ironic services locally, without needing a
full devstack environment or a server in a remote datacenter.

If you would like to exercise the Ironic services in isolation within your local
environment, you can do this without starting any other OpenStack services. For
example, this is useful for rapidly prototyping and debugging interactions over
the RPC channel, testing database migrations, and so forth.

Here we describe two ways to install and configure the dependencies, either run
directly on your local machine or encapsulated in a virtual machine or
container.

Step 1: Create a Python virtualenv
----------------------------------

#. If you haven't already downloaded the source code, do that first::

    cd ~
    git clone https://opendev.org/openstack/ironic
    cd ironic

#. Create the Python virtualenv::

    tox -evenv --notest --develop -r

#. Activate the virtual environment::

    . .tox/venv/bin/activate

#. Install the `openstack` client command utility::

    pip install python-openstackclient


#. Install the `baremetal` client::

    pip install python-ironicclient

   .. note:: You can install python-ironicclient from source by cloning the git
             repository and running `pip install .` while in the root of the
             cloned repository.

#. Export some ENV vars so the client will connect to the local services
   that you'll start in the next section::

    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://localhost:6385/

Next, install and configure system dependencies.

Step 2: Install System Dependencies Locally
--------------------------------------------

This step will install MySQL on your local system. This may not be desirable
in some situations (eg, you're developing from a laptop and do not want to run
a MySQL server on it all the time). If you want to use SQLite, skip it and do
not set the ``connection`` option.

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

   .. note:: if you choose not to install mysql-server, ironic will default to
             using a local sqlite database. The database will then be stored in
             ``ironic/ironic.sqlite``.


#. Create a configuration file within the ironic source directory::

    # generate a sample config
    tox -egenconfig

    # copy sample config and modify it as necessary
    cp etc/ironic/ironic.conf.sample etc/ironic/ironic.conf.local

    # disable auth since we are not running keystone here
    sed -i "s/#auth_strategy = keystone/auth_strategy = noauth/" etc/ironic/ironic.conf.local

    # use the 'fake-hardware' test hardware type
    sed -i "s/#enabled_hardware_types = .*/enabled_hardware_types = fake-hardware/" etc/ironic/ironic.conf.local

    # use the 'fake' deploy and boot interfaces
    sed -i "s/#enabled_deploy_interfaces = .*/enabled_deploy_interfaces = fake/" etc/ironic/ironic.conf.local
    sed -i "s/#enabled_boot_interfaces = .*/enabled_boot_interfaces = fake/" etc/ironic/ironic.conf.local

    # enable both fake and ipmitool management and power interfaces
    sed -i "s/#enabled_management_interfaces = .*/enabled_management_interfaces = fake,ipmitool/" etc/ironic/ironic.conf.local
    sed -i "s/#enabled_power_interfaces = .*/enabled_power_interfaces = fake,ipmitool/" etc/ironic/ironic.conf.local

    # change the periodic sync_power_state_interval to a week, to avoid getting NodeLocked exceptions
    sed -i "s/#sync_power_state_interval = 60/sync_power_state_interval = 604800/" etc/ironic/ironic.conf.local

    # if you opted to install mysql-server, switch the DB connection from sqlite to mysql
    sed -i "s/#connection = .*/connection = mysql\+pymysql:\/\/root:MYSQL_ROOT_PWD@localhost\/ironic/" etc/ironic/ironic.conf.local

    # use JSON RPC to avoid installing rabbitmq locally
    sed -i "s/#rpc_transport = oslo/rpc_transport = json-rpc/" etc/ironic/ironic.conf.local

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
    . .tox/venv/bin/activate
    ironic-api -d --config-file etc/ironic/ironic.conf.local

#. Start the Conductor service in debug mode and watch its output::

    cd ~/ironic
    . .tox/venv/bin/activate
    ironic-conductor -d --config-file etc/ironic/ironic.conf.local

Step 4: Interact with the running services
------------------------------------------

You should now be able to interact with ironic via the python client, which is
present in the python virtualenv, and observe both services' debug outputs in
the other two windows. This is a good way to test new features or play with the
functionality without necessarily starting DevStack.

To get started, export the following variables to point the client at the
local instance of ironic and disable the authentication::

    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://127.0.0.1:6385

Then list the available commands and resources::

    # get a list of available commands
    openstack help baremetal

    # get the list of drivers currently supported by the available conductor(s)
    baremetal driver list

    # get a list of nodes (should be empty at this point)
    baremetal node list

Here is an example walkthrough of creating a node::

    MAC="aa:bb:cc:dd:ee:ff"   # replace with the MAC of a data port on your node
    IPMI_ADDR="1.2.3.4"       # replace with a real IP of the node BMC
    IPMI_USER="admin"         # replace with the BMC's user name
    IPMI_PASS="pass"          # replace with the BMC's password

    # enroll the node with the fake hardware type and IPMI-based power and
    # management interfaces. Note that driver info may be added at node
    # creation time with "--driver-info"
    NODE=$(baremetal node create \
           --driver fake-hardware \
           --management-interface ipmitool \
           --power-interface ipmitool \
           --driver-info ipmi_address=$IPMI_ADDR \
           --driver-info ipmi_username=$IPMI_USER \
           -f value -c uuid)

    # driver info may also be added or updated later on
    baremetal node set $NODE --driver-info ipmi_password=$IPMI_PASS

    # add a network port
    baremetal port create $MAC --node $NODE

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
  . .tox/venv/bin/activate
  pip uninstall ironic
  pip install -e .

  # install and upgrade ironic and all python dependencies
  cd ~/ironic
  . .tox/venv/bin/activate
  pip install -U -e .

