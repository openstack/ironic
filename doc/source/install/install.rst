Install and configure the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to install and configure the
Bare Metal service, code-named ironic, manually from packages on one of the
three popular families of Linux distributions.

Alternatively, you can use one of the numerous projects that install ironic.
One of them is provided by the bare metal team:

* `Bifrost <https://docs.openstack.org/bifrost/latest/>`_ installs ironic in
  the standalone mode (without the rest of OpenStack).

More installation projects are developed by other OpenStack teams:

* `Kolla
  <https://docs.openstack.org/kolla-ansible/latest/reference/bare-metal/ironic-guide.html>`_
  can install ironic in containers as part of OpenStack.
* OpenStack-Ansible has a `role to install ironic
  <https://docs.openstack.org/openstack-ansible-os_ironic/latest/>`_.
* TripleO uses ironic for provisioning bare metal nodes and can also be used
  `to install ironic
  <https://docs.openstack.org/project-deploy-guide/tripleo-docs/latest/features/baremetal_overcloud.html>`_.

.. NOTE(dtantsur): add your favourite installation tool, but please link to the
   **Ironic guide**, not to the generic page. If a separate Ironic guide does
   not exist yet, create it first.

Contents
--------

.. toctree::
   :maxdepth: 2

   install-rdo.rst
   install-ubuntu.rst
   install-obs.rst
