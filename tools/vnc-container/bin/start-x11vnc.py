#!/usr/bin/env python3

"""Entry point for the VNC console container.

This script:
1. Discovers the console app (vendor) by querying the BMC
2. Writes the extension config and patches the manifest
3. Generates Firefox policies
4. Starts an HTTP server for extension shutdown signalling
5. Starts x11vnc with hooks to start/stop Firefox
6. Handles SIGTERM for graceful shutdown of console websockets
"""

import http.server
import json
import logging
import os
import signal
import subprocess
import threading
from urllib import parse

import requests

LOG = logging.getLogger(__name__)

EXTENSION_PATH = os.environ['EXTENSION_PATH']
APP_INFO = os.environ.get('APP_INFO') or '{}'
APP = os.environ.get('APP') or 'fake'
READ_ONLY = os.environ.get('READ_ONLY') or 'False'
DISPLAY_WIDTH = os.environ.get('DISPLAY_WIDTH') or '1280'
DISPLAY_HEIGHT = os.environ.get('DISPLAY_HEIGHT') or '960'
FIREFOX = os.environ.get('FIREFOX') or 'firefox'

REDFISH_SUPPORTED = {'Dell', 'Hpe', 'Supermicro'}


shutdown_requested = False
shutdown_complete = threading.Event()


class ShutdownHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for browser shutdown signalling.

    Endpoints:
      GET  /browser-shutdown          - 200 if shutdown requested,
                                        404 otherwise
      POST /browser-shutdown          - Request shutdown
      POST /browser-shutdown-complete - Signal shutdown complete
    """

    def do_GET(self):
        if self.path == '/browser-shutdown':
            if shutdown_requested:
                LOG.info('GET /browser-shutdown -> 200 (shutdown requested)')
                self.send_response(200)
            else:
                # LOG.debug('GET /browser-shutdown -> 404')
                self.send_response(404)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/browser-shutdown':
            LOG.info('POST /browser-shutdown -> 200 (initiating shutdown)')
            self.send_response(200)
            self.end_headers()
            threading.Thread(
                target=graceful_shutdown_browser, daemon=True
            ).start()
        elif self.path == '/browser-shutdown-complete':
            LOG.info('POST /browser-shutdown-complete -> 200 '
                     '(extension confirmed)')
            shutdown_complete.set()
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def discover_app(app_name, app_info):
    """Discover the console vendor by querying the BMC."""
    if app_name == 'fake':
        return 'fake'
    if app_name == 'redfish-graphical':
        url = app_info['address'] + app_info.get('root_prefix', '/redfish/v1')
        verify = app_info.get('verify_ca', True)
        r = requests.get(url, verify=verify, timeout=60).json()
        oem = ','.join(r['Oem'].keys())
        if oem in REDFISH_SUPPORTED:
            return oem
        raise Exception(f'Unsupported {app_name} vendor {oem}')
    raise Exception(f'Unknown app name {app_name}')


def write_extension_config(app_name, app_info_raw):
    """Write the extension config.js with app name and info."""
    config_path = os.path.join(EXTENSION_PATH, 'config.js')
    with open(config_path, 'w') as f:
        f.write('let config = {\n')
        f.write(f'    app: "{app_name}",\n')
        f.write(f'    app_info: {app_info_raw}\n')
        f.write('};\n')


def patch_manifest(app_name):
    """Replace APP_NAME placeholders in the extension manifest."""
    manifest_path = os.path.join(EXTENSION_PATH, 'manifest.json')
    with open(manifest_path, 'r') as f:
        content = f.read()
    content = content.replace('APP_NAME', app_name)
    with open(manifest_path, 'w') as f:
        f.write(content)


def build_policies(app_name, app_info, error):
    """Build the Firefox enterprise policies dict."""
    debug = int(os.environ.get('DEBUG') or 0)
    verify = app_info.get('verify_ca') or True

    if app_name == 'fake':
        # Extensions cannot set file:// URLs so special case the fake driver
        homepage = 'file:///drivers/fake/index.html'
    else:
        homepage = 'file:///drivers/launch/index.html'
        if error:
            homepage += f'?error={error}'

    policies = {
        'AppAutoUpdate': False,
        'AutofillAddressEnabled': False,
        'AutofillCreditCardEnabled': False,
        'DisableAppUpdate': True,
        'DisableFirefoxScreenshots': True,
        'DisableFirefoxStudies': True,
        'DisablePocket': True,
        'DisableSystemAddonUpdate': True,
        'DisableTelemetry': True,
        'DontCheckDefaultBrowser': True,
        'Homepage': {
            'URL': homepage,
            'StartPage': 'homepage',
        },
        'NoDefaultBookmarks': True,
        'OfferToSaveLogins': False,
        'OverrideFirstRunPage': '',
        'OverridePostUpdatePage': '',
        'PasswordManagerEnabled': False,
        'Preferences': {
            'security.ssl.enable_ocsp_stapling': {
                'Value': verify,
                'Status': 'locked',
            },
            'dom.disable_open_during_load': {
                'Value': False,
                'Status': 'locked',
            },
        },
        'PrintingEnabled': False,
        'PromptForDownloadLocation': False,
        'SanitizeOnShutdown': True,
        'SkipTermsOfUse': True,
        'StartDownloadsInTempDirectory': True,
        'WebsiteFilter': {
            'Block': ['<all_urls>'],
            'Exceptions': ['file:///drivers/*'],
        },
    }

    if not debug:
        policies.update({
            'BlockAboutConfig': True,
            'BlockAboutAddons': True,
            'BlockAboutProfiles': True,
            'BlockAboutSupport': True,
        })

    address = app_info.get('address')
    if address:
        policies['WebsiteFilter']['Exceptions'].append(f'{address}/*')

    return policies


def write_policies(app_name, app_info, error):
    """Generate and write Firefox policies."""
    os.makedirs('/etc/firefox/policies', exist_ok=True)
    policies = build_policies(app_name, app_info, error)
    with open('/etc/firefox/policies/policies.json', 'w') as f:
        json.dump({'policies': policies}, f, indent=2)


def start_http_server():
    """Start an HTTP server for shutdown signalling.

    The browser extension cannot fetch file:// URLs from its background
    script, so shutdown state is communicated over HTTP instead.
    """
    server = http.server.HTTPServer(('127.0.0.1', 8888), ShutdownHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    LOG.info('Shutdown HTTP server listening on port 8888')
    return server


def graceful_shutdown_browser():
    """Signal the extension to navigate tabs away, then kill Firefox.

    Sets a flag that the browser extension detects via HTTP polling.
    When detected, the extension navigates all tabs to about:blank,
    triggering a clean websocket close. The extension then POSTs to
    signal it is safe to kill the browser.
    """
    result = subprocess.run(
        ['pgrep', '-x', FIREFOX],
        capture_output=True
    )
    if result.returncode != 0:
        LOG.debug('Browser is not running, skipping graceful shutdown')
        return

    LOG.info('Requesting graceful browser shutdown')
    global shutdown_requested
    shutdown_requested = True
    if shutdown_complete.wait(timeout=10):
        LOG.info('Browser shutdown complete, terminating %s', FIREFOX)
    else:
        LOG.warning('Timed out waiting for browser shutdown, '
                    'terminating %s', FIREFOX)
    subprocess.run(
        ['killall', '-s', 'SIGTERM', FIREFOX],
        capture_output=True
    )
    shutdown_requested = False
    shutdown_complete.clear()


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    # Discover the app (vendor)
    app_info = json.loads(APP_INFO)
    error = None
    try:
        app_name = discover_app(APP, app_info)
    except Exception as e:
        error = parse.quote(str(e))
        app_name = 'error'
        LOG.error('App discovery failed: %s', e)

    LOG.info('App: %s', app_name)

    # Configure the extension
    write_extension_config(app_name, APP_INFO)
    patch_manifest(app_name)
    write_policies(app_name, app_info, error)

    os.environ['X11VNC_CREATE_GEOM'] = (
        f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}x24'
    )

    # Start HTTP server for extension shutdown signalling
    http_server = start_http_server()

    # Build and start x11vnc command
    cmd = [
        'runuser', '-u', 'firefox', '--',
        'x11vnc', '-ncache', '10'
    ]
    if READ_ONLY == 'True':
        cmd += ['-viewonly', '-nocursor']
    cmd += [
        '-create', '-shared', '-forever',
        '-afteraccept', 'start-firefox.sh',
        '-gone', 'stop-firefox.sh',
    ]

    LOG.info('Starting x11vnc')
    process = subprocess.Popen(cmd)

    # Handle SIGTERM: gracefully close console websockets before
    # killing Firefox, then terminate x11vnc.
    def handle_signal(signum, frame):
        LOG.info('Received signal %s, shutting down', signum)
        threading.Thread(
            target=graceful_shutdown_browser, daemon=True
        ).start()
        process.terminate()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    process.wait()
    LOG.info('x11vnc exited with code %s', process.returncode)

    # If x11vnc exits while stop-firefox.sh is still waiting for the
    # browser extension to complete its graceful shutdown, wait here to
    # avoid the container exiting prematurely.
    if shutdown_requested:
        LOG.info('Waiting for browser shutdown to complete')
        shutdown_complete.wait(timeout=10)

    http_server.shutdown()
    LOG.info('Shutdown complete')


if __name__ == '__main__':
    main()
