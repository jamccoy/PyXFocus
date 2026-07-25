#!/usr/bin/env python
"""
Compile the Fortran extensions PyXFocus needs.

The repository ships pre-built Windows ``.dll`` files only, so on macOS and
Linux the Fortran modules have to be built once before ``PyXFocus.surfaces``
or ``PyXFocus.analyses`` will import.  Run this from the repository root::

    python build_extensions.py

You need a Fortran compiler (``gfortran``) and numpy.  On macOS install
gfortran with ``brew install gcc``; on Debian/Ubuntu use
``apt install gfortran``.

This replaces the old ``compiletrace.sh``, which hard-coded ``f2py`` as a
standalone command.  Invoking f2py through ``python -m numpy.f2py`` instead
guarantees the extensions are built for the *same* interpreter that will
import them -- the usual cause of "module not found" after a build that
looked like it succeeded.
"""

from __future__ import print_function

import os
import subprocess
import sys

#: (module name, source file) for every Fortran extension.
#: The module name must match what the Python code imports.
EXTENSIONS = [
    ('zernsurf', 'zernsurf.f95'),
    ('transformationsf', 'transformationsf.f95'),
    ('surfacesf', 'surfacesf.f95'),
    ('woltsurf', 'woltsurf.f95'),
    ('reconstruct', 'reconstruct.f95'),
    ('specialfunctions', 'specialFunctions.f95'),
]


def build(name, source, use_openmp=True):
    """Compile one extension, returning True on success."""
    cmd = [sys.executable, '-m', 'numpy.f2py', '-c', '-m', name, source]
    if use_openmp:
        cmd += ['--f90flags=-fopenmp', '-lgomp']

    print('building %s from %s' % (name, source))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    output = proc.communicate()[0].decode('utf-8', 'replace')

    if proc.returncode != 0:
        if use_openmp:
            # Apple's stock clang toolchain often has no OpenMP runtime.
            # The extensions are correct without it, just single-threaded.
            print('  OpenMP build failed, retrying without it')
            return build(name, source, use_openmp=False)
        print('  FAILED')
        print(output[-2000:])
        return False

    print('  ok')
    return True


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    missing = [s for _, s in EXTENSIONS if not os.path.exists(s)]
    if missing:
        print('Missing Fortran sources: %s' % ', '.join(missing))
        return 1

    failed = [n for n, s in EXTENSIONS if not build(n, s)]

    if failed:
        print('\n%d extension(s) failed: %s' % (len(failed), ', '.join(failed)))
        print('Check that gfortran is installed and on your PATH.')
        return 1

    print('\nAll %d extensions built.' % len(EXTENSIONS))
    print('Verify with:  python -c "import PyXFocus.surfaces"')
    print('(run it from the directory *containing* the PyXFocus folder)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
