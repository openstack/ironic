.. _image-store:

Configure the Image service for temporary URLs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some drivers of the Baremetal service (in particular, any drivers using
:ref:`direct-deploy` or :ref:`ansible-deploy` interfaces,
and some virtual media drivers) require target user images to be available
over clean HTTP(S) URL with no authentication involved
(neither username/password-based, nor token-based).

When using the Baremetal service integrated in OpenStack,
this can be achieved by specific configuration of the Image service
and Object Storage service as described below.

#. Configure the Image service to have object storage as a backend for
   storing images.
   For more details, please refer to the Image service configuration guide.

   .. note::
      When using Ceph+RadosGW for Object Storage service, images stored in
      Image service must be available over Object Storage service as well.

#. Enable TempURLs for the Object Storage account used by the Image service
   for storing images in the Object Storage service.

   #. Check if TempURLs are enabled:

      .. code-block:: shell

         # executed under credentials of the user used by Image service
         # to access Object Storage service
         $ openstack object store account show
         +------------+---------------------------------------+
         | Field      | Value                                 |
         +------------+---------------------------------------+
         | Account    | AUTH_bc39f1d9dcf9486899088007789ae643 |
         | Bytes      | 536661727                             |
         | Containers | 1                                     |
         | Objects    | 19                                    |
         | properties | Temp-Url-Key='secret'                 |
         +------------+---------------------------------------+

   #. If property ``Temp-Url-Key`` is set, note its value.

   #. If property ``Temp-Url-Key`` is not set, you have to configure it
      (``secret`` is used in the example below for the value):

      .. code-block:: shell

         $ openstack object store account set --property Temp-Url-Key=secret

#. Optionally, configure the ironic-conductor service. The default
   configuration assumes that:

   #. the Object Storage service is implemented by :swift-doc:`swift <>`,
   #. the Object Storage service URL is available from the service catalog,
   #. the project, used by the Image service to access the Object Storage, is
      the same as the project, used by the Bare Metal service to access it,
   #. the container, used by the Image service, is called ``glance``.

   If any of these assumptions do not hold, you may want to change your
   configuration file (typically located at ``/etc/ironic/ironic.conf``),
   for example:

   .. code-block:: ini

      [glance]

      swift_endpoint_url = http://openstack/swift
      swift_account = AUTH_bc39f1d9dcf9486899088007789ae643
      swift_container = glance
      swift_temp_url_key = secret

#. (Re)start the ironic-conductor service.
