# ps5-lz4: LZ4 NG and Zstd packing of PS5 games for ampr-emu-ng (PS5 Dump Forge),
# run entirely on the NAS.
# Build from the repository root:
#   docker build -t ps5-lz4:local -f nas-lz4/Dockerfile .

# ampr-emu-ng main after v0.3.5: fd read thread priority (#51), on-demand
# index reads and exact-size pack reads. Built from upstream without local patches.
FROM rust:1.99.0-slim-trixie@sha256:24e632c09342c20abf8312cf4f61430a911c01ed3a5e4c02b87292b1c39c5273 AS ng-runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates clang-19 lld-19 llvm-19 make curl unzip python3 git \
    && rm -rf /var/lib/apt/lists/*
ENV PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk LLVM_CONFIG=/usr/bin/llvm-config-19
ENV PATH=/usr/lib/llvm-19/bin:$PATH
ENV RUSTUP_TOOLCHAIN=1.99.0 RUSTUP_AUTO_INSTALL=0
RUN curl -fsSL --retry 3 https://github.com/ps5-payload-dev/sdk/releases/download/v0.43/ps5-payload-sdk.zip -o /tmp/sdk.zip \
    && echo 'a9cc9929f21b2b2c5d5b309f3bab4997067c45281c0622cf4838b1aecba66fcb  /tmp/sdk.zip' | sha256sum -c - \
    && unzip -q /tmp/sdk.zip -d /opt && rm /tmp/sdk.zip
RUN rustup component add rust-src
WORKDIR /runtime
# Pinned by commit: the checkout must be exactly this commit (its hash covers every
# file); source.tar.gz is made from it for the corresponding-source requirement.
ARG NG_COMMIT=0a5670a5d629c78572c61b66353a04e56f1b53d2
RUN git init -q source && git -C source fetch -q --depth 1 https://github.com/quer3q/ampr-emu-ng "$NG_COMMIT" \
    && git -C source checkout -q FETCH_HEAD && test "$(git -C source rev-parse HEAD)" = "$NG_COMMIT" \
    && git -C source archive --format=tar.gz --prefix="ampr-emu-ng-$NG_COMMIT/" HEAD > source.tar.gz \
    && rm -rf source/.git
WORKDIR /runtime/source
RUN cargo test --workspace --locked \
    && make verify AMPR_GIT_REV=0a5670a \
    && cp out/release/libSceAmpr.sprx /runtime/libSceAmpr-ng.sprx \
    && python3 -c 'import hashlib,json;from pathlib import Path;p=Path("/runtime/libSceAmpr-ng.sprx");Path("/runtime/ng-runtime.json").write_text(json.dumps({"name":"ampr-emu-ng 0a5670a (main after v0.3.5)","commit":"0a5670a5d629c78572c61b66353a04e56f1b53d2","sha256":hashlib.sha256(p.read_bytes()).hexdigest()}))'

FROM python:3.12-slim-bookworm AS forge
COPY nas-lz4/install-forge.py /tmp/install-forge.py
RUN python3 /tmp/install-forge.py

FROM python:3.12-slim-bookworm
ARG MKPFS_VERSION=1.1.0
# unrar (RARLAB's freeware, from Debian non-free): extracts multi-part RAR5
# archives in the library, checking every file's CRC. lz4 and zstd: the
# Compress dialog's size estimates from a sample of the game.
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends unrar libstdc++6 lz4 zstd \
 && rm -rf /var/lib/apt/lists/* \
 && unrar | head -1
RUN pip install --no-cache-dir "mkpfs==${MKPFS_VERSION}" \
 && mkpfs -V | grep -q "${MKPFS_VERSION}" \
 && python3 -c "from mkpfs.exfat import ExfatReader; import cryptography"
COPY --from=forge /usr/local/bin/ps5-dump-forge /usr/local/bin/ps5-dump-forge
COPY --from=forge /opt/ps5lz4/ /opt/ps5lz4/
COPY --from=ng-runtime /runtime/libSceAmpr-ng.sprx /opt/ps5lz4/libSceAmpr-ng.sprx
COPY --from=ng-runtime /runtime/ng-runtime.json /opt/ps5lz4/ng-runtime.json
COPY --from=ng-runtime /runtime/source.tar.gz /opt/ps5lz4/licenses/ampr-emu-ng-0a5670a/source.tar.gz
COPY --from=ng-runtime /runtime/source/LICENSE /opt/ps5lz4/licenses/ampr-emu-ng-0a5670a/LICENSE
COPY nas-lz4/ps5lz4.py /opt/ps5lz4/ps5lz4.py
COPY nas-lz4/ui.html /opt/ps5lz4/ui.html
COPY nas-lz4/store.html /opt/ps5lz4/store.html
COPY nas-lz4/ps5regist.py /opt/ps5lz4/ps5regist.py
COPY nas-lz4/entrypoint.sh /usr/local/bin/ps5lz4-entrypoint
COPY nas-lz4/busy.sh /usr/local/bin/ps5lz4-busy
RUN printf '#!/bin/sh\nexec python3 /opt/ps5lz4/ps5lz4.py "$@"\n' > /usr/local/bin/ps5lz4 \
 && chmod 755 /usr/local/bin/ps5lz4 /opt/ps5lz4/ps5lz4.py \
 && chmod -R a+rX /opt/ps5lz4
ENV PS5LZ4_LIBRARY=/library \
    PS5LZ4_OUTPUT=/output \
    PS5LZ4_STATE=/state \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="ps5-lz4" \
      org.opencontainers.image.description="LZ4 NG and Zstd packing of PS5 games for ampr-emu-ng on a NAS"
LABEL org.opencontainers.image.source="https://github.com/dviree/PS5-LZ4-NAS"
# Resume an unfinished queue, then idle until `docker exec ps5-lz4 ps5lz4 ...`.
CMD ["/usr/local/bin/ps5lz4-entrypoint"]
