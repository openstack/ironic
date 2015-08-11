# -*- mode: ruby -*-
# vi: set ft=ruby :

# WARNING: This Vagrantfile is for development purposes only. It is intended to
# bootstrap required services - such as mysql and rabbit - into a reliably
# accessible VM, rather than forcing the engineer to install and manage these
# services manually. This Vagrantfile is not intended to assist in provisioning
# Ironic. For that, please use the bifrost project.

VAGRANTFILE_API_VERSION = '2'

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|

  config.vm.box = 'ubuntu/trusty64'

  config.vm.define 'ironic' do |ironic|
    ironic.vm.provider :virtualbox do |vb|
      vb.customize ['modifyvm', :id, '--memory', '512', '--cpuexecutioncap', '25']
    end

    ironic.vm.network 'private_network', ip: '192.168.99.11' # It goes to 11.

    ironic.vm.provision 'ansible' do |ansible|
      ansible.verbose = 'v'
      ansible.playbook = 'vagrant.yaml'
      ansible.extra_vars = {
          ip: '192.168.99.11'
      }
    end
  end
end
