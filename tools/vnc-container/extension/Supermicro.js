window.addEventListener("load", function () {
    if (window.location.protocol === "file:" && window.location.pathname.endsWith("/drivers/launch/index.html")) {
        console.log("supermicro-graphical driver launch page loaded");
        window.location.replace(bmc_url("/"));
    }
    else if (window.location.pathname.endsWith("/")) {
        console.log("supermicro-graphical logging in");
        login();
    }
    else if (window.location.search.includes("url_name=mainmenu")) {
        console.log("supermicro-graphical waiting for console to be ready");
        waitForConsoleSnapshot();
    }
    else if (window.location.search.includes("url_name=man_ikvm_html5_bootstrap")) {
        console.log("supermicro-graphical console page loaded");
    }
});


/**
 * Fills in the username and password fields and clicks the login button.
 */
function login() {
    const username_field = document.querySelector('input[name="name"]');
    const password_field = document.getElementById('pwd');
    const login_button = document.getElementById('login_word');

    if (username_field && password_field && login_button) {
        username_field.value = config.app_info.username;
        password_field.value = config.app_info.password;
        login_button.click();
    } else {
        console.error("Login elements not found.", username_field, password_field, login_button);
    }
}


/**
 * Waits for the console snapshot image to load and then clicks it to launch the HTML5 KVM console.
 */
function waitForConsoleSnapshot() {

    const checkExist = setInterval(() => {
        const topMenuFrame = document.getElementById("TOPMENU");
        const topMenuDoc = topMenuFrame.contentDocument || topMenuFrame.contentWindow.document;
        if (! topMenuDoc){
            console.log('waiting for topMenuDoc...');
            return;
        }
        const mainFrame = topMenuDoc.getElementById("frame_main");
        const mainDoc = mainFrame.contentDocument || mainFrame.contentWindow.document;
        if (! mainDoc){
            console.log('waiting for mainDoc...');
            return;
        }
        const img1 = mainDoc.getElementById("img1");
        if (! img1){
            console.log('waiting for img1');
            return;
        }
        console.log('waiting for img1 to load')
        if (img1 && img1.src.includes("Snapshot") && img1.complete) {
            console.log("supermicro-graphical snapshot ready, clicking");
            clearInterval(checkExist);
            // override onclick to open as a tab instead of a popup
            img1.onclick = () => {
                window.open(bmc_url("/cgi/url_redirect.cgi?url_name=man_ikvm_html5_bootstrap"));
            }
            // open by clicking so that window.opener is set on the console page
            img1.click();
        }
    }, 1000);
}