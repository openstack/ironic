Ironic
======

Ironic is an Incubated OpenStack project which aims to provision
bare metal machines instead of virtual machines, forked from the
Nova Baremetal driver. It is best thought of as a bare metal
hypervisor **API** and a set of plugins which interact with
the bare metal hypervisors. By default, it will use PXE and IPMI
in concert to provision and turn on/off machines, but Ironic
also supports vendor-specific plugins which may implement additional
functionality.

-----------------
Project Resources
-----------------

Project status, bugs, and blueprints are tracked on Launchpad:

  http://launchpad.net/ironic

Additional resources are linked from the project wiki page:

  https://wiki.openstack.org/wiki/Ironic

Developers wishing to contribute to an OpenStack project should
find plenty of helpful resources here:

  https://wiki.openstack.org/wiki/Getting_Started

All OpenStack projects use Gerrit for code reviews.
A good reference for that is here:

  https://wiki.openstack.org/wiki/GerritWorkflow

--------------------
Project Architecture
--------------------

An Ironic deployment will be composed of the following components:

- A **RESTful API** service, by which operators and other services
  may interact with the managed bare metal servers.
- A **Manager** service, which does the bulk of the work. Functionality
  is exposed via the API service.
  The Manager and API services communicate via RPC.
- An internal **driver API** for different Manager functions.
  There are currently two driver types: BMCDriver and DeploymentDriver.
- Internal drivers for each function are dynamically loaded, according to the
  specific hardware being managed, such that heterogeneous hardware deployments
  can be managed by a single Manager service.
- One or more **Deployment Agents**, which provide local control over
  the hardware which is not available remotely to the Manager.
  A ramdisk should be built which contains one of these agents, eg. with
  https://github.com/stackforge/diskimage-builder, and this ramdisk can be
  booted on-demand. The agent is never run inside a tenant instance.
- A **Database** and a DB API for storing persistent state of the Manager and Drivers.


In addition to the two types of drivers, BMCDriver and DeploymentDriver, there
are three categories of driver functionality: core, common, and vendor:

- "Core" functionality represents the minimal API for that driver type, eg.
  power on/off for a BMCDriver.
- "Common" functionality represents an extended but supported API, and any
  driver which implements it must be consistent with all other driver
  implementations of that functionality. For example, if a driver supports
  enumerating PCI devices, it must return that list as well-structured JSON. In
  this case, Ironic may validate the API input's structure, but will pass it
  unaltered to the driver. This ensures compatibility for common features
  across drivers.
- "Vendor" functionality allows an excemption to the API contract when a vendor
  wishes to expose unique functionality provided by their hardware and is
  unable to do so within the core or common APIs. In this case, Ironic will
  neither store nor introspect the messages passed between the API and the
  driver.


-----------
Development
-----------

Ironic source code should be pulled directly from git::

  git clone https://github.com/openstack/ironic

Setting up a local environment for development can be done with tox::

    cd <your_src_dir>/ironic

    # install prerequisites
    * Ubuntu/Debian:
    sudo apt-get install python-dev swig libssl-dev python-pip libmysqlclient-dev libxml2-dev libxslt-dev
    * Fedora/RHEL:
    sudo yum install python-devel swig openssl-devel python-pip mysql-libs libxml2-devel libxslt-devel

    sudo easy_install nose
    sudo pip install virtualenv setuptools-git flake8 tox

    # create virtualenv
    tox -evenv -- echo 'done'

    # activate the virtualenv
    source .tox/venv/bin/activate

    # run testr init
    testr init

    # run pep8/flake8 checks
    flake8

    # run unit tests
    testr run

    # deactivate the virtualenv
    deactivate

