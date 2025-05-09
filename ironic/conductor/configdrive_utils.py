#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import gzip
import json
import os
import tempfile

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
import pycdlib

from ironic.common import exception
from ironic.common import neutron


LOG = log.getLogger(__name__)
CONF = cfg.CONF


def is_invalid_network_metadata(network_data):
    """Return True if network metadata is invalid.

    :param network_data: A dictionary object containing network_metadata,
                         with three sub-fields, 'links', 'networks',
                         and 'services'. Returns True if the document is
                         invalid and missing network metadata, or when
                         specific other issues such as null MTU values
                         are detected.
    :returns: True when the data supplied is invalid.
    """
    try:
        # FIXME(TheJulia): Another possible issue is Nova can send
        # the MTU on links as "null" values. That seems super problematic
        # for jumbo frame users or constrained environments. We should
        # likely just declare missing MTU as a qualifier to rebuild, but
        # that is likely to then trigger far more often. Maybe that means
        # it is an even better idea...
        if (not network_data.get('links', [])
            and not network_data.get('networks', [])
            and not network_data.get('services', [])):
            return True
        if not CONF.conductor.disable_metadata_mtu_check:
            for link in network_data.get('links', []):
                if link.get('mtu') is None:
                    return True
    except AttributeError:
        # Got called with None or something else lacking the attribute.
        # NOTE(TheJulia): If we ever want to inject metadata if missing
        # here is where we would add it.
        return True
    return False


def check_and_patch_configdrive(task, configdrive):
    """Evaluates and patches an provided ISO9660 configuration drive file.

    This method is responsible for taking the user requested configuration
    drive, performing basic evaluation, attempting to patch/fix the
    configuration drive to enable the latest metadata written to be valid and
    correct, which is intended to allow the overall deployment process to
    proceed with the correct data.

    :param task: A TaskManager object.
    :param configdrive: The in-memory configuration drive file which was
                        submitted by the requester.
    :returns: The submitted configuration drive or a regenerated and patched
              configuration drive OR the original requested configuration
              drive *if* a failure is encountered in the overall process.
    """
    try:
        with tempfile.NamedTemporaryFile(dir=CONF.tempdir,
                                         mode="wb+") as fileobj:
            # We have a file, we need to extract it and get it to an temp file
            fileobj.write(gzip.decompress(base64.b64decode(configdrive)))
            fileobj.flush()
            # Reset the position back to the start.
            fileobj.seek(0)
            # We then needs to peak inside, and likely then re-master it.
            provided_iso = pycdlib.PyCdlib()
            provided_iso.open_fp(fileobj)
            # NOTE(TheJulia): on the filename is an ISO9660 detail which
            # delineates the filename as the end of filename and signals the
            # the file identifier number.
            # https://wiki.osdev.org/ISO_9660
            with provided_iso.open_file_from_iso(
                    iso_path='/openstack/latest/network_data.json;1') as ndfp:
                try:
                    nd_dict = json.loads(ndfp.read())
                    # NOTE(TheJulia): This is the area of the code we would
                    # want to inject any additional checks in for patching in.
                    if not is_invalid_network_metadata(nd_dict):
                        # We know the config drive is okay, we can return what
                        # was submitted.
                        return configdrive
                except (TypeError, json.decoder.JSONDecodeError) as e:
                    # NOTE(TheJulia): We've gotten some sort of invalid data
                    # which is a possible case. So... just live with it and
                    # move on.
                    LOG.debug('Encountered error while trying to parse '
                              'configuration drive network_data.json file '
                              'for node UUID %(node)s, instance %(inst)s.'
                              'content which was submitted to Ironic. '
                              'Error: %(error)s',
                              {'error': e,
                               'node': task.node.uuid,
                               'inst': task.node.instance_uuid})
            LOG.warning('The provided metadata for the deployment of '
                        'node %s appears invalid, and will be '
                        'regenerated based upon the available '
                        'metadata.', task.node.uuid)
            network_data = json.dumps(generate_config_metadata(task))
            # Grab the filename to use. This is not with a context manager
            # because we are going to do the write-out of the new file
            # using mkisofs.
            new_iso_file = tempfile.mkstemp(dir=CONF.tempdir)[1]
            # NOTE(TheJulia): This is where we would make a decision to
            # inject any additional override files to the image as the
            # regenerate_iso call takes overrides.
            regenerate_iso(
                provided_iso, new_iso_file,
                {'/openstack/latest/network_data.json': network_data},
                node_uuid=task.node.uuid)
            new_drive = _read_config_drive(new_iso_file)
            # Remove the file.
            os.remove(new_iso_file)
    except (OSError, processutils.ProcessExecutionError) as e:
        # Catch any general OSError (permission issue) or
        # ProcessExecutionError from regenerate_iso.
        LOG.error('Failed to regenerate the configuration drive ISO '
                  'for node %(node)s, '
                  'roceeding with submitted metadata: %s',
                  {'error': e,
                   'node': task.node.uuid})
        return configdrive
    except exception.ConfigDriveRegenerationFailure:
        # If this is being raised, the generation failed. That should have
        # been logged where it was raised.
        return configdrive
    except pycdlib.pycdlibexception.PyCdlibInvalidInput:
        # File is missing in ISO or could not be found.
        LOG.error('Failed to process metadata, as the supplied configuration '
                  'drive ISO for the deployment of node %s lacked the '
                  'openstack/latest/network_data.json file.', task.node.uuid)
        return configdrive
    return new_drive


def _read_config_drive(file):
    # NOTE(TheJulia): This is minimal to keep the file open interaction out
    # of the unit test code path, with the goal of just keeping things a bit
    # more simple as well.
    with open(file, "rb") as new_iso:
        return base64.b64encode(
            gzip.compress(new_iso.read())).decode()


def regenerate_iso(source, dest, override_files, node_uuid=None):
    """Utility method to regenerate a config drive ISO image.

    This method takes the source, extracts the contents in a temporary folder,
    applies override contents, and then re-packages the contents into the dest
    file supplied as a parameter.

    :param source: A PyCdlib class object of an opened ISO file to extract.
    :param dest: The destination filename to write the result to.
    :param override_files: A dictionary of file name keys and contents stored
                           as values paris, which will be used to override
                           contents of the configuration drive for the purpose
                           of patching metadata.
    :param node_uuid: The node UUID, for logging purposes.
    """
    with tempfile.TemporaryDirectory(dir=CONF.tempdir) as tempfolder:
        # NOTE(TheJulia): The base extraction logic was sourced from kickstart
        # utils, as an actually kind of simple base approach to do the needful
        # extraction.
        LOG.debug('Extracting configuration drive for node %(node)s to '
                  '%(location)s.',
                  {'node': node_uuid,
                   'location': tempfolder})
        # The default configuration drive format we expect is generally
        # of a rock ridge format, and to avoid classic dos ISO9660 level
        # constraints, we will get the path using a rock ridge base path
        # so we don't have dashes translated into underscores on files
        # we want to preserve.
        for path, dirlist, filelist in source.walk(rr_path='/'):
            unix_path = path.lstrip('/')
            if path != "/":
                os.makedirs(os.path.join(tempfolder, unix_path), exist_ok=True)
            for f in filelist:
                # In iso9660 file extensions are mangled. Example '/FOO/BAR;1'.
                iso_file_path = os.path.join(path, f)
                file_record = source.get_record(rr_path=iso_file_path)
                posix_file_path = source.full_path_from_dirrecord(
                    file_record, rockridge=True
                )
                # Path to which the file in config drive to be written on the
                # server.
                posix_file_path = os.path.join(tempfolder,
                                               posix_file_path.lstrip('/'))
                # Extract the actual file from the ISO.
                source.get_file_from_iso(
                    joliet_path=iso_file_path, local_path=posix_file_path)
        # Okay, we have the files in a folder, lets patch!
        for file in override_files:
            LOG.debug('Patching override configuration drive file '
                      '%(file)s for node %(node)s.',
                      {'file': file,
                       'node': node_uuid})
            content = override_files[file]
            dest_path = os.path.join(tempfolder, str(file).lstrip('/'))
            with open(dest_path, mode="w") as new_file:
                new_file.write(content)
        # Instead of trying to use pycdlib to walk and assemble everything,
        # we'll just call out to mkisofs
        processutils.execute('mkisofs',
                             '-o', dest,
                             '-ldots',
                             '-allow-lowercase',
                             '-allow-multidot',
                             '-l',
                             '-publisher', 'Ironic',
                             '-quiet', '-J', '-r',
                             '-V', 'config-2',
                             tempfolder, attempts=1)


def generate_instance_network_data(task):
    """Generates OpenStack instance network metadata.

    This method was added to help facilitate the correction of cases
    where bad metadata could be supplied to Ironic by a service such
    as Nova where an instance has been requested, but missing
    network configuration details harms the viability of the overall
    instance's deployment.

    This method works by taking the available information which Ironic
    manages and controls, and reconciles it together into an OpenStack
    style network_data document which can then be rendered as
    network_data.json.

    :param task: A TaskManager class instance.
    :returns: A dictionary object with three keys, 'links', 'networks',
              and 'services' which contains various related entries
              as generated by the internal neutron get_neutron_port_data
              method which is then combined such that bond ports are also
              honored.
    """
    ports = task.ports
    portgroups = task.portgroups

    # get tenant vifs from all port objects, and reverse the structural
    # mapping so we keep the data associated for re-assembly.
    vif_id_to_objects = {'ports': {}, 'portgroups': {}}
    for name, collection in (('ports', ports), ('portgroups', portgroups)):
        for p in collection:
            # NOTE(TheJulia): While super similar to nova metadata code
            # as it pertiains to ironic, this explicitly focuses on
            vif_id = p.internal_info.get('tenant_vif_port_id')
            if vif_id:
                vif_id_to_objects[name][vif_id] = p
                # So now we have something like
                # vif_id_to_objects['ports'][vif_id] holding port object
                # so we have something easy and well structured to work with
                # through the rest of the method.
        # Where things are weird for nova and more clear-cut here is
        # we have and own all the physical structural data about the ports.
        # In nova, it is based upon what the user requests from an instance
        # and attempts to be bridge into the context of a baremetal node.
        # Metalsmith's metadata generation is geared similar to a nova
        # instance, the union of requested. Here, we don't really need to
        # take any guesses, everything is already mapped.

        # The pattern here is keyed off a list of VIF Ids. We'll need
        # this to finish hydrating necessary data.
        vif_id_keys = list(vif_id_to_objects['ports'])
        vif_id_keys.extend(list(vif_id_to_objects['portgroups']))

        # This is the starting point for metadata generation. We have three
        # buckets which contain lists of dicts. In this specific case, we
        # have to create a consolidated view across all attachments which
        # will require us to add values in.
    net_meta = {
        'links': [],
        'networks': [],
        'services': [],
    }
    for vif_id in vif_id_keys:
        vif_net_meta = {}
        if vif_id in vif_id_to_objects['portgroups']:
            pg = vif_id_to_objects['portgroups'][vif_id]
            pg_ports = [p for p in ports if p.portgroup_id == pg.id]
            bond_links = []
            # Pre-bake the various links for the bond.
            # This won't cause any duplicates to be added. A port
            # cannot be in more than one port group for the same
            # node.
            for p in pg_ports:
                # Assemble all of the portgroup members to ensure
                # they are present in the resulting list of physical
                # links to consider, so it can be assembled together.
                bond_links.append(
                    {
                        'id': p.uuid,
                        'type': 'phy',
                        'ethernet_mac_address': p.address,
                    }
                )
            vif_net_meta = neutron.get_neutron_port_data(
                pg.id, vif_id, iface_type='bond',
                mac_address=pg.address, bond_links=bond_links)
        elif vif_id in vif_id_to_objects['ports']:
            p = vif_id_to_objects['ports'][vif_id]
            vif_net_meta = neutron.get_neutron_port_data(
                p.id, vif_id,
                mac_address=p.address,
                iface_type='phy')
        else:
            LOG.error('While attempting to generate network metadata, '
                      'an unexpected case was encountered where VIF '
                      '%(vif)s was expected but then not found for '
                      'the deploy of node %(node)s.',
                      {'node': task.node.uuid,
                       'vif': vif_id})
        # Assemble the *per* VIF parts into the whole
        for key in ['links', 'networks', 'services']:
            # There is a fundimental issue, which is if
            # a *user* requests instances with multiple distinct
            # VIFs, and those vifs have multiple networks and
            # differences, it might not reconcile or may create
            # a conflicting situation. This is a reality and
            # there is likely not much we can do to  head it off
            # as its entirely a possible situation in an entirely
            # manually configured universe.
            net_meta[key].extend(vif_net_meta[key])

    # NOTE(TheJulia): This is done after the fact since our entire
    # structure assembles everything together by vif and upon the basis
    # of the vif attachments. We swap the values down to shorter values
    # because it turns out some configdrive readers will try to use the
    # id as a name value instead of operating relatively within the
    # context of the running state of the node where the data applies.
    link_count = 0
    link_map = {}
    # This is all modeled to modify in place so we minimally touch
    # the rest of the data structure.
    for link in net_meta['links']:
        link_name = 'iface{}'.format(link_count)
        link_map[link['id']] = link_name
        net_meta['links'][link_count]['id'] = link_name
        link_count += 1
    # We have to re-iterate through the all of the links to address
    # bond links, since we should already have mapped names, and now
    # we just need to correct them.
    link_count = 0
    for link in net_meta['links']:
        bond_links = link.get('bond_links')
        if bond_links:
            new_links = [link_map[x] for x in bond_links]
            net_meta['links'][link_count]['bond_links'] = new_links
        link_count += 0
    # We now need to re-associate networks to the new interface
    # id values.
    net_count = 0
    for network in net_meta['networks']:
        new_name = link_map[net_meta['networks'][net_count]['link']]
        net_meta['networks'][net_count]['link'] = new_name
        net_count += 1
    return net_meta


def generate_config_metadata(task):
    """Generates new network config metadata.

    This method wraps generate_instance_network_data and performs
    the logging actions in relation to it, and also performs a post
    generation sanity check on the network metadata.

    When the data is invalid, this method *also* raises an internal
    ConfigDriveRegenerationFailure exception which is a signal to the
    caller method that an issue has occurred. The expectation being
    that the caller knows how to handle and navigate that issue without
    failing the deployment operation.

    :param task: A TaskManager object.
    :returns: A dictionary object with three keys, 'links', 'networks',
              and 'services' which contains various related entries
              as generated by the internal neutron get_neutron_port_data
              method which is then combined such that bond ports are also
              honored.
    :raises: ConfigDriveRegenerationFailure when no metadata is generated
             or the configuration state of the drivers does not support
             the generation of network metadata. The purpose of this is
             to appropriately signal an error to the caller, not fail the
             overall requested operation by the end user.
    """
    # NOTE(TheJulia): This method could be improved or extended in the
    # future, and with that somewhat in mind, the name of the method
    # was left appropriately broad to set that stage.

    metadata = generate_instance_network_data(task)
    if is_invalid_network_metadata(metadata):
        # NOTE(TheJulia): This *should* never happen in the scenarios
        # known to Ironic, however *could* happen if there is some sort
        # of weird state due to drivers. i.e. if someone had a completely
        # custom set of interfaces, this could occur and we don't want
        # this to be fatal because maybe this is also the intent. In
        # any event, log the error and move on.
        LOG.error('Failed to generate new network metadata for '
                  'deployment of node %s. No virtual interfaces '
                  'were generated. Possible missing vifs?',
                  task.node.uuid)
        raise exception.ConfigDriveRegenerationFailure()
    return metadata


def check_and_fix_configdrive(task, configdrive):
    """Check and fix the supplied config drive.

    In certain cases, a caller may supply a horribly broken configuration
    drive which contains a list of empty dicts or even is an ISO in the same
    state.

    The prupose of this method is to attempt to identify and correct those
    specific cases to help ensure the instance being deployed has what is
    necessary to boot.

    If this method fails, an internal exception,
    ConfigDriveRegenerationFailure is raised by the various helper methods
    used by this method, however this method will just return the user
    supplied

    :param task: A Taskmanager object.
    :param configdrive: The supplied configuration drive.
    :returns: Returns a configuration drive aligning with the type which
              was originally supplied by the user.
    """

    # NOTE(TheJulia): A possible, feature sort of expansion is to potentially
    # use this same method to also just supply network metadata injection if
    # no configuration drive is supplied.
    try:
        if isinstance(configdrive, str) and configdrive.startswith('http'):
            # In this event, we've been given a URL. We don't support
            # trying to do anything else hwere.
            return configdrive
        elif isinstance(configdrive, dict):
            provided_network_data = configdrive.get('network_data')
            # TODO(TheJulia): This is where we could inject network config
            # metadata into config drive results if not supplied to by the
            # user.
            if is_invalid_network_metadata(provided_network_data):
                # BUG 2106073 OR there is data, but no network data in the
                # configuration drive. In such a case, we need to take what
                # we know to be the metadata based upon the state,
                # and replace the field.
                generated_metadata = generate_config_metadata(task)
                # Explicitly set to a variable to allow the method to not
                # possibly impact the original configdrive value.
                configdrive['network_data'] = generated_metadata
        else:
            # This method knows how to patch the existing configdrive and
            # call the metadata check independently due to the complexity
            # of handling the config drive ISOs and fixing them when they
            # need updates.
            LOG.debug('Starting to evaluate configdrive for node %s',
                      task.node.uuid)
            configdrive = check_and_patch_configdrive(task, configdrive)
    except exception.ConfigDriveRegenerationFailure:
        LOG.warning('Ironic was unable to regenerate the configdrive for node '
                    '%s.', task.node.uuid)
        # This is not a fatal failure, just circle things back.
    # Always return configdrive content, otherwise we hand None back
    # which causes the overall process to fail.
    return configdrive
