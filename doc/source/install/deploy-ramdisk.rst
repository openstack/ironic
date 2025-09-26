.. _deploy-ramdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the
:ironic-python-agent-doc:`ironic-python-agent (IPA) <>`
service running on it for controlling and deploying bare metal nodes.
This image is not written *to* the storage of any given node, but
provides the runtime tooling and communication for the inspection,
cleaning, and ultimately deployment of a bare metal node managed by Ironic.

Ironic publishes images on every commit from every branch of
:ironic-python-agent-doc:`ironic-python-agent (IPA) <>`

* DIB_ images are suitable for production usage and can be downloaded from
  https://tarballs.openstack.org/ironic-python-agent/dib/files/.

  .. warning:: The published images will not work for dhcp-less deployments
               since the simple-init_ element is not present. Check the DIB_
               documentation to see how to build the image.

Building from source
--------------------

Check the ironic-python-agent-builder_ project for information on how to build
ironic-python-agent ramdisks.

.. _DIB: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/dib.html
.. _ironic-python-agent-builder: https://docs.openstack.org/ironic-python-agent-builder/latest/
.. _simple-init: https://docs.openstack.org/diskimage-builder/latest/elements/simple-init/README.html
