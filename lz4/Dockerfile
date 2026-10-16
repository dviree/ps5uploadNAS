# LZ4 Compression engine for a NAS. Everything runs here; nothing runs on
# the PS5. See nas/README.md.

FROM debian:bookworm-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev make python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
ARG BUILD_VERSION=nas
RUN make -f nas/Makefile -j"$(nproc)" BUILD_VERSION="$BUILD_VERSION" \
 && strip build/nas/lz4-compression

FROM debian:bookworm-slim
# mount: loop-mounting .exfat images (privileged containers only).
# tini: forwards `docker stop` to the engine.
RUN apt-get update \
 && apt-get install -y --no-install-recommends mount tini \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /data/LZ4Compression /data/homebrew \
 && chmod 1777 /data
COPY --from=build /src/build/nas/lz4-compression /usr/local/bin/lz4-compression
COPY nas/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
EXPOSE 5920
VOLUME ["/data/LZ4Compression"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
