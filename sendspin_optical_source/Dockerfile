FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
      python3 \
      py3-pip \
      pulseaudio-utils \
    && python3 -m venv /opt/sendspin-venv \
    && /opt/sendspin-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/sendspin-venv/bin/pip install --no-cache-dir "aiosendspin==9.1.1"

COPY app.py /app/app.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
