window.addEventListener("load", function () {
    if (window.location.protocol === "file:" && window.location.pathname.endsWith("/drivers/launch/index.html")) {
        set_status("Detecting iLO version");
        console.log("ilo-graphical driver launch page loaded");
        detectIloVersion();
    }
    else if (window.location.pathname.endsWith("/irc.html")) {
        console.log("ilo-graphical logging in");
        login(false);
    }
    else if (window.location.pathname.endsWith("/html/login.html")) {
        // ilo5 login
        console.log("ilo-graphical ilo5 logging in");
        login(true);
    }
});


/**
 * Detects the iLO version by making a Redfish API call and redirects to the appropriate login page or console.
 */
function detectIloVersion() {
    const url = redfish_url("");
    const xhr = new XMLHttpRequest();
    xhr.open("GET", url, true);
    xhr.withCredentials = true;
    xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
            console.log("Redfish Request successful:", xhr.responseText);
            const response = JSON.parse(xhr.responseText);
            manager_type = response.Oem.Hpe.Manager[0].ManagerType;
            if (manager_type == "iLO 5") {
                console.log("ilo-graphical loading login page");
                set_status("Logging in to BMC");
                const console_url = bmc_url("/html/login.html");
                window.location.href = console_url; // Redirect to the KVM session
            }
            else {
                // ilo6 console screen has an inline login
                console.log("ilo-graphical loading console");
                set_status("Loading console");
                const console_url = bmc_url("/irc.html");
                window.location.href = console_url; // Redirect to the KVM session
            }
        } else {
            console.error("iLO version detection failed:", xhr.status, xhr.statusText);
            set_error(`Failed to detect iLO version: (${xhr.status}) ${xhr.statusText}`);
        }
    }
    xhr.onerror = function () {
            console.error("iLO version detection failed:", xhr.status, xhr.statusText);
            set_error(`Failed to detect iLO version: (${xhr.status}) ${xhr.statusText}`);
    };
    xhr.send();
}


/**
 * Fills in the username and password fields and clicks the login button.
 * @param {HTMLInputElement} usernameField - The username input element.
 * @param {HTMLInputElement} passwordField - The password input element.
 * @param {HTMLButtonElement} loginButton - The login button element.
 * @param {boolean} redirect - Whether to redirect after successful login (for iLO5).
 */
function clickLoginButton(usernameField, passwordField, loginButton, redirect) {
    const username = config.app_info.username;
    const password = config.app_info.password;

    usernameField.value = username;
    passwordField.value = password;
    console.log("logging in", username);
    loginButton.click();

    if (redirect) {
        const console_url = bmc_url("/irc.html");
        let intervalId = setInterval(() => {
            if (document.cookie.includes("sessionKey")) {
                console.log("sessionKey cookie found, redirecting...");
                window.location.href = console_url;
                clearInterval(intervalId);
            } else {
                console.log("Waiting for sessionKey cookie...");
            }
        }, 200); // Check every 200 milliseconds

    }
}


/**
 * Handles the login process by filling in credentials and clicking the login button.
 * It also observes for disabled login fields and waits for them to become enabled.
 */
function login(redirect) {
    const usernameField = document.getElementById("username");
    const passwordField = document.getElementById("password");
    const loginButton = document.getElementById("login-form__submit");

    if (!usernameField || !passwordField || !loginButton) {
        console.log("Username or password field not found.");
        return;
    }

    if (usernameField.disabled) {
        console.log("Waiting for login fields to be enabled");
        const observer = new MutationObserver((mutationsList, observer) => {
            for (const mutation of mutationsList) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'disabled') {
                    if (!usernameField.disabled) {
                        console.log("Login fields are now enabled");
                        clickLoginButton(usernameField, passwordField, loginButton, redirect);
                        observer.disconnect();
                    }
                }
            }
        });
        observer.observe(usernameField, { attributes: true });
    } else {
        clickLoginButton(usernameField, passwordField, loginButton, redirect);
    }
}