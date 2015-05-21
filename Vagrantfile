# -*- mode: ruby -*-
# vi: set ft=ruby :

VAGRANTFILE_API_VERSION = '2'

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|

  config.vm.box = 'ubuntu/trusty64'

  config.vm.define 'ironic' do |ironic|
    ironic.vm.provider :virtualbox do |vb|
      vb.customize ['modifyvm', :id,'--memory', '2048']
    end

    ironic.vm.network 'private_network', ip: '192.168.99.11' # It goes to 11.

    ironic.vm.provision 'ansible' do |ansible|
      ansible.verbose = 'v'
      ansible.playbook = 'vagrant.yml'
      ansible.extra_vars = {
          ip: '192.168.99.11'
      }
    end
  end
end
