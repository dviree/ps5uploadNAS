# LZ4 Compression - NAS (Linux) build of the engine.
#
# Builds the same engine as the PS5 payload, as a normal Linux program that
# serves the web page on port 5920. Run from the repository root:
#   make -f nas/Makefile
# No PS5 SDK is needed. See nas/README.md.

SHELL := bash

CC ?= cc
AR ?= ar
PYTHON ?= python3

OUT := build/nas
BIN := $(OUT)/lz4-compression
BUILD_VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)-nas

# Shared engine sources. The PS5-only modules (notifications, power guard,
# home screen tile, ShadowMountPlus, md image mounts) are replaced by the
# nas/src versions below.
C_SRCS := src/lzc_main.c src/lzc_websrv.c src/lzc_api.c src/lzc_job.c \
  src/lzc_diag.c src/lzc_size_cache.c src/lzc_icon_thumb.c \
  src/ampr_index.c src/asset.c src/pfs_compress.c src/pfs_decompress.c \
  src/pfs_repair.c src/pfs_ampr_hotswap.c src/pfs_block_pipeline.c \
  src/pfs_validate_hash.c src/miniz_tinfl.c src/ampr_pack.c \
  src/ampr_pack_profile.c src/ampr_pack_toml.c src/ampr_pack_runtime.c \
  src/lzc_boot_files.c
C_SRCS += nas/src/lzc_nas_platform.c nas/src/lzc_notify_nas.c \
  nas/src/lzc_power_guard_nas.c nas/src/lzc_app_installer_nas.c \
  nas/src/lzc_shadowmount_nas.c nas/src/lzc_image_mount_nas.c

ASSETS := $(wildcard assets/*)
GEN_SRCS := $(patsubst assets/%,$(OUT)/gen/assets/%,$(ASSETS:=.c))
AMPR_RUNTIME := third_party/ampr_emu/libSceAmpr.sprx
AMPR_RUNTIME_SHA256 := 69e6c4d5e4f5fb83c9e01815db5861c4c75734acbf4595cafa50d4c218116d1a
AMPR_RUNTIME_GEN := $(OUT)/gen/ampr_runtime_blob.c
PROFILES := profiles/index.json $(wildcard profiles/*.toml)
PROFILES_GEN := $(OUT)/gen/lz4_profiles.c

LZ4_SRCS := third_party/lz4/lz4.c third_party/lz4/lz4hc.c
QR_SRCS := third_party/qrcodegen/qrcodegen.c
ZLIB_SRCS := $(addprefix third_party/zlib/,adler32.c compress.c crc32.c \
  deflate.c infback.c inffast.c inflate.c inftrees.c trees.c uncompr.c zutil.c)

OBJS := $(patsubst %.c,$(OUT)/obj/%.o,$(C_SRCS) $(LZ4_SRCS) $(ZLIB_SRCS) $(QR_SRCS))
OBJS += $(patsubst %.c,%.o,$(GEN_SRCS) $(AMPR_RUNTIME_GEN) $(PROFILES_GEN))

CFLAGS ?= -O2
CFLAGS += -std=gnu11 -pthread -Wall -Wno-format-truncation -Wno-restrict \
  -Wno-unused-function
CFLAGS += -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64
CFLAGS += -include nas/src/lzc_nas_compat.h
CFLAGS += -Isrc -Ithird_party/lz4 -Ithird_party/zlib -Ithird_party/qrcodegen
CFLAGS += -DLZC_VERSION=\"$(BUILD_VERSION)\" -DBUILD_VERSION=\"$(BUILD_VERSION)\"
CFLAGS += -DLZC_PORT=5920 -DVERSION_TAG=\"lz4-compression\"
CFLAGS += -DMINIZ_USE_UNALIGNED_LOADS_AND_STORES=1
CFLAGS += -DLZC_PFSC_ZLIB_LEVEL=7 -DLZC_PFSC_THRESHOLD_GAIN=5 \
  -DLZC_PFSC_FORCE_RAW_EXEC=1
LDFLAGS ?=
LDLIBS := -pthread -lm

all: $(BIN)

$(OUT)/gen/assets/%.c: assets/%
	mkdir -p $(dir $@)
	$(PYTHON) gen-asset-module.py --path $* $< > $@.tmp
	mv $@.tmp $@

$(AMPR_RUNTIME_GEN): $(AMPR_RUNTIME) tools/gen_binary_c.py
	mkdir -p $(dir $@)
	$(PYTHON) tools/gen_binary_c.py --symbol lzc_ampr_runtime_blob \
	  --sha256 $(AMPR_RUNTIME_SHA256) $< > $@.tmp
	mv $@.tmp $@

$(PROFILES_GEN): $(PROFILES) tools/gen_profiles_c.py
	mkdir -p $(dir $@)
	$(PYTHON) tools/gen_profiles_c.py profiles/index.json > $@.tmp
	mv $@.tmp $@

$(OUT)/gen/%.o: $(OUT)/gen/%.c
	$(CC) $(CFLAGS) -c $< -o $@

$(OUT)/obj/third_party/%.o: third_party/%.c
	mkdir -p $(dir $@)
	$(CC) -O2 -Ithird_party/lz4 -Ithird_party/zlib -c $< -o $@

$(OUT)/obj/%.o: %.c $(wildcard src/*.h) nas/src/lzc_nas_compat.h
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BIN): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $(OBJS) $(LDLIBS)

clean:
	rm -rf $(OUT)

.SECONDARY: $(GEN_SRCS) $(AMPR_RUNTIME_GEN) $(PROFILES_GEN)
.PHONY: all clean
