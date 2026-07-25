"""
Wolter-I telescope trace, packaged as a single call.

This wraps the raw PyXFocus routines (sources -> primary -> secondary ->
focus) into one function that takes a parameter object and hands back rays
plus the performance numbers you actually want to look at.  The GUI calls
this, but it is deliberately usable on its own from a script or notebook::

    from PyXFocus.gui.wolter import WolterParams, trace

    result = trace(WolterParams(r0=220., z0=8400., offaxis=1.0))
    print(result.hpd_arcsec)

Geometry convention (inherited from PyXFocus):
    * The Wolter focus sits at the origin, +z points back toward the sky.
    * The primary/secondary node is at z = z0, radius r0, so z0 is the
      focal length.
    * The primary spans z0 -> z0 + primary_length.
    * The secondary spans z0 - secondary_length -> z0.
"""

import numpy as np

import PyXFocus.analyses as anal
import PyXFocus.conicsolve as conic
import PyXFocus.sources as sources
import PyXFocus.surfaces as surf
import PyXFocus.transformations as tran

#: Radians per arcminute, and arcseconds per radian.
_ARCMIN = np.pi / (180. * 60.)
_ARCSEC_PER_RAD = 180. / np.pi * 3600.

#: Misalignment limits, in mm and arcminutes.
#:
#: These are not physics limits -- they guard a real defect in the Fortran
#: secondary solver (``woltsurf.f95``).  Once the secondary is displaced far
#: enough that rays no longer intersect the hyperboloid, the Newton iteration
#: stops converging and spins forever, hanging the caller with no error.
#: Measured empirically: translations hang between 80 and 100 mm, rotations
#: between 20 and 40 arcmin.  The caps below sit well inside that, and are
#: still enormous next to real Wolter-I alignment tolerances (microns and
#: arcseconds).  Past roughly a millimetre only a handful of rays survive
#: vignetting anyway, so the results stop meaning anything long before here.
MAX_TRANSLATION_MM = 20.
MAX_ROTATION_ARCMIN = 15.


def check_misalignment(params):
    """
    Raise if a misalignment would trip the non-converging secondary solver.

    Raises
    ------
    ValueError
        If any translation or rotation exceeds the documented safe limit.
    """
    for name in ('sec_dx', 'sec_dy', 'sec_dz'):
        val = getattr(params, name)
        if abs(val) > MAX_TRANSLATION_MM:
            raise ValueError(
                '%s = %g mm exceeds the safe limit of %g mm. Beyond this the '
                'Fortran secondary solver fails to converge and hangs.'
                % (name, val, MAX_TRANSLATION_MM))
    for name in ('sec_rx', 'sec_ry', 'sec_rz'):
        val = getattr(params, name)
        if abs(val) > MAX_ROTATION_ARCMIN:
            raise ValueError(
                '%s = %g arcmin exceeds the safe limit of %g arcmin. Beyond '
                'this the Fortran secondary solver fails to converge and hangs.'
                % (name, val, MAX_ROTATION_ARCMIN))


class WolterParams(object):
    """
    Every knob the Wolter-I explorer exposes.

    Parameters
    ----------
    r0 : float
        Shell radius at the node, in mm.
    z0 : float
        Focal length (node to focus), in mm.
    primary_length, secondary_length : float
        Axial mirror lengths, in mm.
    psi : float
        Wolter prescription parameter; 1.0 is a classic Wolter-I.
    offaxis : float
        Source off-axis angle, in arcminutes.
    azimuth : float
        Azimuth of the off-axis direction, in degrees.
    num_rays : int
        Rays launched before vignetting.
    sec_dx ... sec_rz : float
        Secondary mirror misalignment: translations in mm, rotations in
        arcminutes.
    seed : int or None
        Seed for the random ray pattern, so a trace is repeatable.
    """

    def __init__(self, r0=220., z0=8400., primary_length=100.,
                 secondary_length=100., psi=1., offaxis=0., azimuth=0.,
                 num_rays=20000, sec_dx=0., sec_dy=0., sec_dz=0.,
                 sec_rx=0., sec_ry=0., sec_rz=0., seed=0):
        self.r0 = r0
        self.z0 = z0
        self.primary_length = primary_length
        self.secondary_length = secondary_length
        self.psi = psi
        self.offaxis = offaxis
        self.azimuth = azimuth
        self.num_rays = num_rays
        self.sec_dx = sec_dx
        self.sec_dy = sec_dy
        self.sec_dz = sec_dz
        self.sec_rx = sec_rx
        self.sec_ry = sec_ry
        self.sec_rz = sec_rz
        self.seed = seed

    def misalignment(self):
        """Secondary misalignment as PyXFocus expects it (mm and radians)."""
        return (self.sec_dx, self.sec_dy, self.sec_dz,
                self.sec_rx * _ARCMIN, self.sec_ry * _ARCMIN,
                self.sec_rz * _ARCMIN)

    def copy(self):
        new = WolterParams()
        new.__dict__.update(self.__dict__)
        return new


class TraceResult(object):
    """Rays at focus plus the numbers derived from them."""

    def __init__(self, params):
        self.params = params
        self.rays = None
        #: Ray positions at each stage, for the layout plot.
        self.path_z = None
        self.path_r = None
        #: Performance metrics.
        self.hpd_arcsec = np.nan
        self.rms_arcsec = np.nan
        self.hpd_mm = np.nan
        self.rms_mm = np.nan
        self.focus_z = np.nan
        self.num_launched = 0
        self.num_surviving = 0
        self.geometric_area = 0.
        self.message = ''

    @property
    def throughput(self):
        """Fraction of launched rays that made it through both mirrors."""
        if self.num_launched == 0:
            return 0.
        return float(self.num_surviving) / self.num_launched

    @property
    def effective_area(self):
        """Geometric collecting area surviving vignetting, in cm^2."""
        return self.geometric_area * self.throughput

    @property
    def spot(self):
        """Focal-plane (x, y) in mm, centred on the centroid."""
        if self.rays is None or self.num_surviving == 0:
            return np.array([]), np.array([])
        x, y = self.rays[1], self.rays[2]
        return x - np.mean(x), y - np.mean(y)


def shell_radii(params):
    """Inner and outer radius of the primary entrance aperture, in mm."""
    rin = conic.primrad(params.z0, params.r0, params.z0, psi=params.psi)
    rout = conic.primrad(params.z0 + params.primary_length,
                         params.r0, params.z0, psi=params.psi)
    return rin, rout


def trace(params, record_paths=True, num_paths=40):
    """
    Trace a Wolter-I shell and measure its focus.

    Parameters
    ----------
    params : WolterParams
        System definition.
    record_paths : bool
        Capture ray positions at each surface for the layout plot.
    num_paths : int
        How many rays to record paths for.

    Returns
    -------
    TraceResult
        Rays at best focus and the derived performance metrics.  If every
        ray vignettes, ``message`` explains it and the metrics stay NaN.
    """
    check_misalignment(params)

    result = TraceResult(params)

    rin, rout = shell_radii(params)
    if not np.isfinite(rin) or not np.isfinite(rout) or rout <= rin:
        result.message = ('Invalid geometry: the primary has no aperture. '
                          'Check r0, focal length and psi.')
        return result

    # Geometric aperture of the annulus, in cm^2.
    result.geometric_area = np.pi * (rout ** 2 - rin ** 2) / 100.

    if params.seed is not None:
        np.random.seed(params.seed)

    rays = sources.annulus(rin, rout, int(params.num_rays))
    result.num_launched = int(params.num_rays)

    # Start the rays above the primary, still travelling in -z.
    start_z = params.z0 + params.primary_length + 500.
    tran.transform(rays, 0, 0, -start_z, 0, 0, 0)

    # Point the beam off-axis.  Direction cosines are set directly so the
    # ray *positions* stay put and only the incoming angle changes.
    theta = params.offaxis * _ARCMIN
    phi = np.radians(params.azimuth)
    if theta != 0.:
        n_rays = len(rays[1])
        rays[4] = np.repeat(np.sin(theta) * np.cos(phi), n_rays)
        rays[5] = np.repeat(np.sin(theta) * np.sin(phi), n_rays)
        rays[6] = np.repeat(-np.cos(theta), n_rays)

    paths = []
    if record_paths:
        paths.append(_sample(rays, num_paths))

    # --- Primary ---
    surf.wolterprimary(rays, params.r0, params.z0, psi=params.psi)
    tran.reflect(rays)
    ind = np.logical_and(rays[3] > params.z0,
                         rays[3] < params.z0 + params.primary_length)
    if not ind.any():
        result.message = 'All rays missed the primary mirror.'
        return result
    rays = tran.vignette(rays, ind=ind)
    if record_paths:
        paths.append(_sample(rays, num_paths))

    # --- Secondary, in its (possibly misaligned) frame ---
    misalign = params.misalignment()
    tran.transform(rays, *misalign)
    surf.woltersecondary(rays, params.r0, params.z0, psi=params.psi)
    tran.reflect(rays)
    tran.itransform(rays, *misalign)

    ind = np.logical_and(rays[3] > params.z0 - params.secondary_length,
                         rays[3] < params.z0)
    if not ind.any():
        result.message = 'All rays missed the secondary mirror.'
        return result
    rays = tran.vignette(rays, ind=ind)
    if record_paths:
        paths.append(_sample(rays, num_paths))

    # Drop any ray that picked up a non-finite position.
    good = np.isfinite(rays[1]) & np.isfinite(rays[2]) & np.isfinite(rays[3])
    if not good.all():
        rays = tran.vignette(rays, ind=good)
    if len(rays[1]) == 0:
        result.message = 'No rays survived the trace.'
        return result

    # --- Best focus ---
    result.focus_z = surf.focusI(rays)
    if record_paths:
        paths.append(_sample(rays, num_paths))

    result.rays = rays
    result.num_surviving = len(rays[1])
    result.hpd_mm = anal.hpd(rays)
    result.rms_mm = anal.rmsCentroid(rays)
    result.hpd_arcsec = result.hpd_mm / params.z0 * _ARCSEC_PER_RAD
    result.rms_arcsec = result.rms_mm / params.z0 * _ARCSEC_PER_RAD

    if record_paths:
        result.path_z, result.path_r = _stack_paths(paths)

    return result


def _sample(rays, num):
    """Grab (z, r) for the first ``num`` rays at the current surface."""
    n = min(num, len(rays[1]))
    z = np.array(rays[3][:n], dtype=float)
    r = np.sqrt(np.array(rays[1][:n], dtype=float) ** 2 +
                np.array(rays[2][:n], dtype=float) ** 2)
    return z, r


def _stack_paths(paths):
    """
    Assemble per-stage samples into (z, r) arrays of shape (stages, rays).

    Vignetting shrinks the ray list between stages, so every stage is
    trimmed to the shortest one to keep the columns aligned.  This traces
    the surviving rays only, which is what the layout plot should show.
    """
    if not paths:
        return None, None
    n = min(len(z) for z, _ in paths)
    if n == 0:
        return None, None
    z = np.vstack([zz[:n] for zz, _ in paths])
    r = np.vstack([rr[:n] for _, rr in paths])
    return z, r


def mirror_profile(params, num=200):
    """
    Radius vs z along both mirrors, for drawing the telescope in profile.

    Returns
    -------
    (zp, rp), (zs, rs)
        Primary and secondary profiles.
    """
    zp = np.linspace(params.z0, params.z0 + params.primary_length, num)
    rp = conic.primrad(zp, params.r0, params.z0, psi=params.psi)
    zs = np.linspace(params.z0 - params.secondary_length, params.z0, num)
    rs = conic.secrad(zs, params.r0, params.z0, psi=params.psi)
    return (zp, rp), (zs, rs)


def encircled_energy(result, num=200):
    """
    Encircled-energy curve: radius from centroid (arcsec) vs enclosed fraction.
    """
    x, y = result.spot
    if len(x) == 0:
        return np.array([]), np.array([])
    rad = np.sort(np.sqrt(x ** 2 + y ** 2))
    frac = np.arange(1, len(rad) + 1) / float(len(rad))
    if len(rad) > num:
        idx = np.linspace(0, len(rad) - 1, num).astype(int)
        rad, frac = rad[idx], frac[idx]
    return rad / result.params.z0 * _ARCSEC_PER_RAD, frac
