
/**
 * Background script that watches for a shutdown signal.
 *
 * Polls the container's HTTP server for a shutdown request. When
 * detected, all browser tabs are navigated to about:blank. This
 * triggers the standard page unload lifecycle, causing any active
 * websocket connections (e.g. Dell iDRAC KVM sessions) to be closed
 * gracefully before the browser process is killed.
 *
 * Once all tabs have been navigated, a POST request signals to the
 * container that it is safe to kill the browser process.
 */

const SHUTDOWN_URL = "http://localhost:8888/browser-shutdown";
const SHUTDOWN_COMPLETE_URL = "http://localhost:8888/browser-shutdown-complete";
const POLL_INTERVAL_MS = 500;

function checkShutdown() {
    fetch(SHUTDOWN_URL).then(response => {
        if (response.ok) {
            console.log("ironic-console: shutdown detected, closing tabs");
            browser.tabs.query({}).then(tabs => {
                let updates = tabs.map(tab =>
                    browser.tabs.update(tab.id, { url: "about:blank" })
                );
                Promise.all(updates).then(() => {
                    console.log("ironic-console: all tabs navigated to about:blank");
                    // Allow time for page unload and websocket close
                    // frames to be sent before signalling completion
                    setTimeout(() => {
                        fetch(SHUTDOWN_COMPLETE_URL, { method: "POST" });
                    }, 1000);
                });
            });
            return;
        }
        setTimeout(checkShutdown, POLL_INTERVAL_MS);
    }).catch(() => {
        // Server not ready or shutdown not requested, keep polling
        setTimeout(checkShutdown, POLL_INTERVAL_MS);
    });
}

checkShutdown();
