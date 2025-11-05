window.addEventListener("load", function () {
    if (window.location.protocol === "file:" && window.location.pathname.endsWith("/drivers/launch/index.html")) {
        console.log("idrac-graphical driver launch page loaded");
        set_status("Getting console credentials");
        loadConsole();
    }
});


/**
 * Loads the iDRAC graphical console by requesting a KVM session URL and redirecting the window.
 */
function loadConsole() {
    const kvm_session_url = redfish_url("/Managers/iDRAC.Embedded.1/Oem/Dell/DelliDRACCardService/Actions/DelliDRACCardService.GetKVMSession")
    const url = new URL(kvm_session_url);
    const netloc = url.host;
    const username = config.app_info.username;
    const password = config.app_info.password;

    const xhr = new XMLHttpRequest();
    xhr.open("POST", kvm_session_url, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Authorization", "Basic " + btoa(username + ":" + password));
    xhr.withCredentials = true;

    xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
            console.log("KVM Session Request successful:", xhr.responseText);
            const response = JSON.parse(xhr.responseText);
            temp_username = response.TempUsername;
            temp_password = response.TempPassword;

            console_url = bmc_url(`/restgui/vconsole/index.html?ip=${netloc}&kvmport=443&title=${config.app}&VCSID=${temp_username}&VCSID2=${temp_password}`);

            console.log("idrac-graphical loading console", console_url);
            window.location.href = console_url; // Redirect to the KVM session
        } else {
            console.error("KVM Session Request failed:", xhr.status, xhr.statusText);
            set_error(`Failed to get console credentials: (${xhr.status}) ${xhr.statusText}`);
        }
    };

    xhr.onerror = function () {
        console.error("KVM Session Request network error.");
        set_error(`Failed to get console credentials: (${xhr.status}) ${xhr.statusText}`);
    };

    console.log("idrac-graphical sending request to:", xhr);
    xhr.send(JSON.stringify({ "SessionTypeName": config.app }));
}
