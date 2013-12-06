#!/bin/sh
TEMPDIR=`mktemp -d`
CFGFILE=ironic.conf.sample
tools/conf/generate_sample.sh -b ./ -p ironic -o $TEMPDIR
if ! diff $TEMPDIR/$CFGFILE etc/ironic/$CFGFILE
then
    echo "E: ironic.conf.sample is not up to date, please run tools/conf/generate_sample.sh"
    exit 42
fi
