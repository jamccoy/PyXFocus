"""The app icon, drawn rather than stored.

Rendered from matplotlib because this machine has no SVG rasteriser
(``rsvg-convert`` / ``inkscape``), and generating the artwork keeps it
reproducible and editable in the same language as the rest of the project.
``tools/make_icon.py`` turns this into a macOS ``.icns``.

The motif is a Wolter-I in profile: two grazing-incidence mirror shells
funnelling a handful of rays down to a focus -- the thing this software
actually computes, not a generic symbol. Deliberately few, thick elements,
because that is what stays legible at 16 px, which is where most icons fail.
"""

BACKGROUND = '#0d1b2a'    # deep space navy
MIRROR = '#e8ecf5'        # bright, so the shells read as reflective
FOCUS = '#ffb454'         # warm accent marking the one point everything hits
RAY_COLORS = ('#5fd4ff', '#8fe3ff')   # two shades per side, inner vs outer ray


def render(path, size=1024):
    """
    Draw the icon to a square PNG.

    Parameters
    ----------
    path : str or Path
        Where to write the PNG.
    size : int
        Pixels per side. 1024 is the largest macOS asks for; every smaller
        variant is downsampled from it.
    """
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyBboxPatch

    figure = Figure(figsize=(size / 100., size / 100.), dpi=100)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.axis('off')

    # Rounded-square plate, inset like a macOS app icon.
    axes.add_patch(FancyBboxPatch(
        (0.06, 0.06), 0.88, 0.88,
        boxstyle='round,pad=0,rounding_size=0.20',
        facecolor=BACKGROUND, edgecolor='none'))

    axis_x = 0.5
    focus = (axis_x, 0.11)
    mirror_lw = size * 0.045
    ray_lw = size * 0.020

    # Two elements per side, kept visually apart rather than overlapping so
    # they still read as separate shapes once downsampled to 16 px: a wide,
    # straight mirror wall (the shell, stopping short of the focus) and a
    # narrower ray running inside it straight to the focus. The pair reads
    # as "a funnel focusing a beam" without needing a literal double bounce.
    for sign in (-1, 1):
        mirror_top = (axis_x + sign * 0.35, 0.87)
        mirror_bottom = (axis_x + sign * 0.11, 0.22)
        axes.plot([mirror_top[0], mirror_bottom[0]],
                  [mirror_top[1], mirror_bottom[1]],
                  color=MIRROR, lw=mirror_lw, solid_capstyle='round')

        ray_top = (axis_x + sign * 0.20, 0.87)
        axes.plot([ray_top[0], focus[0]], [ray_top[1], focus[1]],
                  color=RAY_COLORS[0], lw=ray_lw, solid_capstyle='round')

    axes.plot([focus[0]], [focus[1]], marker='o',
              markersize=size * 0.05, color=FOCUS, markeredgewidth=0)

    figure.savefig(path, dpi=100, transparent=False)
    return path
