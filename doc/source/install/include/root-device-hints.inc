.. _root-device-hints:

Specifying the disk for deployment (root device hints)
------------------------------------------------------

The Bare Metal service supports passing hints to the deploy ramdisk about
which disk it should pick for the deployment. The list of supported hints is:

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
* hctl (STRING): the SCSI address (Host, Channel, Target and Lun),
  e.g '1:0:0:0'
* by_path (STRING): the alternate device name corresponding to a particular
  PCI or iSCSI path, e.g /dev/disk/by-path/pci-0000:00
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

    baremetal node set <node-uuid> --property root_device='{"wwn": "0x4000cca77fc4dba1"}'


That will guarantee that Bare Metal service will pick the disk device that
has the ``wwn`` equal to the specified wwn value, or fail the deployment if it
can not be found.

.. note::
    Starting with the Ussuri release, root device hints can be specified
    per-instance, see :doc:`/install/standalone`.

The hints can have an operator at the beginning of the value string. If
no operator is specified the default is ``==`` (for numerical values)
and ``s==`` (for string values). The supported operators are:

* For numerical values:

  * ``=`` equal to or greater than. This is equivalent to ``>=`` and is
    supported for `legacy reasons <https://docs.openstack.org/nova/latest/user/filter-scheduler.html#filtering>`_
  * ``==`` equal to
  * ``!=`` not equal to
  * ``>=`` greater than or equal to
  * ``>`` greater than
  * ``<=`` less than or equal to
  * ``<`` less than

* For strings (as python comparisons):

  * ``s==`` equal to
  * ``s!=`` not equal to
  * ``s>=`` greater than or equal to
  * ``s>`` greater than
  * ``s<=`` less than or equal to
  * ``s<`` less than
  * ``<in>`` substring

* For collections:

  * ``<all-in>`` all elements contained in collection
  * ``<or>`` find one of these

Examples are:

* Finding a disk larger or equal to 60 GiB and non-rotational (SSD)::

    baremetal node set <node-uuid> --property root_device='{"size": ">= 60", "rotational": false}'

* Finding a disk whose vendor is ``samsung`` or ``winsys``::

    baremetal node set <node-uuid> --property root_device='{"vendor": "<or> samsung <or> winsys"}'

.. note::
    If multiple hints are specified, a device must satisfy all the hints.
