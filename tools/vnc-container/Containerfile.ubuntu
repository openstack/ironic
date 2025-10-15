FROM ubuntu:noble

# firefox-esr is installed from the mozillateam ppa because the ubuntu
# packaged fedora exits with a message to install the snap

RUN apt-get update && \
    apt-get install -y \
    dumb-init \
    iproute2 \
    procps \
    psmisc \
    python3-requests \
    software-properties-common \
    x11vnc \
    xvfb && \
    add-apt-repository ppa:mozillateam/ppa && \
    apt-get install -y \
    firefox-esr && \
    useradd --create-home --shell /bin/bash firefox

ENV DISPLAY_WIDTH=1280
ENV DISPLAY_HEIGHT=960

ENV APP='fake'
ENV APP_INFO={}
ENV READ_ONLY=False
ENV DEBUG=0
ENV FIREFOX=firefox-esr
ENV FIREFOX_CONFIG_DIR=/home/firefox/.mozilla/firefox-esr
ENV EXTENSION_PATH="/usr/lib/firefox-esr-addons/extensions/@ironic-console.openstack.org"

ADD bin/* /usr/local/bin
ADD drivers /drivers
ADD extension /usr/lib/firefox-esr-addons/extensions/@ironic-console.openstack.org

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/usr/local/bin/start-x11vnc.sh"]