#!/bin/bash
#
# A simple wrapper around flake8 which makes it possible
# to ask it to only verify files changed in the current
# git HEAD patch.
#
# Intended to be invoked via tox:
#
#   tox -epep8 -- -HEAD
#

TEMP_SHA_FILE="plugin.$$.SHA256SUM"
find ironic_tempest_plugin/ -type f | xargs sha256sum | sort > ${TEMP_SHA_FILE}
if ! diff -q ${TEMP_SHA_FILE} tools/ironic_tempest_plugin.SHA256SUM;
then
    rm ${TEMP_SHA_FILE}
    echo ""
    echo "*******************************************************"
    echo "ERROR: Detected changes made to the ironic_tempest_plugin/ directory"
    echo "ERROR: Changes to the ironic_tempest_plugin/ are not allowed as"
    echo "ERROR: we no longer use that content and it will be removed"
    echo "ERROR: Please add changes to the tempest tests in the repository:"
    echo "ERROR:    openstack/ironic-tempest-plugin"
    echo "*******************************************************"
    echo ""
    exit 1
fi
rm ${TEMP_SHA_FILE}

if test "x$1" = "x-HEAD" ; then
    shift
    files=$(git diff --name-only HEAD~1 | tr '\n' ' ')
    echo "Running flake8 on ${files}"
    diff -u --from-file /dev/null ${files} | flake8 --diff "$@"
else
    echo "Running flake8 on all files"
    exec flake8 "$@"
fi
