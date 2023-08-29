.. _dev-quickstart:

=====================
Developer Quick-Start
=====================

This is a quick walkthrough to get you started developing code for Ironic.
This assumes you are already familiar with submitting code reviews to
an OpenStack project. If you are not, please begin by following the steps
in the
`OpenDev infra manual <https://docs.opendev.org/opendev/infra-manual/latest/gettingstarted.html>`_
to get yourself familiar with the general git workflow we use.

This guide is primarily technical in nature; for information on how the Ironic
team organizes work, please see `Ironic's contribution guide <https://docs.openstack.org/ironic/latest/contributor/contributing.html>`_.

This document covers both :ref:`unit` and :ref:`integrated`. New contributors
are recommended to start with unit tests.

.. _integrated:

Integrated Testing Environments
-------------------------------
The ultimate in development environments for Ironic is a working system, with
mock bare metal hardware and a fully functional API service. There are three
ways to get environment, listed below.

.. note::
  These environments may use automation that assume you are running on a VM.
  Please do not use these environments on a system that you are not willing to
  have wiped and reinstalled when complete.

.. list-table:: Testing Environments
  :widths: 15, 70, 15

  * - Environment
    - Description/Uses
    - How-To
  * - Devstack
    - Useful for testing Ironic with other OpenStack services. Also the
      environment required for running or building Ironic's tempest tests.
      Recommended for new contributors.
    - :doc:`devstack-guide`
  * - Bifrost
    - Used for testing Ironic standalone with minimal setup or using real
      hardware, or testing bifrost changes directly.
    - :doc:`bifrost-dev-guide`
  * - Local
    - Ironic services running locally, without any other OpenStack services.
      This can be useful for rapid prototyping, debugging, or testing database
      migrations.
    - :doc:`local-dev-guide`

.. _unit:

Unit Testing Environment
------------------------
For most people, unit testing is the quickest and easiest way to check
the validity of a change. Unlike a fully integrated testing environment,
unit tests can generally be safely run on a developer's workstation.

Ironic uses `tox <https://tox.readthedocs.io/en/latest/>`_ to orchestrate unit
tests and documentation building. Contributors are strongly encouraged to
validate code passes unit tests under a supported version of python before
pushing up a change. See the
`Project Testing Interface <https://governance.openstack.org/tc/reference/pti/python.html>`_
for the exact versions of python supported currently.

System Prerequisites
====================

The following packages cover the prerequisites for a local development
environment on most current distributions.

- Ubuntu/Debian::

    sudo apt-get install build-essential python3-dev libssl-dev python3-pip libmysqlclient-dev libxml2-dev libxslt-dev libpq-dev git git-review libffi-dev gettext ipmitool psmisc graphviz libjpeg-dev

- RHEL/CentOS/Fedora::

    sudo dnf install python3-devel openssl-devel python3-pip mysql-devel libxml2-devel libxslt-devel postgresql-devel git git-review libffi-devel gettext ipmitool psmisc graphviz gcc libjpeg-turbo-devel

- openSUSE/SLE::

    sudo zypper install git git-review libffi-devel libmysqlclient-devel libopenssl-devel libxml2-devel libxslt-devel postgresql-devel python3-devel python-nose python3-pip gettext-runtime psmisc

To run the tests locally, it is a requirement that your terminal emulator
supports unicode with the ``en_US.UTF8`` locale. If you use locale-gen to
manage your locales, make sure you have enabled ``en_US.UTF8`` in
``/etc/locale.gen`` and rerun ``locale-gen``.

Python Prerequisites
====================

We suggest to use at least tox 3.9, if your distribution has an older version,
you can install it using pip system-wise or better per user using the --user
option that by default will install the binary under $HOME/.local/bin, so you
need to be sure to have that path in $PATH; for example::

    pip install tox --user

will install tox as ~/.local/bin/tox

You may need to explicitly upgrade virtualenv if you've installed the one
from your OS distribution and it is too old (tox will complain). You can
upgrade it individually, if you need to::

    pip install --upgrade virtualenv --user

Running Unit Tests Locally
==========================

If you haven't already, Ironic source code should be pulled directly from git::

    # from a user-writable directory, usually $HOME or $HOME/dev
    git clone https://opendev.org/openstack/ironic
    cd ironic


Most of the time, you will want to run unit tests and pep8 checks. This can be
done with the following command::

    tox -e pep8,py3

Ironic has multiple test environments that can be run by tox. An incomplete
list of environments and what they do is below. Please reference the ``tox.ini``
file in the project you're working on for a complete, up-to-date list.

.. list-table:: Tox Environments
  :widths: 20, 80

  * - Environment
    - Description
  * - pep8
    - Run style checks on code, documentation, and release notes.
  * - py<version>
    - Run unit tests with the specified python version. For example, ``py310`` will run the unit tests with python 3.10.
  * - unit-with-driver-libs
    - Run unit tests with the default python3 on the system, but also includes driver-specific libraries and the tests they enable.
  * - mysql-migrations
    - Run MySQL database migration unit tests. Setup database first using ``tools/test-setup.sh`` in Ironic repo.
  * - docs
    - Build and validate documentation.
  * - releasenotes
    - Build and validate release notes using ``reno``.
  * - api-ref
    - Build and validate API reference documentation.
  * - genconfig
    - Generates example configuration file.
  * - genpolicy
    - Generates example policy configuration file.
  * - venv
    - Creates a venv, with dependencies installed, for running commands in e.g. ``tox -evenv -- reno new my-release-note``


You may also pass options to the test programs using positional arguments.
To run a specific unit test, this passes the desired test
(regex string) to `stestr <https://pypi.org/project/stestr>`_::

    # run a specific test for Python 3.10
    tox -epy310 -- test_conductor

Debugging unit tests
====================

In order to break into the debugger from a unit test we need to insert
a breaking point to the code:

.. code-block:: python

  import pdb; pdb.set_trace()

Then run ``tox`` with the debug environment as one of the following::

  tox -e debug
  tox -e debug test_file_name
  tox -e debug test_file_name.TestClass
  tox -e debug test_file_name.TestClass.test_name

For more information see the
:oslotest-doc:`oslotest documentation <user/features.html#debugging-with-oslo-debug-helper>`.


Other tests
===========
Ironic also has a number of tests built with Tempest. For more information
about writing or running those tests, see :ref:`tempest`.


OSProfiler Tracing in Ironic
----------------------------

OSProfiler is an OpenStack cross-project profiling library. It is being
used among OpenStack projects to look at performance issues and detect
bottlenecks. For details on how OSProfiler works and how to use it in ironic,
please refer to `OSProfiler Support Documentation <osprofiler-support>`_.


Building developer documentation
--------------------------------

If you would like to build the documentation locally, eg. to test your
documentation changes before uploading them for review, run these
commands to build the documentation set:

- On the machine with the ironic checkout::

    # change into the ironic source code directory
    cd ~/ironic

    # build the docs
    tox -edocs

To view the built documentation locally, open up the top level index.html in
your browser. For an example user named ``bob`` with the Ironic checkout in
their homedir, the URL to put in the browser would be::

    file:///home/bob/ironic/doc/build/html/index.html

If you're building docs on a remote VM, you can use python's SimpleHTTPServer
to setup a quick webserver to check your docs build::

    # Change directory to the newly built HTML files
    cd ~/ironic/doc/build/html/

    # Create a server using python on port 8000
    python -m SimpleHTTPServer 8000

    # Now use your browser to open the top-level index.html located at:
    http://remote_ip:8000
