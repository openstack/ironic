#!/usr/bin/env python3

import hashlib
import json
import os
import socket
import ssl
import sys

from urllib.parse import urlparse

app_name = os.environ.get("APP", "fake")
app_info = json.loads(os.environ.get("APP_INFO"))
verify = app_info.get("verify_ca", True)
print("""# PSM Certificate Override Settings file
# This is a generated file!  Do not edit.
""")

address = app_info.get("address")
if verify or not address:
    sys.exit(0)

try:
    parsed_url = urlparse(address)
    addr = parsed_url.hostname
    port = parsed_url.port or 443

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with socket.create_connection((addr, int(port)), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname=addr) as wrappedSocket:
            der_cert_bin = wrappedSocket.getpeercert(True)

            digest = hashlib.sha256(der_cert_bin).hexdigest()
            formatted_digest = ':'.join(
                a + b for a, b in zip(digest[::2], digest[1::2])).upper()

    print(f"{addr}:{port}:\tOID.2.16.840.1.101.3.4.2.1\t{formatted_digest}\t")
except Exception as e:
    print("# Problem fetching certificate fingerprint.")
    print(f"# {e}")