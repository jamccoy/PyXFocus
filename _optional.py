"""
Lazy loading for optional third-party dependencies.

Some PyXFocus functions (Zernike/Legendre wavefront fitting, wavefront
padding) rely on the external ``utilities`` imaging package.  Importing it
at module scope meant a missing ``utilities`` broke *every* function in
``analyses`` and ``surfaces``, including the core raytrace routines that
never touch it.

``optional_module`` defers the import until an attribute is actually used,
so the package imports cleanly without ``utilities`` installed and only the
functions that genuinely need it raise -- with a message saying what to
install.
"""


class _OptionalModule:
    """Proxy that imports ``name`` on first attribute access."""

    def __init__(self, name, purpose, install):
        self._name = name
        self._purpose = purpose
        self._install = install
        self._module = None

    def __getattr__(self, attr):
        # Guard against recursion on our own private attributes.
        if attr.startswith('_'):
            raise AttributeError(attr)

        if self._module is None:
            try:
                self._module = __import__(self._name, fromlist=['__name__'])
            except ImportError as err:
                raise ImportError(
                    "%s is required for %s but is not installed.\n"
                    "Install it with: %s\n"
                    "(The rest of PyXFocus works without it.)"
                    % (self._name, self._purpose, self._install)
                ) from err

        return getattr(self._module, attr)


def optional_module(name, purpose, install):
    """
    Return a proxy for ``name`` that imports on first use.

    Parameters
    ----------
    name : str
        Fully qualified module name, e.g. ``'utilities.imaging.man'``.
    purpose : str
        Short description of what needs it, used in the error message.
    install : str
        Command that installs the dependency.

    Returns
    -------
    _OptionalModule
        Proxy forwarding attribute access to the real module.
    """
    return _OptionalModule(name, purpose, install)


#: Install hint for the ``utilities`` imaging package.
UTILITIES_INSTALL = 'pip install git+https://github.com/rallured/utilities.git'
