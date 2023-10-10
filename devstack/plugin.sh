#!/bin/bash
# plugin.sh - devstack plugin for ironic

# devstack plugin contract defined at:
# https://docs.openstack.org/devstack/latest/plugins.html

echo_summary "ironic devstack plugin.sh called: $1/$2"
source $DEST/ironic/devstack/lib/ironic

if is_service_enabled ir-api ir-cond; then
    if [[ "$1" == "stack" ]]; then
        if [[ "$2" == "install" ]]; then
        # stack/install - Called after the layer 1 and 2 projects source and
        # their dependencies have been installed

            echo_summary "Installing Ironic"
            if ! is_service_enabled nova; then
                source $TOP_DIR/lib/nova_plugins/functions-libvirt
                install_libvirt
            fi
            install_ironic
            install_ironicclient
            cleanup_ironic_config_files
            downgrade_dnsmasq

        elif [[ "$2" == "post-config" ]]; then
        # stack/post-config - Called after the layer 1 and 2 services have been
        # configured. All configuration files for enabled services should exist
        # at this point.

            echo_summary "Configuring Ironic"
            configure_ironic

            if is_service_enabled key; then
                create_ironic_accounts
            fi

            if [[ "$IRONIC_BAREMETAL_BASIC_OPS" == "True" && "$IRONIC_IS_HARDWARE" == "False" ]]; then
                echo_summary "Precreating bridge: $IRONIC_VM_NETWORK_BRIDGE"
                if [[ "$Q_BUILD_OVS_FROM_GIT" == "True" ]]; then
                    if [[ "$Q_AGENT" == "ovn" ]]; then
                        # If we're here, we were requested to install from git
                        # for OVN *and* OVS, but that means basic setup has not been
                        # performed yet. As such, we need to do that and start
                        # OVN/OVS where as if we just need to ensure OVS is present,
                        # vendor packaging does that for us. We start early here,
                        # because neutron setup for this is deferred until too late
                        # for our plugin to setup the test environment.
                        echo_summary "Setting up OVN..."
                        init_ovn
                        start_ovn
                    fi
                else
                    # NOTE(TheJulia): We are likely doing this to ensure
                    # OVS is running.
                    echo_summary "Installing OVS to pre-create bridge"
                    install_package openvswitch-switch
                fi
                sudo ovs-vsctl -- --may-exist add-br $IRONIC_VM_NETWORK_BRIDGE
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

            if is_service_enabled neutron || [[ "$HOST_TOPOLOGY" == "multinode" ]]; then
                echo_summary "Configuring Ironic networks"
                configure_ironic_networks
            fi
            if [[ "$HOST_TOPOLOGY" == 'multinode' ]]; then
                setup_vxlan_network
            fi

            # Start the ironic API and ironic taskmgr components
            prepare_baremetal_basic_ops
            echo_summary "Starting Ironic"
            start_ironic
            enroll_nodes

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
