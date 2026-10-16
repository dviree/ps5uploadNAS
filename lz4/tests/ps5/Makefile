# PS5 self-test payload for the AMPR LZ4 packer.
#   make -f tests/ps5/Makefile        (from the repository root)
# Upload a game tree to /data/lz4test/game, then load lz4-selftest.elf
# with Payload Manager. Results: /data/lz4test/selftest.log, result.json.

ifeq ($(strip $(PS5_PAYLOAD_SDK)),)
$(error PS5_PAYLOAD_SDK is required)
endif
include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk

PYTHON ?= python3
OUT := build/ps5-selftest
BIN := $(OUT)/lz4-selftest.elf
SRCS := tests/ps5/lz4_selftest.c src/ampr_pack.c src/ampr_pack_profile.c \
  src/ampr_pack_toml.c src/ampr_pack_runtime.c src/ampr_index.c \
  third_party/lz4/lz4.c third_party/lz4/lz4hc.c \
  $(addprefix third_party/zlib/,adler32.c crc32.c zutil.c)
GEN := $(OUT)/ampr_runtime_blob.c
CFLAGS := -O2 -Wall -Werror -Isrc -Ithird_party/lz4 -Ithird_party/zlib

all: $(BIN)

$(GEN): third_party/ampr_emu/libSceAmpr.sprx tools/gen_binary_c.py
	mkdir -p $(OUT)
	$(PYTHON) tools/gen_binary_c.py --symbol lzc_ampr_runtime_blob \
	  --sha256 69e6c4d5e4f5fb83c9e01815db5861c4c75734acbf4595cafa50d4c218116d1a $< > $@

$(BIN): $(SRCS) $(GEN) src/*.h
	"$(CC)" $(CFLAGS) -o $@ $(SRCS) $(GEN)
	"$(STRIP)" --strip-all $@

clean:
	rm -rf $(OUT)

.PHONY: all clean
