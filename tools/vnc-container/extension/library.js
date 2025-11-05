

/**
 * Constructs a URL using the configured BMC URL.
 * @returns {string} The complete URL.
 */
function bmc_url(path) {
    let url = config.app_info.address;
    return url + path;
}

/**
 * Constructs the Redfish API base URL using the configured BMC URL.
 * @returns {string} The complete Redfish API base URL.
 */
function redfish_url(path) {
    root_prefix = config.app_info.root_prefix;
    if (!root_prefix) {
        root_prefix = "/redfish/v1";
    }
    return bmc_url(root_prefix + path);
}

function set_status(status) {
    qs = new URLSearchParams(window.location.search);
    if (qs.get("status") == status){
        return
    }
    qs.set("status", status);
    window.location.search = qs.toString();
}

function set_error(error) {
    qs = new URLSearchParams(window.location.search);
    qs.set("error", error);
    window.location.search = qs.toString();
}
