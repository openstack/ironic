.. _root-device-hints:

Specifying the disk for deployment (root device hints)
------------------------------------------------------

Starting with the Kilo release, Bare Metal service supports passing
hints to the deploy ramdisk about which disk it should pick for the
deployment. The list of support hints is:

* model (STRING): device identifier
* vendor (STRING): device vendor
* serial (STRING): disk serial number
* size (INT): size of the device in GiB

  .. note::
    A node's 'local_gb' property is often set to a value 1 GiB less than the
    actual disk size to account for partitioning (this is how DevStack, TripleO
    and Ironic Inspector work, to name a few). However, in this case ``size``
    should be the actual size. For example, for a 128 GiB disk ``local_gb``
    will be 127, but size hint will be 128.

* wwn (STRING): unique storage identifier
* wwn_with_extension (STRING): unique storage identifier with the vendor extension appended
* wwn_vendor_extension (STRING): unique vendor storage identifier
* rotational (BOOLEAN): whether it's a rotational device or not. This
  hint makes it easier to distinguish HDDs (rotational) and SSDs (not
  rotational) when choosing which disk Ironic should deploy the image onto.
* name (STRING): the device name, e.g /dev/md0


  .. warning::
     The root device hint name should only be used for devices with
     constant names (e.g RAID volumes). For SATA, SCSI and IDE disk
     controllers this hint is not recommended because the order in which
     the device nodes are added in Linux is arbitrary, resulting in
     devices like /dev/sda and /dev/sdb `switching around at boot time
     <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Storage_Administration_Guide/persistent_naming.html>`_.


To associate one or more hints with a node, update the node's properties
with a ``root_device`` key, for example::

    ironic node-update <node-uuid> add properties/root_device='{"wwn": "0x4000cca77fc4dba1"}'


That will guarantee that Bare Metal service will pick the disk device that
has the ``wwn`` equal to the specified wwn value, or fail the deployment if it
can not be found.

.. note::
    If multiple hints are specified, a device must satisfy all the hints.
