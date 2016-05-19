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

            # Start the ironic API and ironic taskmgr components
            echo_summary "Starting Ironic"
            start_ironic
            prepare_baremetal_basic_ops
            if is_service_enabled tempest; then
                ironic_configure_tempest
            fi
        fi
    fi

    if [[ "$1" == "unstack" ]]; then
    # unstack - Called by unstack.sh before other services are shut down.

        stop_ironic
        cleanup_baremetal_basic_ops
    fi

    if [[ "$1" == "clean" ]]; then
    # clean - Called by clean.sh before other services are cleaned, but after
    # unstack.sh has been called.

        cleanup_ironic
    fi
fi
