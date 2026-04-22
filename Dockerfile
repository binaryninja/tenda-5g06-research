FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binwalk \
        ca-certificates \
        curl \
        file \
        gcc-aarch64-linux-gnu \
        gzip \
        iproute2 \
        jq \
        net-tools \
        p7zip-full \
        procps \
        python3 \
        qemu-user-static \
        squashfs-tools \
        strace \
        tar \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tenda-b104
COPY scripts/ /opt/tenda-b104/scripts/
RUN chmod +x /opt/tenda-b104/scripts/*.py /opt/tenda-b104/scripts/*.sh
RUN aarch64-linux-gnu-gcc \
        -nostdlib -shared -fPIC -O2 -ffreestanding -fno-builtin -fno-stack-protector \
        -Wl,-soname,libtenda-httpd-shim.so \
        -o /opt/tenda-b104/libtenda-httpd-shim.so \
        /opt/tenda-b104/scripts/native_httpd_shim.c

ENV FIRMWARE_ARCHIVE=/firmware/downloads/sample_latest.zip
ENV WORKDIR=/work
ENV FIRMWARE_CMD=/bin/sh

ENTRYPOINT ["/opt/tenda-b104/scripts/run_qemu.sh"]
