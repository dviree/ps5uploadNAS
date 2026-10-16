# SPDX-License-Identifier: AGPL-3.0-only
#
# PS5 Remote Play registration (pairing) for ps5-lz4.
#
# A Python port of the local (non-PSN) registration in chiaki-ng,
# lib/src/regist.c and lib/src/rpcrypt.c, Copyright (C) Chiaki contributors,
# AGPL-3.0 (https://github.com/streetpea/chiaki-ng). The key tables below are
# copied from rpcrypt.c. This file stays under the AGPL-3.0; its source is
# published with ps5-lz4 at https://github.com/dviree/PS5-LZ4-NAS.
#
# Pairing needs the console's 8-digit PIN (Settings > System > Remote Play >
# Link Device) and the PSN account ID of the signed-in user. On a jailbroken
# PS5 with a fake (offline) activated account that is the ID the activation
# tool set. The result's regist key is what wakes the PS5 from rest mode.

import base64
import hashlib
import hmac
import os
import re
import socket
import time

REGIST_PORT = 9295
CLIENT_TYPE = "dabfa2ec873de5839bee8d3f4c0239c4282c07c25c6077a2931afcf0adc0d34f"
HMAC_KEY_PS5 = bytes([0x46, 0x46, 0x87, 0xb3, 0x49, 0xca, 0x8c, 0xe8,
                      0x59, 0xc5, 0x27, 0x0f, 0x5d, 0x7a, 0x69, 0xd6])

# rpcrypt.c, chiaki_rpcrypt_init_regist(): ps5_keys_0
PS5_KEYS_0 = bytes.fromhex(
    '24d8c2694c677871ee31bd2b83b21d61c9a78eed9ad36a6b5cc83579a724e21706602edff4db271055d9ea164e900cbf'
    '406f54a531702d5d1e27df3740ba9d5dffe1057080d4b7c2967f2f42eb5a08dec1b55215f6b5f2d969a5c7c47f4664a4'
    'fd4698a7e12a8e6faf654228b9c26f3ee3e44ee45b9d6010b85ab07d040c4c2478bdb8badb8fe3a0756d28c2335b3283'
    'dd51b0a58d0966e45cb8700be68214b6d2b0c2e055f384ad9d3af877f59d9aa97df1451b9b5525d8c1ff03a5480b1b19'
    '0cbde0cd48f32c9919d6b8bbd635436f71e3ef3e97b8e940a847e0e001169da7e5944b1dd280a27ff29810380db856c3'
    '7a4b4c85ec2f2389afd5ba9aadb0619c51b46d024926a43484203530230a4714321a960ee80f9696d4ba683a671574e0'
    'd6604c685073142f1159acc832d1db4c8a94753361d1d4fdaa6a6168d8ae314fb8077b270ff90bb0c264b372ea8b8740'
    '09b482b4ad76f936056089c820eba5f1510b27a7f0768496ebb12ec28528bc4834d4018d5b2554e0c44fa0fa998d6d7a'
    '64b1a95da4f9f522eb9af4a87a784b7fe28b0450437d262d1998386a4f2d30152e4fcdb9ce9e8d12c9fe338b84ce5b40'
    'e37f726d6c8a6a9e54f1e3645d6e7fac1ae7f7fa0022ed2b23fa58c5eb44925dccaa829f23fba6c9652ae07912652c34'
    'c52316c9cc0530f3960b90671aa7694c3e43249d4e68bd8b756e9d076f1a6aba')
# rpcrypt.c, chiaki_rpcrypt_aeropause(): ps5_keys_1
PS5_KEYS_1 = bytes.fromhex(
    '794d7830fe10524ca8905b9a7e5fd3e113e0f10fa3e7bb457fdc8ed5f1045c7851eff8655903398437ae59df23b66034'
    'e64be2f54c13c6daf9fdb36584d645ec2c00f2eddccb936e6146e5d60194ee78850e685eb55bcdd36341fc81431c6f7c'
    'bae8bd8631d5707fb54a903e84e171e00299f471e702ed36afde56c290e0aec2f9af53c6d862163227fb6e9b48c6eaff'
    '6f780222982c1fbfb08ea939bcdf17ded70ee17a010ec387fcaae46b0f5b0af118198ae52c369b403099249448d747b2'
    'af6b8c409e4d6d3407c1262fbb14f7bc3652bd84fe4a9af48adb3489aaf10d940b92f41ce46c792d6ec0190ad5559414'
    '0513c26223b3d426c444567acd1cead474b936409f08fb4962059298ad1d9f8a768bd40f214076b61691459366cc12ea'
    '4df409e2ac33d06f4351073ed7952c1e1f0c24b30e3aef95f5eb77dd20f23598f2aea966e613ef5d3a2d66ede21ee932'
    '4a40bf37c67029d98ca1614a293dc7559c949ec911451028a727d1d3d08479c7a9b0f6af458c3cd4df3bf70da24f1397'
    '7827f048c0a5ab830105d012d71e123a4e9877aebab14eb53b59ca6da51180919c0769595a53707c9597116d668da3bd'
    'bb2db0bf9b10cbc70f5b7e67e2b04bba1012b9bc97fd48e48ac10fa1309d5620241a7d5ba0b4be9d384fb456a84d137c'
    '44e88497eb782c5285e4a2f6f3d9719eeeb81147fba91bc740c6e1196d50a12a')


class RegistError(Exception):
    pass


def account_id_bytes(text: str) -> bytes:
    """PSN account ID as Chiaki wants it: 8 bytes, little endian. Accepts the
    base64 form Chiaki shows (12 characters), a decimal number or 0x-hex."""
    t = text.strip()
    if re.fullmatch(r"[A-Za-z0-9+/]{11}=", t):
        raw = base64.b64decode(t)
        if len(raw) == 8:
            return raw
    if re.fullmatch(r"\d{1,20}", t):
        return int(t).to_bytes(8, "little")
    if re.fullmatch(r"0x[0-9A-Fa-f]{1,16}", t):
        return int(t, 16).to_bytes(8, "little")
    raise RegistError("account ID must be base64 (like Chiaki: 12 characters ending in =), "
                      "a decimal number or 0x-hex")


class RPCrypt:
    """chiaki_rpcrypt for target PS5_1, registration keys."""

    def __init__(self, ambassador: bytes, key_0_off: int, pin: int):
        self.ambassador = ambassador
        bright = bytearray(PS5_KEYS_0[i * 0x20 + key_0_off] for i in range(16))
        for n, shift in enumerate((0x18, 0x10, 0x08, 0x00)):
            bright[0xc + n] ^= (pin >> shift) & 0xff
        self.bright = bytes(bright)

    def _cipher(self, counter: int):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        try:
            from cryptography.hazmat.decrepit.ciphers.modes import CFB
        except ImportError:  # cryptography < 47
            from cryptography.hazmat.primitives.ciphers.modes import CFB
        iv = hmac.new(HMAC_KEY_PS5, self.ambassador + counter.to_bytes(8, "big"), hashlib.sha256).digest()[:16]
        return Cipher(algorithms.AES(self.bright), CFB(iv))

    def encrypt(self, data: bytes, counter: int = 0) -> bytes:
        e = self._cipher(counter).encryptor()
        return e.update(data) + e.finalize()

    def decrypt(self, data: bytes, counter: int = 0) -> bytes:
        d = self._cipher(counter).decryptor()
        return d.update(data) + d.finalize()


def aeropause(ambassador: bytes, key_1_off: int) -> bytes:
    wurzelbert = 0xd3  # (uint8_t)-0x2d for PS5
    return bytes(((ambassador[i] ^ PS5_KEYS_1[i * 0x20 + key_1_off]) + wurzelbert + i) & 0xff
                 for i in range(16))


def build_request(account_id: bytes, pin: int, ambassador: bytes | None = None):
    """(header bytes, payload bytes, RPCrypt) as chiaki_regist builds them."""
    ambassador = ambassador or os.urandom(16)
    buf = bytearray(b"A" * 0x1e0)  # "can be random"
    key_0_off = buf[0x18d] & 0x1f
    key_1_off = buf[0] >> 3
    crypt = RPCrypt(ambassador, key_0_off, pin)
    aero = aeropause(ambassador, key_1_off)
    buf[0xc7:0xc7 + 8] = aero[8:16]
    buf[0x191:0x191 + 8] = aero[0:8]
    inner = (f"Client-Type: {CLIENT_TYPE}\r\n"
             f"Np-AccountId: {base64.b64encode(account_id).decode()}\r\n").encode()
    payload = bytes(buf) + crypt.encrypt(inner)
    header = ("POST /sie/ps5/rp/sess/rgst HTTP/1.1\r\n HTTP/1.1\r\n"
              "HOST: 10.0.2.15\r\n"
              "User-Agent: remoteplay Windows\r\n"
              "Connection: close\r\n"
              f"Content-Length: {len(payload)}\r\n"
              "RP-Version: 1.0\r\n"
              "\r\n").encode()
    return header, payload, crypt


def parse_response(body: bytes, crypt: RPCrypt) -> dict:
    text = crypt.decrypt(body).decode(errors="replace")
    fields = {}
    for line in text.split("\r\n"):
        k, sep, v = line.partition(":")
        if sep:
            fields[k.strip()] = v.strip()
    if "PS5-RegistKey" not in fields or "RP-Key" not in fields:
        raise RegistError("the PS5 answered without a regist key (wrong PIN or account ID?)")
    regist_key = bytes.fromhex(fields["PS5-RegistKey"]).split(b"\0")[0].decode()
    return {"regist_key": regist_key, "rp_key": fields["RP-Key"],
             "mac": fields.get("PS5-Mac", ""), "nickname": fields.get("PS5-Nickname", ""),
             "key_type": fields.get("RP-KeyType", "")}


def register(host: str, pin: str, account_id: str, timeout: float = 3.0) -> dict:
    """Pair with the PS5 at `host`. Returns regist_key (for wake-up), rp_key,
    mac and nickname, like a registered host in Chiaki."""
    if not re.fullmatch(r"\d{8}", pin.strip()):
        raise RegistError("the PIN is the 8 digits shown on the PS5 under Remote Play > Link Device")
    header, payload, crypt = build_request(account_id_bytes(account_id), int(pin.strip()))
    # 1. regist search: SRC3 -> RES3 on UDP 9295
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as us:
        us.settimeout(timeout)
        us.connect((host, REGIST_PORT))
        us.send(b"SRC3\0")
        try:
            deadline = time.time() + timeout
            while True:
                data = us.recv(0x100)
                if data.startswith(b"RES3"):
                    break
                if time.time() > deadline:
                    raise socket.timeout()
        except (socket.timeout, OSError):
            raise RegistError("the PS5 did not answer the pairing search: is it on and showing "
                              "the Remote Play PIN (Settings > System > Remote Play > Link Device)?")
    time.sleep(0.1)  # "PS4 doesn't accept requests immediately"
    # 2. registration request over TCP 9295
    with socket.create_connection((host, REGIST_PORT), timeout=timeout) as ts:
        ts.sendall(header)
        ts.sendall(payload)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = ts.recv(1500)
            if not chunk:
                break
            buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")
        lines = head.decode(errors="replace").split("\r\n")
        m = re.match(r"HTTP/1\.\d (\d+)", lines[0] if lines else "")
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
        if not m or m.group(1) != "200":
            reason = headers.get("rp-application-reason", "")
            raise RegistError(f"the PS5 refused the pairing ({lines[0] if lines else 'no answer'}"
                              f"{', reason 0x' + reason if reason else ''}): check the PIN and account ID")
        size = int(headers.get("content-length", "0"))
        while len(body) < size:
            chunk = ts.recv(size - len(body))
            if not chunk:
                break
            body += chunk
    return parse_response(body[:size], crypt)
