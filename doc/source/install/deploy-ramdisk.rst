.. _deploy-ramdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the
:ironic-python-agent-doc:`ironic-python-agent (IPA) <>`
service running on it for controlling and deploying bare metal nodes.

Two kinds of images are published on every commit from every branch of
:ironic-python-agent-doc:`ironic-python-agent (IPA) <>`

* DIB_ images are suitable for production usage and can be downloaded from
  https://tarballs.openstack.org/ironic-python-agent/dib/files/.

  * For Train and older use CentOS 7 images.
  * For Ussuri and up to Yoga use CentOS 8 images.
  * For Zed and newer use CentOS 9 images.

  .. warning:: CentOS 7 master images are no longer updated and must not be
               used.

  .. warning:: The published images will not work for dhcp-less deployments
               since the simple-init_ element is not present. Check the DIB_
               documentation to see how to build the image.

* TinyIPA_ images are suitable for CI and testing environments and can be
  downloaded from
  https://tarballs.openstack.org/ironic-python-agent/tinyipa/files/.

Building from source
--------------------

Check the ironic-python-agent-builder_ project for information on how to build
ironic-python-agent ramdisks.

.. _DIB: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/dib.html
.. _TinyIPA: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/tinyipa.html
.. _ironic-python-agent-builder: https://docs.openstack.org/ironic-python-agent-builder/latest/
.. _simple-init: https://docs.openstack.org/diskimage-builder/latest/elements/simple-init/README.html
