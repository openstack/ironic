#!/bin/bash
# plugin.sh - devstack plugin for ironic

# devstack plugin contract defined at:
# http://docs.openstack.org/developer/devstack/plugins.html

echo_summary "ironic's plugin.sh was called..."
source $DEST/ironic/devstack/lib/ironic

if is_service_enabled ir-api ir-cond; then
    if [[ "$1" == "stack" ]]; then
        if [[ "$2" == "install" ]]; then
        # stack/install - Called after the layer 1 and 2 projects source and
        # their dependencies have been installed

            echo_summary "Installing Ironic"
            install_ironic
            install_ironicclient
            cleanup_ironic_config_files

        elif [[ "$2" == "post-config" ]]; then
        # stack/post-config - Called after the layer 1 and 2 services have been
        # configured. All configuration files for enabled services should exist
        # at this point.

            echo_summary "Configuring Ironic"
            configure_ironic

            if is_service_enabled key; then
                create_ironic_accounts
            fi

        elif [[ "$2" == "extra" ]]; then
        # stack/extra - Called near the end after layer 1 and 2 services have
        # been started.

            # Initialize ironic
            init_ironic

            if [[ "$IRONIC_BAREMETAL_BASIC_OPS" == "True" && "$IRONIC_IS_HARDWARE" == "False" ]]; then
                echo_summary "Creating bridge and VMs"
                create_bridge_and_vms
            fi

            if is_service_enabled neutron; then
                echo_summary "Configuring Ironic networks"
                configure_ironic_networks
            fi

            # Start the ironic API and ironic taskmgr components
            echo_summary "Starting Ironic"
            start_ironic
            prepare_baremetal_basic_ops

        elif [[ "$2" == "test-config" ]]; then
        # stack/test-config - Called at the end of devstack used to configure tempest
        # or any other test environments
            if is_service_enabled tempest; then
                echo_summary "Configuring Tempest for Ironic needs"
                ironic_configure_tempest
            fi
        fi
    fi

    if [[ "$1" == "unstack" ]]; then
    # unstack - Called by unstack.sh before other services are shut down.

        stop_ironic
        cleanup_ironic_provision_network
        cleanup_baremetal_basic_ops
    fi

    if [[ "$1" == "clean" ]]; then
    # clean - Called by clean.sh before other services are cleaned, but after
    # unstack.sh has been called.

        cleanup_ironic
    fi
fi
