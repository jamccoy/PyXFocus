#!/usr/bin/env python
"""
Smoke tests: does the package import, and does it still do physics?

Run from the directory *containing* the PyXFocus folder::

    python -m PyXFocus.test_smoke

Deliberately dependency-light (no pytest) so it can be run straight after
building the Fortran extensions to confirm the install is sound.
"""

from __future__ import print_function

import sys
import traceback

import numpy as np

RESULTS = []


def check(name, fn):
    """Run one check, recording pass/fail rather than raising."""
    try:
        fn()
    except Exception:
        RESULTS.append((name, False, traceback.format_exc().strip()))
        print('FAIL  %s' % name)
    else:
        RESULTS.append((name, True, ''))
        print('ok    %s' % name)


def test_imports():
    """Every core module imports without the optional `utilities` package."""
    import PyXFocus.analyses          # noqa: F401
    import PyXFocus.conicsolve        # noqa: F401
    import PyXFocus.lenses            # noqa: F401
    import PyXFocus.sources           # noqa: F401
    import PyXFocus.surfaces          # noqa: F401
    import PyXFocus.transformations   # noqa: F401


def test_wolter_surfaces_bound():
    """woltsurf is actually imported, so the Wolter routines can run."""
    import PyXFocus.surfaces as surf
    assert hasattr(surf.wolt, 'wolterprimary'), 'woltsurf not bound'


def test_optional_dependency_message():
    """A missing optional dep fails late, with a useful message."""
    from PyXFocus._optional import optional_module
    mod = optional_module('definitely_not_installed_xyz', 'testing', 'pip install x')
    try:
        mod.anything
    except ImportError as err:
        assert 'pip install x' in str(err), 'install hint missing'
    else:
        raise AssertionError('expected ImportError')


def test_onaxis_focus_is_sharp():
    """A perfect on-axis Wolter-I focuses to essentially a point."""
    from PyXFocus.gui.wolter import WolterParams, trace
    result = trace(WolterParams(offaxis=0., num_rays=10000))
    assert result.num_surviving == 10000, 'unexpected vignetting on axis'
    assert result.hpd_arcsec < 0.01, 'on-axis HPD too large: %g' % result.hpd_arcsec
    assert abs(result.focus_z) < 1e-3, 'focus not at origin: %g' % result.focus_z


def test_offaxis_blur_grows():
    """Off-axis coma grows with field angle, and vignetting bites."""
    from PyXFocus.gui.wolter import WolterParams, trace
    hpds, counts = [], []
    for off in (0., 2., 5., 10.):
        r = trace(WolterParams(offaxis=off, num_rays=10000))
        hpds.append(r.hpd_arcsec)
        counts.append(r.num_surviving)
    assert all(np.diff(hpds) > 0), 'HPD should grow off-axis: %s' % hpds
    assert all(np.diff(counts) < 0), 'throughput should fall off-axis: %s' % counts


def test_misalignment_degrades():
    """Displacing the secondary makes the image worse."""
    from PyXFocus.gui.wolter import WolterParams, trace
    clean = trace(WolterParams(offaxis=1., num_rays=10000))
    bent = trace(WolterParams(offaxis=1., sec_dy=0.2, num_rays=10000))
    assert bent.hpd_arcsec > clean.hpd_arcsec, 'misalignment should degrade HPD'


def test_misalignment_guard():
    """The guard blocks inputs that hang the Fortran secondary solver."""
    from PyXFocus.gui.wolter import WolterParams, trace, MAX_TRANSLATION_MM
    try:
        trace(WolterParams(sec_dy=MAX_TRANSLATION_MM * 10))
    except ValueError:
        pass
    else:
        raise AssertionError('expected ValueError for extreme misalignment')


def test_encircled_energy_consistent():
    """The half-power radius from the EE curve matches the reported HPD."""
    from PyXFocus.gui.wolter import WolterParams, trace, encircled_energy
    result = trace(WolterParams(offaxis=5., num_rays=20000))
    rad, frac = encircled_energy(result)
    half_power_radius = rad[np.abs(frac - 0.5).argmin()]
    assert np.isclose(half_power_radius * 2, result.hpd_arcsec, rtol=.05), (
        'EE half-power radius %g disagrees with HPD %g'
        % (half_power_radius, result.hpd_arcsec))


def test_sweep_tracks_offaxis():
    """A sweep reproduces the off-axis trend, point by point."""
    from PyXFocus.gui.wolter import WolterParams, sweep
    result = sweep(WolterParams(num_rays=4000), 'offaxis', 0., 8., 8)
    assert result.valid.all(), 'every off-axis point should trace'
    hpd = result.hpd_arcsec
    assert np.all(np.diff(hpd) > 0), 'HPD should grow across the sweep: %s' % hpd
    assert np.all(np.diff(result.throughput) < 0), 'throughput should fall'


def test_sweep_survives_ungraceable_points():
    """Points past the misalignment guard become NaN, not an exception."""
    from PyXFocus.gui.wolter import WolterParams, sweep, MAX_ROTATION_ARCMIN
    result = sweep(WolterParams(num_rays=2000), 'sec_ry', 0.,
                   MAX_ROTATION_ARCMIN * 3, 7)
    assert result.valid.any(), 'low-tilt points should still trace'
    assert not result.valid.all(), 'high-tilt points should be rejected'
    assert result.notes, 'rejected points should record a reason'


def test_sweep_can_be_cancelled():
    """should_stop truncates the sweep instead of running to completion."""
    from PyXFocus.gui.wolter import WolterParams, sweep
    done = []
    result = sweep(WolterParams(num_rays=2000), 'offaxis', 0., 10., 20,
                   progress=lambda d, t: done.append(d),
                   should_stop=lambda: len(done) >= 4)
    assert len(result.values) == 4, 'expected truncation to 4 points'
    assert result.completed == 4


def test_sweep_csv_roundtrip(tmp_path=None):
    """The CSV export has one header plus one row per point."""
    import os
    import tempfile
    from PyXFocus.gui.wolter import WolterParams, sweep
    result = sweep(WolterParams(num_rays=2000), 'sec_dy', 0., .3, 5)
    path = os.path.join(tempfile.mkdtemp(), 'sweep.csv')
    result.to_csv(path)
    lines = open(path).read().strip().split('\n')
    assert len(lines) == 6, 'expected header + 5 rows, got %d' % len(lines)
    assert lines[0].startswith('sec_dy[mm]'), 'unexpected header: %s' % lines[0]


def test_nonconvergence_is_counted_not_silently_vignetted():
    """
    Solver failures are reported, not disguised as geometric misses.

    r0=5mm is ill-conditioned enough that most rays hit the iteration cap.
    Before the cap existed this hung; before the counting existed the dead
    rays were absorbed by the mirror-extent test and quietly reported as
    rays that missed the mirror, which understated throughput with no hint
    that anything had gone wrong.
    """
    from PyXFocus.gui.wolter import WolterParams, trace
    result = trace(WolterParams(r0=5., num_rays=2000))
    assert result.num_nonconverged > 0, 'expected solver failures at r0=5'
    assert result.metrics_are_bounds, 'metrics should be flagged as bounds'
    assert result.warnings, 'a non-converged trace must warn'
    assert 'lower bound' in ' '.join(result.warnings)
    total = (result.num_surviving + result.num_nonconverged
             + result.num_nonfinite)
    assert total <= result.num_launched, 'accounting exceeds rays launched'


def test_clean_trace_reports_no_nonconvergence():
    """A well-conditioned system must not raise false alarms."""
    from PyXFocus.gui.wolter import WolterParams, trace
    result = trace(WolterParams(num_rays=5000))
    assert result.num_nonconverged == 0
    assert result.num_nonfinite == 0
    assert not result.metrics_are_bounds
    assert result.warnings == []


def test_sweep_records_nonconvergence():
    """A sweep carries the per-point non-convergence count into its CSV."""
    import os
    import tempfile
    from PyXFocus.gui.wolter import WolterParams, sweep
    result = sweep(WolterParams(num_rays=1000), 'r0', 3., 60., 8)
    assert (result.nonconverged > 0).any(), 'expected degraded points'
    path = os.path.join(tempfile.mkdtemp(), 'sweep.csv')
    result.to_csv(path)
    lines = open(path).read().strip().split('\n')
    assert lines[0].endswith('rays_nonconverged'), lines[0]
    assert len(lines) == 9


def test_collecting_area_is_geometric_only():
    """Collecting area is aperture x throughput, with no reflectivity in it."""
    from PyXFocus.gui.wolter import WolterParams, trace
    result = trace(WolterParams(offaxis=2., num_rays=5000))
    expected = result.geometric_area * result.throughput
    assert np.isclose(result.collecting_area, expected), (
        'collecting_area should be geometric_area * throughput')


def test_param_specs_cover_every_field():
    """
    The spec table and WolterParams cannot drift apart.

    This is the test that would have caught `seed`: it is a WolterParams
    field with no entry in the panel, so a saved configuration silently
    reverted it to 0 on reload.
    """
    from PyXFocus.gui.wolter import WolterParams, PARAM_FIELDS, PARAM_SPECS
    fields = set(vars(WolterParams()))
    assert set(PARAM_FIELDS) == fields, (
        'spec/field mismatch: %s' % (set(PARAM_FIELDS) ^ fields))
    assert len(PARAM_SPECS) == len(fields), 'duplicate spec name'


def test_param_spec_defaults_match_constructor():
    """A spec default that disagrees with WolterParams is a silent trap."""
    from PyXFocus.gui.wolter import WolterParams, PARAM_SPECS
    defaults = WolterParams()
    for spec in PARAM_SPECS:
        assert float(spec.default) == float(getattr(defaults, spec.name)), (
            '%s default %r != constructor %r'
            % (spec.name, spec.default, getattr(defaults, spec.name)))


def test_params_dict_roundtrip():
    """to_dict -> json -> from_dict preserves all 15 fields exactly."""
    import json
    from PyXFocus.gui.wolter import WolterParams, PARAM_FIELDS
    p = WolterParams(r0=300., z0=12000., offaxis=2.5, azimuth=90.,
                     sec_dy=0.3, sec_rx=1.25, num_rays=12345, seed=42)
    back = WolterParams.from_dict(json.loads(json.dumps(p.to_dict())))
    for name in PARAM_FIELDS:
        assert getattr(p, name) == getattr(back, name), (
            '%s did not survive: %r -> %r'
            % (name, getattr(p, name), getattr(back, name)))
    assert isinstance(back.num_rays, int) and isinstance(back.seed, int)


def test_params_from_dict_collects_problems():
    """One bad field costs that field, not the whole configuration."""
    from PyXFocus.gui.wolter import WolterParams
    problems = []
    p = WolterParams.from_dict(
        {'r0': 300., 'psi': float('nan'), 'z0': 'banana', 'coating': 'Ir'},
        problems)
    assert p.r0 == 300., 'the good field should still be applied'
    assert p.psi == WolterParams().psi, 'non-finite must fall back to default'
    assert p.z0 == WolterParams().z0, 'non-numeric must fall back to default'
    assert not hasattr(p, 'coating'), 'unknown keys must never be setattr-ed'
    joined = ' '.join(problems)
    for expect in ('coating', 'psi', 'z0'):
        assert expect in joined, 'no problem recorded for %s' % expect


def test_params_from_dict_rejects_non_finite():
    """
    NaN must not reach a spin box.

    json.loads accepts a bare NaN token, and QDoubleSpinBox.setValue(nan)
    silently yields the field MAXIMUM -- so an unguarded NaN would read
    back as a deliberate extreme misalignment.
    """
    import json
    from PyXFocus.gui.wolter import WolterParams
    data = json.loads('{"sec_ry": NaN, "sec_rx": Infinity}')
    p = WolterParams.from_dict(data)
    assert p.sec_ry == 0. and p.sec_rx == 0.


def test_reproducible():
    """The same seed gives the same answer twice."""
    from PyXFocus.gui.wolter import WolterParams, trace
    a = trace(WolterParams(offaxis=3., seed=42, num_rays=5000))
    b = trace(WolterParams(offaxis=3., seed=42, num_rays=5000))
    assert a.hpd_arcsec == b.hpd_arcsec, 'trace is not reproducible'


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            check(name, fn)

    failures = [(n, tb) for n, ok, tb in RESULTS if not ok]
    print('\n%d passed, %d failed' % (len(RESULTS) - len(failures), len(failures)))
    for name, tb in failures:
        print('\n--- %s ---\n%s' % (name, tb))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
