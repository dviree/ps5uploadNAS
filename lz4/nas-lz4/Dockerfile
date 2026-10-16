# ps5-lz4: LZ4 HC packing of PS5 games for APR-EMU, run entirely on the NAS.
# Build from the repository root:
#   docker build -t ps5-lz4:local -f nas-lz4/Dockerfile .

FROM python:3.12-slim-bookworm AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev make \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY src ./src
COPY third_party ./third_party
COPY tools/gen_binary_c.py ./tools/
COPY tests/host ./tests/host
# The upstream host Makefile uses -Werror; GCC (unlike clang) warns about an
# intentionally truncated 16-byte keyword buffer in ampr_pack_profile.c.
RUN CFLAGS="-O2 -Wno-error=format-truncation" make -f tests/host/Makefile PYTHON=python3 \
 && strip build/host/ampr_pack_cli \
 && build/host/ampr_pack_cli 2>&1 | grep -q 'verify <packed>'

FROM python:3.12-slim-bookworm
ARG MKPFS_VERSION=1.1.0
# unrar (RARLAB's freeware, from Debian non-free): extracts multi-part RAR5
# archives in the library, checking every file's CRC.
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends unrar \
 && rm -rf /var/lib/apt/lists/* \
 && unrar | head -1
RUN pip install --no-cache-dir "mkpfs==${MKPFS_VERSION}" \
 && mkpfs -V | grep -q "${MKPFS_VERSION}" \
 && python3 -c "from mkpfs.exfat import ExfatReader; import cryptography"
COPY --from=build /src/build/host/ampr_pack_cli /usr/local/bin/ampr_pack_cli
COPY profiles /opt/ps5lz4/profiles
COPY compat/compat.json /opt/ps5lz4/compat.json
COPY nas-lz4/ps5lz4.py /opt/ps5lz4/ps5lz4.py
COPY nas-lz4/ui.html /opt/ps5lz4/ui.html
COPY nas-lz4/store.html /opt/ps5lz4/store.html
COPY nas-lz4/ps5regist.py /opt/ps5lz4/ps5regist.py
COPY app/lz4-compression/version.js /opt/ps5lz4/lz4c-version.js
COPY third_party/ampr_emu/libSceAmpr.sprx /opt/ps5lz4/libSceAmpr.sprx
COPY nas-lz4/entrypoint.sh /usr/local/bin/ps5lz4-entrypoint
COPY nas-lz4/busy.sh /usr/local/bin/ps5lz4-busy
RUN printf '#!/bin/sh\nexec python3 /opt/ps5lz4/ps5lz4.py "$@"\n' > /usr/local/bin/ps5lz4 \
 && chmod 755 /usr/local/bin/ps5lz4 /opt/ps5lz4/ps5lz4.py \
 && chmod -R a+rX /opt/ps5lz4
ENV PS5LZ4_LIBRARY=/library \
    PS5LZ4_OUTPUT=/output \
    PS5LZ4_STATE=/state \
    PS5LZ4_PACKER=/usr/local/bin/ampr_pack_cli \
    PS5LZ4_PROFILES=/opt/ps5lz4/profiles \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="ps5-lz4" \
      org.opencontainers.image.description="LZ4 HC packing of PS5 games for APR-EMU on a NAS"
LABEL org.opencontainers.image.source="https://github.com/dviree/PS5-LZ4-NAS"
# Resume an unfinished queue, then idle until `docker exec ps5-lz4 ps5lz4 ...`.
CMD ["/usr/local/bin/ps5lz4-entrypoint"]
