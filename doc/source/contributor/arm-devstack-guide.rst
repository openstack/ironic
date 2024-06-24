=====================================================
Deploying Ironic on ARM64 with DevStack
=====================================================

The instructions here are specifically on how to configure for
`Deploying Ironic with DevStack <https://docs.openstack.org/ironic/latest/contributor/devstack-guide.html>`_
on an ARM64 architecture.

.. _ARM64configurations:

Configurations
==============

Create devstack/local.conf with the following content::

    cat >local.conf <<END
    [[local|localrc]]
    # Enable and disable services
    disable_all_services
    # enable_service <service name>

    # Credentials
    ADMIN_PASSWORD=password
    DATABASE_PASSWORD=password
    RABBIT_PASSWORD=password
    SERVICE_PASSWORD=password
    SERVICE_TOKEN=password

    # Set glance's default limit to be baremetal image friendly
    GLANCE_LIMIT_IMAGE_SIZE_TOTAL=5000

    # Enable Ironic plugin
    enable_plugin ironic https://opendev.org/openstack/ironic

    # Create a virtual machine to pose as Ironic's baremetal node.
    IRONIC_VM_COUNT=1

    # The parameters below represent the minimum possible values to create
    # functional aarch64-based nodes.
    IRONIC_VM_SPECS_RAM=4096
    IRONIC_VM_SPECS_DISK=3

    IRONIC_VM_SPECS_CPU=1
    IRONIC_VM_VOLUME_COUNT=2

    # Enable hardware types and interfaces.
    IRONIC_ENABLED_HARDWARE_TYPES=redfish
    IRONIC_ENABLED_MANAGEMENT_INTERFACES=redfish
    IRONIC_DEFAULT_RESCUE_INTERFACE=agent
    IRONIC_ENABLED_BOOT_INTERFACES="ipxe,redfish-virtual-media,http-ipxe,pxe,http"
    IRONIC_ENABLED_DEPLOY_INTERFACES="direct,ramdisk"
    IRONIC_ENABLED_RESCUE_INTERFACES="agent,no-rescue"

    # Specify deploy driver. This driver should be in the enabled list above.
    IRONIC_DEPLOY_DRIVER=redfish

    FORCE_CONFIG_DRIVE=False

    # aarch64 + IRONIC_BUILD_DEPLOY_RAMDISK will be a bad mix
    IRONIC_BUILD_DEPLOY_RAMDISK=False

    IRONIC_AGENT_IMAGE_DOWNLOAD_SOURCE=http
    IRONIC_AUTOMATED_CLEAN_ENABLED=False
    IRONIC_BOOT_MODE=uefi
    IRONIC_CALLBACK_TIMEOUT=800
    IRONIC_GRUB2_SHIM_FILE=https://mirror.stream.centos.org/9-stream/BaseOS/aarch64/os/EFI/BOOT/BOOTAA64.EFI
    IRONIC_GRUB2_FILE=https://mirror.stream.centos.org/9-stream/BaseOS/aarch64/os/EFI/BOOT/grubaa64.efi
    IRONIC_HW_ARCH=aarch64
    IRONIC_DIB_RAMDISK_OS=debian-arm64

    INSTALL_TEMPEST=False
    VIRT_DRIVER=ironic

    # By default, DevStack creates a 10.0.0.0/24 network for instances.
    # If this overlaps with the hosts network, you may adjust with the
    # following.
    #
    # IP_VERSION=4
    # FIXED_RANGE=10.1.0.0/20
    # IPV4_ADDRS_SAFE_TO_USE=10.1.0.0/20
    # NETWORK_GATEWAY=10.1.0.1

    Q_AGENT=openvswitch
    Q_ML2_PLUGIN_MECHANISM_DRIVERS=openvswitch
    Q_ML2_TENANT_NETWORK_TYPE=vxlan

    # Log all output to files
    LOGFILE=/opt/stack/devstack.log
    LOGDIR=/opt/stack/logs
    IRONIC_VM_LOG_DIR=/opt/stack/ironic-bm-logs

    END

This configuration sets up DevStack to work with ARM architecture hardware,
using aarch64 images and appropriate hardware types, interfaces, and settings.

Refer to the `Ironic on Devstack setup guide <https://docs.openstack.org/ironic/latest/contributor/devstack-guide.html>`_ for more information on deploying Ironic with DevStack.
