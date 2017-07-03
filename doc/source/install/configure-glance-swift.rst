.. _image-store:

Configure the Image service for temporary URLs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some drivers of the Baremetal service (in particular, any ``agent_*`` drivers,
any new-style drivers using ``direct`` deploy interface,
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


#. Configure the ironic-conductor service.
   The configuration file is typically located at
   ``/etc/ironic/ironic.conf``.
   Some of the required values are available in the response of an
   ``openstack object store account show`` command;
   others have to match those configured in Image and Object Store services
   configuration files. Below is a example of a minimal set of configuration
   options to specify when Object Storage service is provided by swift
   (check configuration file sample included within ironic
   code ``etc/ironic/ironic.conf.sample`` for full list of available options
   and their detailed descriptions):

   .. code-block:: ini

      [glance]

      temp_url_endpoint_type = swift
      swift_endpoint_url = http://openstack/swift
      swift_account = AUTH_bc39f1d9dcf9486899088007789ae643
      swift_container = glance
      swift_temp_url_key = secret

#. (Re)start the ironic-conductor service.
