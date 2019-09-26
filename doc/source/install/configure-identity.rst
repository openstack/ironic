Configure the Identity service for the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Create the Bare Metal service user (for example, ``ironic``).
   The service uses this to authenticate with the Identity service.
   Use the ``service`` tenant and give the user the ``admin`` role:

   .. code-block:: console

      $ openstack user create --password IRONIC_PASSWORD \
          --email ironic@example.com ironic
      $ openstack role add --project service --user ironic admin

#. You must register the Bare Metal service with the Identity service so that
   other OpenStack services can locate it. To register the service:

   .. code-block:: console

      $ openstack service create --name ironic --description \
          "Ironic baremetal provisioning service" baremetal

#. Use the ``id`` property that is returned from the Identity service when
   registering the service (above), to create the endpoint,
   and replace ``IRONIC_NODE`` with your Bare Metal service's API node:

   .. code-block:: console

      $ openstack endpoint create --region RegionOne \
          baremetal admin http://$IRONIC_NODE:6385
      $ openstack endpoint create --region RegionOne \
          baremetal public http://$IRONIC_NODE:6385
      $ openstack endpoint create --region RegionOne \
          baremetal internal http://$IRONIC_NODE:6385

#. You may delegate limited privileges related to the Bare Metal service
   to your Users by creating Roles with the OpenStack Identity service.  By
   default, the Bare Metal service expects the "baremetal_admin" and
   "baremetal_observer" Roles to exist, in addition to the default "admin"
   Role. There is no negative consequence if you choose not to create these
   Roles. They can be created with the following commands:

   .. code-block:: console

      $ openstack role create baremetal_admin
      $ openstack role create baremetal_observer

   If you choose to customize the names of Roles used with the Bare Metal
   service, do so by changing the "is_member", "is_observer", and "is_admin"
   policy settings in ``/etc/ironic/policy.json``.

   More complete documentation on managing Users and Roles within your
   OpenStack deployment are outside the scope of this document, but may be
   found here_.

#. You can further restrict access to the Bare Metal service by creating a
   separate "baremetal" Project, so that Bare Metal resources (Nodes, Ports,
   etc) are only accessible to members of this Project:

   .. code-block:: console

      $ openstack project create baremetal

   At this point, you may grant read-only access to the Bare Metal service API
   without granting any other access by issuing the following commands:

   .. code-block:: console

      $ openstack user create \
          --domain default --project-domain default --project baremetal \
          --password PASSWORD USERNAME
      $ openstack role add \
          --user-domain default --project-domain default --project baremetal \
          --user USERNAME baremetal_observer

#. Further documentation is available elsewhere for the ``openstack``
   `command-line client`_ and the Identity_ service. A
   :doc:`policy.json.sample </configuration/sample-policy>`
   file, which enumerates the service's default policies, is provided for
   your convenience with the Bare Metal Service.

.. _Identity: https://docs.openstack.org/keystone/train/admin/cli-manage-projects-users-and-roles.html
.. _`command-line client`: https://docs.openstack.org/python-openstackclient/train/cli/authentication.html
.. _here: https://docs.openstack.org/keystone/train/admin/identity-concepts.html#user-management
