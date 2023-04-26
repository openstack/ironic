#!/bin/bash

set -eu -o pipefail

VERBOSE=${VERBOSE:-True}
if [[ "$VERBOSE" == True ]]; then
    set -x
    guestfish_args="--verbose"
fi

CIRROS_VERSION=${CIRROS_VERSION:-0.6.1}
CIRROS_ARCH=${CIRROS_ARCH:-x86_64}
# TODO(dtantsur): use the image cached on infra images in the CI
DISK_URL=http://download.cirros-cloud.net/${CIRROS_VERSION}/cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-disk.img
OUT=$(realpath ${1:-rootfs.img})

IRONIC_TTY_DEV=${IRONIC_TTY_DEV:-ttyS0,115200}
# rdroot : boot from the ramdisk present on the root partition instead of
#          mounting the root partition.
# dslist : disable Nova metadata support, it takes a long time on boot.
KARGS=${KARGS:-nofb vga=normal console=${IRONIC_TTY_DEV} rdroot dslist=configdrive}

workdir=$(mktemp -d)
root_mp=$workdir/root
efi_mp=$workdir/efi
dest=$workdir/dest

cd $workdir

curl -Lf -o disk.qcow2 $DISK_URL
qemu-img convert -O raw disk.qcow2 disk.img
rm disk.qcow2

# kpartx automatically allocates loop devices for all partitions in the image
device=$(sudo kpartx -av disk.img | grep -oE 'loop[0-9]+p' | head -1)

function clean_up {
    set +e
    sudo umount $efi_mp
    sudo umount $root_mp
    sudo kpartx -d $workdir/disk.img
    sudo rm -rf $workdir
}
trap clean_up EXIT

# TODO(dtantsur): some logic instead of hardcoding numbers 1 and 15?
rootdev=/dev/mapper/${device}1
efidev=/dev/mapper/${device}15

mkdir -p $root_mp $efi_mp $dest/boot/efi
sudo mount $rootdev $root_mp
sudo mount $efidev $efi_mp

sudo cp -aR $root_mp/* $dest/
sudo cp -aR $efi_mp/EFI $dest/boot/efi/

# These locations are required by IPA even when it does not really run
# grub-install.
sudo mkdir -p $dest/{dev,proc,run,sys}

# The default arguments don't work for us, update grub configuration.
sudo sed -i "/^ *linux /s/\$/ $KARGS/" $dest/boot/efi/EFI/ubuntu/grub.cfg

LIBGUESTFS_BACKEND=direct sudo -E \
    virt-make-fs --size +50M --type ext3 --label cirros-rootfs \
    ${guestfish_args:-} "$dest" "$OUT"

sudo chown $USER "$OUT"
qemu-img info "$OUT"
