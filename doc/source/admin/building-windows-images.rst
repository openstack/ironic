.. _building_image_windows:

Building images for Windows
---------------------------
We can use ``New-WindowsOnlineImage`` in `windows-openstack-imaging-tools`_
tool as an option to create Windows images (whole disk images) corresponding
boot modes which will support for Windows NIC Teaming. And allow the
utilization of link aggregation when the instance is spawned on hardware
servers (Bare metals).

Requirements:
~~~~~~~~~~~~~

* A Microsoft Windows Server Operating System along with
  ``Hyper-V virtualization`` enabled,
  ``PowerShell`` version >=4 supported,
  ``Windows Assessment and Deployment Kit``,
  in short ``Windows ADK``.
* The windows Server compatible drivers.
* Working git environment.

Preparation:
~~~~~~~~~~~~

* Download a Windows Server 2012R2/ 2016 installation ISO.
* Install Windows Server 2012R2/ 2016 OS on workstation PC along with
  following feature:

  - Enable Hyper-V virtualization.
  - Install PowerShell 4.0.
  - Install Git environment & import git proxy (if have).
  - Create new ``Path`` in Microsoft Windows Server Operating System which
    support for submodule update via ``git submodule update –init`` command::

      - Variable name: Path
      - Variable value: C:\Windows\System32\WindowsPowerShell\v1.0\;C:\Program Files\Git\bin

  - Rename virtual switch name in Windows Server 2012R2/ 2016 in
    ``Virtual Switch Manager`` into `external`.

Implementation:
~~~~~~~~~~~~~~~

* ``Step 1``: Create folders: ``C:\<folder_name_1>`` where output images will
  be located, ``C:\<folder_name_2>`` where you need to place the necessary
  hardware drivers.

* ``Step 2``: Copy and extract necessary hardware drivers in
  ``C:\<folder_name_2>``.

* ``Step 3``: Insert or burn Windows Server 2016 ISO to ``D:\``.

* ``Step 4``: Download ``windows-openstack-imaging-tools`` tools.

  .. code-block:: console

    git clone https://github.com/cloudbase/windows-openstack-imaging-tools.git

* ``Step 5``: Create & running script `create-windows-cloud-image.ps1`:

  .. code-block:: console

    git submodule update --init
    Import-Module WinImageBuilder.psm1
    $windowsImagePath = "C:\<folder_name_1>\<output_file_name>.qcow2"
    $VirtIOISOPath = "C:\<folder_name_1>\virtio.iso"
    $virtIODownloadLink = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.133-2/virtio-win.iso"
    (New-Object System.Net.WebClient).DownloadFile($virtIODownloadLink, $VirtIOISOPath)
    $wimFilePath = "D:\sources\install.wim"
    $extraDriversPath = "C:\<folder_name_2>\"
    $image = (Get-WimFileImagesInfo -WimFilePath $wimFilePath)[1]
    $switchName = 'external'
    New-WindowsOnlineImage -WimFilePath $wimFilePath
      -ImageName $image.ImageName ` -WindowsImagePath $windowsImagePath -Type 'KVM' -ExtraFeatures @() `
      -SizeBytes 20GB -CpuCores 2 -Memory 2GB -SwitchName $switchName ` -ProductKey $productKey -DiskLayout 'BIOS' `
      -ExtraDriversPath $extraDriversPath ` -InstallUpdates:$false -AdministratorPassword 'Pa$$w0rd' `
      -PurgeUpdates:$true -DisableSwap:$true

  After executing this command you will get two output files, first one being
  "C:\<folder_name_1>\<output_file_name>.qcow2", which is the resulting windows
  whole disk image and "C:\<folder_name_1>\virtio.iso", which is virtio iso
  contains all the synthetic drivers for the KVM hypervisor.

  See `example_windows_images`_ for more details and examples.

  .. note::

    We can change ``SizeBytes``, ``CpuCores`` and ``Memory`` depending on requirements.

.. _`example_windows_images`: https://github.com/cloudbase/windows-openstack-imaging-tools/blob/master/Examples
.. _`windows-openstack-imaging-tools`: https://github.com/cloudbase/windows-openstack-imaging-tools
