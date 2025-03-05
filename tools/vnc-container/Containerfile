FROM quay.io/centos/centos:stream9

RUN dnf -y install \
    epel-release && \
    dnf -y install \
    chromium \
    chromedriver \
    dumb-init \
    procps \
    psmisc \
    python3-requests \
    python3-selenium \
    x11vnc \
    xorg-x11-server-Xvfb

ENV DISPLAY_WIDTH=1280
ENV DISPLAY_HEIGHT=960

ENV APP='fake'

ADD bin/* /usr/local/bin
ADD drivers /drivers

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/usr/local/bin/start-xvfb.sh"]