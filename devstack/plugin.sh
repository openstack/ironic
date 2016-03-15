#!/bin/bash
# plugin.sh - devstack plugin for ironic

echo_summary "ironic's plugin.sh was called..."
source $DEST/ironic/devstack/lib/ironic

if is_service_enabled ir-api ir-cond; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Ironic"
        install_ironic
        install_ironicclient
        cleanup_ironic
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configuring Ironic"
        configure_ironic

        if is_service_enabled key; then
            create_ironic_accounts
        fi

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
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

    if [[ "$1" == "unstack" ]]; then
        stop_ironic
        cleanup_baremetal_basic_ops
    fi

    if [[ "$1" == "clean" ]]; then
        cleanup_ironic
    fi
fi
