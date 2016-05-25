#!/usr/bin/env bash

PROJECT_NAME=${PROJECT_NAME:-ironic}
CFGFILE_NAME=${PROJECT_NAME}.conf.sample
OSLO_CFGFILE_OPTION=${OSLO_CFGFILE_OPTION:-tools/config/ironic-config-generator.conf}

if [ -e etc/${PROJECT_NAME}/${CFGFILE_NAME} ]; then
    CFGFILE=etc/${PROJECT_NAME}/${CFGFILE_NAME}
elif [ -e etc/${CFGFILE_NAME} ]; then
    CFGFILE=etc/${CFGFILE_NAME}
else
    echo "${0##*/}: can not find config file"
    exit 1
fi

TEMPDIR=`mktemp -d /tmp/${PROJECT_NAME}.XXXXXX`
trap "rm -rf $TEMPDIR" EXIT

oslo-config-generator --config-file=${OSLO_CFGFILE_OPTION} --output-file ${TEMPDIR}/${CFGFILE_NAME}
if [ $? != 0 ]
then
    exit 1
fi

if ! diff -u ${TEMPDIR}/${CFGFILE_NAME} ${CFGFILE}
then
   echo "${0##*/}: ${PROJECT_NAME}.conf.sample is not up to date."
   echo "${0##*/}: Please run oslo-config-generator --config-file=${OSLO_CFGFILE_OPTION}"
   exit 1
fi
