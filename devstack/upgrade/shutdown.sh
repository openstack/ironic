#!/bin/bash
#
#

set -o errexit

source $GRENADE_DIR/grenaderc
source $GRENADE_DIR/functions

# We need base DevStack functions for this
source $BASE_DEVSTACK_DIR/functions
source $BASE_DEVSTACK_DIR/stackrc # needed for status directory
source $BASE_DEVSTACK_DIR/lib/tls
source $BASE_DEVSTACK_DIR/lib/apache

# Keep track of the DevStack directory
IRONIC_DEVSTACK_DIR=$(dirname "$0")/..
source $IRONIC_DEVSTACK_DIR/lib/ironic

set -o xtrace

stop_ironic
