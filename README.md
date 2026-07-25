# PyXFocus
General purpose raytracing software with an emphasis on X-ray telescope design

Use of this software for academic and professional optical design work is permitted and encouraged.

Any publications resulting from use of this software shall include an acknowledgement of PyXFocus.
The suggested sentence for the acknowledgements section is:

This work makes use of PyXFocus, an open source Python-based raytracing package.

---

## Installing

PyXFocus is imported as a package named `PyXFocus`, so the repository folder
must be named `PyXFocus` and its **parent** directory must be on your Python
path.

```bash
git clone https://github.com/kbuffo/PyXFocus.git
cd PyXFocus
```

### 1. Requirements

* Python 3, numpy, scipy, matplotlib
* `gfortran` (macOS: `brew install gcc`; Debian/Ubuntu: `apt install gfortran`)
* PyQt5, only if you want the GUI

### 2. Build the Fortran extensions

The repository ships pre-built **Windows** `.dll` files only. On macOS and
Linux you must compile the Fortran modules once:

```bash
python build_extensions.py
```

This builds six extension modules (`surfacesf`, `woltsurf`, `zernsurf`,
`transformationsf`, `reconstruct`, `specialfunctions`). It calls f2py through
`python -m numpy.f2py`, which guarantees they are built for the same
interpreter that will import them — if you build with one Python and import
with another, the modules will appear to be missing.

### 3. Check it worked

From the directory *containing* the `PyXFocus` folder:

```bash
python -m PyXFocus.test_smoke
```

All checks should pass. These verify the package imports and that the physics
is still right (an on-axis Wolter-I focuses to a point, off-axis coma grows
with field angle, and so on).

### Optional dependency

A few wavefront-fitting routines (`OPDtoZernike`, `OPDtoLegendre`,
`wavefront`, and the `zernsurf` surfaces) need the external `utilities`
imaging package:

```bash
pip install git+https://github.com/rallured/utilities.git
```

It is imported lazily, so **everything else works without it**. If you call a
function that needs it, you get an ImportError naming the package and the
install command.

## The Wolter-I Explorer (GUI)

A graphical front end for the package's core use case — designing and
misaligning a Wolter-I grazing-incidence telescope:

```bash
python -m PyXFocus.gui.app
```

Set the shell radius, focal length, mirror lengths, source off-axis angle and
secondary misalignment in the left-hand panel. The trace re-runs
automatically and reports:

* **Spot Diagram** — the focal-plane spot, in arcseconds, with the
  half-power diameter circled.
* **Telescope Layout** — the system in profile with rays converging on the
  focus, plus a zoom inset on the mirrors themselves (a Wolter-I is ~8 m long
  but only ~20 cm in radius, so the mirrors need their own scale).
* **Encircled Energy** — enclosed fraction vs. radius from the centroid.

Alongside: HPD and RMS radius in arcseconds, surviving ray count, throughput,
effective collecting area, and the best-focus position.

**Show script** prints the plain PyXFocus script equivalent to the current
settings, so the GUI can be used to find a configuration and then hand it
back to you as code.

### Misalignment limits

The secondary misalignment fields are capped at ±20 mm and ±15 arcmin. This
is not a physics limit — it guards a defect in the Fortran secondary solver
(`woltsurf.f95`): once the secondary is displaced far enough that rays no
longer intersect the hyperboloid, the Newton iteration never converges and
hangs with no error. Translations hang beyond roughly 80–100 mm and rotations
beyond 20–40 arcmin. Real Wolter-I alignment tolerances are microns and
arcseconds, and past about a millimetre so few rays survive vignetting that
the numbers stop meaning much, so the caps are generous in practice.
`PyXFocus.gui.wolter.trace` enforces the same limits with a clear `ValueError`
so scripts cannot hit the hang either.

## Scripting

The GUI is a thin shell over `PyXFocus.gui.wolter`, which has no Qt
dependency and is usable on its own:

```python
from PyXFocus.gui.wolter import WolterParams, trace

result = trace(WolterParams(r0=220., z0=8400., offaxis=1.0))
print(result.hpd_arcsec, result.num_surviving, result.effective_area)
```

Or drive the raytracer directly. Rays are a list of ten arrays,
`[opd, x, y, z, l, m, n, ux, uy, uz]` — position, direction cosines, and the
normal of the last surface hit:

```python
import numpy as np
import PyXFocus.sources as sources
import PyXFocus.surfaces as surf
import PyXFocus.transformations as tran
import PyXFocus.analyses as anal
import PyXFocus.conicsolve as conic

r0, z0, length = 220., 8400., 100.

rin = conic.primrad(z0, r0, z0)
rout = conic.primrad(z0 + length, r0, z0)
rays = sources.annulus(rin, rout, 20000)
tran.transform(rays, 0, 0, -(z0 + length + 500.), 0, 0, 0)

surf.wolterprimary(rays, r0, z0)
tran.reflect(rays)
rays = tran.vignette(rays, ind=np.logical_and(rays[3] > z0,
                                              rays[3] < z0 + length))

surf.woltersecondary(rays, r0, z0)
tran.reflect(rays)
rays = tran.vignette(rays, ind=np.logical_and(rays[3] > z0 - length,
                                              rays[3] < z0))

surf.focusI(rays)
print('HPD [arcsec]:', anal.hpd(rays) / z0 * 180 / np.pi * 3600)
```

### Conventions

* Lengths are in **mm**, angles passed to `transform` are in **radians**.
* The Wolter focus is at the origin; `+z` points back toward the sky.
* The primary/secondary node is at `z = z0` with radius `r0`, so `z0` is the
  focal length.
* `transform` moves the *coordinate system*, not the rays; `itransform`
  undoes it.

## Repository layout

| Module | Purpose |
| --- | --- |
| `sources.py` | Ray sources (point, annulus, converging beam, …) |
| `surfaces.py` | Surfaces to trace to (Wolter, conic, sphere, cylinder, …) |
| `transformations.py` | Coordinate transforms, reflection, refraction, gratings, vignetting |
| `analyses.py` | Centroid, RMS, HPD, wavefront and OPD fitting |
| `conicsolve.py` | Wolter-I prescription maths (radii, focus, sag) |
| `lenses.py` | Singlet and doublet lenses |
| `gui/wolter.py` | One-call Wolter-I trace with performance metrics |
| `gui/app.py` | PyQt5 Wolter-I Explorer |
| `build_extensions.py` | Compiles the Fortran extensions |
| `test_smoke.py` | Import and physics checks |

### A note on `examples/`

Most scripts under `examples/` predate the current package layout. They
import a module named `traces` (an older name for this package) or the
removed monolithic `PyTrace` API, and will not run as written. Treat them as
reference for how traces were assembled rather than as runnable code;
`examples/wolterSchwarzschildTest.py` uses the current `PyXFocus.*` imports.
