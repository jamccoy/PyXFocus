#!/usr/bin/env python
"""Build the macOS .icns from the drawn artwork.

    /opt/anaconda3/bin/python tools/make_icon.py

Renders a 1024 px master via :mod:`PyXFocus.gui.icon`, downsamples it with
``sips`` into the iconset macOS expects, then packs it with ``iconutil``.
Both ship with macOS, so there is nothing to install.

The resulting ``.icns`` is committed -- it is small, stable, and it *is* the
design. Re-run this only when the artwork changes.
"""

from __future__ import print_function

import os
import subprocess
import sys
import tempfile

#: This file lives in <PyXFocus>/tools/, so REPO is the PyXFocus folder
#: itself, and REPO's *parent* has to be on sys.path -- the package is
#: imported as PyXFocus.gui.icon, and the folder is named PyXFocus.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(REPO, 'resources', 'PyXFocus.icns')
PREVIEW = os.path.join(REPO, 'resources', 'PyXFocus.png')

#: macOS expects exactly these names; iconutil is fussy about them.
VARIANTS = [
    (16, 'icon_16x16.png'),
    (32, 'icon_16x16@2x.png'),
    (32, 'icon_32x32.png'),
    (64, 'icon_32x32@2x.png'),
    (128, 'icon_128x128.png'),
    (256, 'icon_128x128@2x.png'),
    (256, 'icon_256x256.png'),
    (512, 'icon_256x256@2x.png'),
    (512, 'icon_512x512.png'),
    (1024, 'icon_512x512@2x.png'),
]


def main():
    if sys.platform != 'darwin':
        print('iconutil is macOS-only; skipping the .icns build', file=sys.stderr)
        return 0

    for tool in ('sips', 'iconutil'):
        if subprocess.call(['which', tool], stdout=subprocess.PIPE) != 0:
            print('%s not found (expected to ship with macOS)' % tool,
                  file=sys.stderr)
            return 1

    sys.path.insert(0, os.path.dirname(REPO))
    from PyXFocus.gui.icon import render

    scratch = tempfile.mkdtemp()
    master = os.path.join(scratch, 'master.png')
    render(master, size=1024)

    iconset = os.path.join(scratch, 'PyXFocus.iconset')
    os.mkdir(iconset)
    for pixels, name in VARIANTS:
        subprocess.check_call(
            ['sips', '-z', str(pixels), str(pixels), master,
             '--out', os.path.join(iconset, name)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out_dir = os.path.dirname(OUTPUT)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    subprocess.check_call(['iconutil', '-c', 'icns', iconset, '-o', OUTPUT],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # A PNG preview alongside, for the README and anything non-macOS.
    subprocess.check_call(['sips', '-z', '512', '512', master,
                           '--out', PREVIEW],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print('wrote %s (%d bytes)' % (OUTPUT, os.path.getsize(OUTPUT)))
    print('wrote %s' % PREVIEW)
    return 0


if __name__ == '__main__':
    sys.exit(main())
