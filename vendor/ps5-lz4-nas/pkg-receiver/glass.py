#!/usr/bin/env python3
"""Give pkg-receiver's page (Loopayeh/pkg-sender, payload/main.c) the Glass
theme of the PS5-LZ4 NAS page.

    python3 glass.py path/to/payload/main.c

Edits main.c in place: glass.css goes in as C string lines right before the
page's </style>, so pkg-sender's own CSS stays and these rules win; the build
gets a "-glass.N" suffix (REV); a missing ";" in the page script (which stops the
whole script in newer sources) is added; and Install closes the game window so
its answer shows; and the Images tab shows one card per game with a choice of
its images (glass.js; LZ4 or the original). Nothing else changes.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REV = "glass.9"  # build suffix; bump it on every change so the NAS restarts the receiver


def c_lines(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for line in css.splitlines():
        line = line.strip()
        if line:
            out.append('"' + line.replace("\\", "\\\\").replace('"', '\\"') + '"\n')
    return "".join(out)


def main() -> None:
    src = Path(sys.argv[1])
    text = src.read_text()
    if "glass.css" in text:
        sys.exit("main.c already has the Glass theme")

    end = '</style></head><body><div class=wrap>"'
    if text.count(end) != 1:
        sys.exit("can't find the end of the page CSS in main.c")
    text = text.replace(end, '"\n/* glass.css (PS5-LZ4 NAS) */\n' + c_lines((HERE / "glass.css").read_text())
                        + '"' + end, 1)

    build = re.search(r'(#define RECEIVER_BUILD ")([^"]+)(")', text)
    if not build:
        sys.exit("can't find RECEIVER_BUILD in main.c")
    text = text[:build.start()] + build.group(1) + build.group(2) + "-" + REV + build.group(3) + text[build.end():]

    text = text.replace("replaceChild(s,t);}},true)\"\n\"function card(", "replaceChild(s,t);}},true);\"\n\"function card(")

    # An Install in the game window answered behind the window: close it and
    # bring the message into view.
    start = "\"async function install(id,name,hasIcon){msg.className='';"
    if text.count(start) != 1:
        sys.exit("can't find install() in main.c")
    text = text.replace(start, "\"async function install(id,name,hasIcon){closeModal();window.scrollTo(0,0);msg.className='';", 1)
    # Images: one card per game with a choice of its images (glass.js).
    render = "\"function render(){grid.innerHTML='';var list;"
    each = "list.forEach(function(g){grid.appendChild(card(g,0));});return;}"
    if text.count(render) != 1 or text.count(each) != 1:
        sys.exit("can't find render() in main.c")
    text = text.replace(render, '/* glass.js (PS5-LZ4 NAS) */\n' + c_lines((HERE / "glass.js").read_text()) + render, 1)
    text = text.replace(each, "groupImgs(list).forEach(function(g){grid.appendChild(g.group?imgCard(g):card(g,0));});return;}", 1)

    # Keep the PS5 awake (awake.c): the code after the pull state it reads,
    # the endpoint next to /api/version, the thread at start-up, and the
    # library with the power calls in the Makefile.
    anchor = "static volatile int g_pull_paused = 0;\n"
    version = '\t} else if (!strcmp(method, "GET") &&\n\t           !strncmp(path, "/api/version", 12)) {\n'
    started = "\tpc_listen_start();\n"
    for part in (anchor, version, started):
        if text.count(part) != 1:
            sys.exit(f"can't find {part.strip()!r} in main.c")
    text = text.replace(anchor, anchor + "\n" + (HERE / "awake.c").read_text()
                        + "\n" + (HERE / "installed.c").read_text()
                        + "\n" + (HERE / "smp.c").read_text(), 1)
    text = text.replace(version, '\t} else if (!strcmp(method, "GET") &&\n\t           !strncmp(path, "/api/keep-awake", 15)) {\n'
                        "\t\tawake_api(fd, path);\n"
                        '\t} else if (!strcmp(method, "GET") &&\n\t           !strncmp(path, "/api/installed", 14)) {\n'
                        "\t\tinstalled_api(fd);\n"
                        '\t} else if (!strcmp(method, "GET") &&\n\t           !strncmp(path, "/api/df", 7)) {\n'
                        "\t\tdf_api(fd, path);\n"
                        '\t} else if (!strcmp(method, "POST") &&\n\t           !strncmp(path, "/api/uninstall", 14)) {\n'
                        "\t\tuninstall_api(fd, path);\n"
                        '\t} else if (!strcmp(method, "POST") &&\n\t           !strncmp(path, "/api/smp?", 9)) {\n'
                        "\t\tsmp_api(fd, path, body, body_len);\n"
                        '\t} else if (!strcmp(method, "GET") &&\n\t           !strncmp(path, "/api/smp-icon", 13)) {\n'
                        "\t\tsmp_icon_api(fd, path);\n"
                        '\t} else if (!strcmp(method, "POST") &&\n\t           !strncmp(path, "/api/notify", 11)) {\n'
                        "\t\tnotify_api(fd, body, body_len);\n" + version, 1)
    text = text.replace(started, started + "\tawake_start();\n", 1)
    mk = src.parent / "Makefile"
    mtext = mk.read_text()
    if "-lSceSystemService" not in mtext:
        if mtext.count("-lSceNet") != 1:
            sys.exit("can't find the libraries in the Makefile")
        mk.write_text(mtext.replace("-lSceNet", "-lSceNet -lSceSystemService", 1))

    src.write_text(text)
    print(f"Glass theme added to {src} (build {build.group(2)}-{REV})")


if __name__ == "__main__":
    main()
