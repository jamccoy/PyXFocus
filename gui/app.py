"""
Wolter-I telescope explorer -- a PyQt5 front end for PyXFocus.

Set up a Wolter-I shell with labelled input fields, press Trace, and see the
spot diagram, the telescope in profile, and the encircled-energy curve, with
HPD and RMS reported in arcseconds.

Launch it with::

    python -m PyXFocus.gui.app

The trace itself lives in :mod:`PyXFocus.gui.wolter` and has no Qt
dependency, so anything you can set up here you can also script.
"""

import sys
import traceback

import matplotlib
matplotlib.use('Qt5Agg')

import matplotlib.patches
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt5 import QtCore, QtWidgets

from PyXFocus.gui import wolter
from PyXFocus.gui.wolter import WolterParams


class TraceWorker(QtCore.QThread):
    """Runs a trace off the UI thread so the window stays responsive."""

    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, params, parent=None):
        super(TraceWorker, self).__init__(parent)
        self.params = params

    def run(self):
        try:
            self.finished.emit(wolter.trace(self.params))
        except Exception:
            self.failed.emit(traceback.format_exc())


class ParameterPanel(QtWidgets.QWidget):
    """The input fields, grouped by what they describe."""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super(ParameterPanel, self).__init__(parent)
        self._spins = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._group('Geometry', [
            ('r0', 'Shell radius r₀', 'mm', 220., 1., 5000., 3, 5.),
            ('z0', 'Focal length z₀', 'mm', 8400., 100., 100000., 1, 100.),
            ('primary_length', 'Primary length', 'mm', 100., 1., 2000., 1, 10.),
            ('secondary_length', 'Secondary length', 'mm', 100., 1., 2000., 1, 10.),
            ('psi', 'Prescription ψ', '', 1., 0.1, 10., 3, 0.1),
        ]))

        layout.addWidget(self._group('Source', [
            ('offaxis', 'Off-axis angle', 'arcmin', 0., 0., 120., 3, 0.5),
            ('azimuth', 'Azimuth', 'deg', 0., 0., 360., 1, 15.),
            ('num_rays', 'Number of rays', '', 20000., 100., 500000., 0, 5000.),
        ]))

        # Ranges here are capped by the backend's safe limits -- see
        # wolter.check_misalignment for why they exist.
        tmax = wolter.MAX_TRANSLATION_MM
        rmax = wolter.MAX_ROTATION_ARCMIN
        layout.addWidget(self._group('Secondary misalignment', [
            ('sec_dx', 'Shift x', 'mm', 0., -tmax, tmax, 4, 0.01),
            ('sec_dy', 'Shift y', 'mm', 0., -tmax, tmax, 4, 0.01),
            ('sec_dz', 'Shift z', 'mm', 0., -tmax, tmax, 4, 0.01),
            ('sec_rx', 'Tilt about x', 'arcmin', 0., -rmax, rmax, 4, 0.05),
            ('sec_ry', 'Tilt about y', 'arcmin', 0., -rmax, rmax, 4, 0.05),
            ('sec_rz', 'Tilt about z', 'arcmin', 0., -rmax, rmax, 4, 0.05),
        ]))

        layout.addStretch(1)

    def _group(self, title, rows):
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        for name, label, unit, default, lo, hi, decimals, step in rows:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(decimals)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setValue(default)
            spin.setKeyboardTracking(False)
            if unit:
                spin.setSuffix(' ' + unit)
            spin.valueChanged.connect(self.changed)
            self._spins[name] = spin
            form.addRow(label + ':', spin)
        return box

    def params(self):
        """Current field values as a :class:`WolterParams`."""
        p = WolterParams()
        for name, spin in self._spins.items():
            value = spin.value()
            setattr(p, name, int(value) if name == 'num_rays' else value)
        return p

    def reset(self):
        defaults = WolterParams()
        for name, spin in self._spins.items():
            spin.blockSignals(True)
            spin.setValue(float(getattr(defaults, name)))
            spin.blockSignals(False)
        self.changed.emit()


class MetricsBar(QtWidgets.QWidget):
    """Read-out strip for the numbers that come out of a trace."""

    FIELDS = [
        ('hpd', 'HPD'),
        ('rms', 'RMS radius'),
        ('rays', 'Rays surviving'),
        ('throughput', 'Throughput'),
        ('area', 'Effective area'),
        ('focus', 'Focus z'),
    ]

    def __init__(self, parent=None):
        super(MetricsBar, self).__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._values = {}
        for key, label in self.FIELDS:
            box = QtWidgets.QVBoxLayout()
            caption = QtWidgets.QLabel(label)
            caption.setStyleSheet('color: gray; font-size: 10px;')
            value = QtWidgets.QLabel('—')
            value.setStyleSheet('font-size: 15px; font-weight: bold;')
            box.addWidget(caption)
            box.addWidget(value)
            layout.addLayout(box)
            self._values[key] = value
        layout.addStretch(1)

    def update_metrics(self, result):
        v = self._values
        v['hpd'].setText('%.4f"' % result.hpd_arcsec)
        v['rms'].setText('%.4f"' % result.rms_arcsec)
        v['rays'].setText('%d / %d' % (result.num_surviving,
                                       result.num_launched))
        v['throughput'].setText('%.1f%%' % (100. * result.throughput))
        v['area'].setText('%.2f cm²' % result.effective_area)
        v['focus'].setText('%.4f mm' % result.focus_z)

    def clear(self):
        for value in self._values.values():
            value.setText('—')


class PlotTabs(QtWidgets.QTabWidget):
    """Spot diagram, telescope profile, and encircled energy."""

    def __init__(self, parent=None):
        super(PlotTabs, self).__init__(parent)
        self.spot_ax = self._add_tab('Spot Diagram')
        self.layout_ax = self._add_tab('Telescope Layout')
        self.ee_ax = self._add_tab('Encircled Energy')
        #: Zoom inset on the layout tab, rebuilt on every redraw.
        self._layout_inset = None

    def _add_tab(self, title):
        page = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(page)
        figure = Figure(figsize=(5, 4), tight_layout=True)
        canvas = FigureCanvasQTAgg(figure)
        box.addWidget(NavigationToolbar2QT(canvas, page))
        box.addWidget(canvas)
        self.addTab(page, title)
        ax = figure.add_subplot(111)
        ax.canvas = canvas
        return ax

    def draw_all(self, result):
        self._draw_spot(result)
        self._draw_layout(result)
        self._draw_ee(result)

    def _draw_spot(self, result):
        ax = self.spot_ax
        ax.clear()
        x, y = result.spot
        scale = wolter._ARCSEC_PER_RAD / result.params.z0
        ax.scatter(x * scale, y * scale, s=1, alpha=.3, color='#1f77b4',
                   edgecolors='none')

        # Mark the half-power diameter for scale.
        if np.isfinite(result.hpd_arcsec) and result.hpd_arcsec > 0:
            circle = matplotlib.patches.Circle(
                (0, 0), result.hpd_arcsec / 2., fill=False, color='crimson',
                lw=1.5, ls='--', label='HPD = %.4f"' % result.hpd_arcsec)
            ax.add_patch(circle)
            ax.legend(loc='upper right', fontsize=8)

        ax.set_xlabel('x [arcsec]')
        ax.set_ylabel('y [arcsec]')
        ax.set_title('Focal plane spot')
        ax.set_aspect('equal')
        ax.grid(alpha=.3)
        ax.canvas.draw_idle()

    def _draw_layout(self, result):
        """
        Telescope in profile, with a zoom inset on the mirrors.

        A Wolter-I is roughly 8 m long but only ~20 cm in radius, so at a
        scale that shows rays converging on the focus the two mirrors
        collapse into a single invisible speck.  The inset zooms on the
        grazing-incidence region so the primary and secondary are actually
        distinguishable.
        """
        ax = self.layout_ax
        if self._layout_inset is not None:
            # ax.clear() leaves child axes behind, so drop it explicitly.
            self._layout_inset.remove()
            self._layout_inset = None
        ax.clear()

        params = result.params
        profiles = wolter.mirror_profile(params)
        self._plot_layout_into(ax, result, profiles, full=True)

        ax.set_xlabel('z [mm]')
        ax.set_ylabel('radius [mm]')
        ax.set_title('Telescope profile (rays travelling −z)')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(alpha=.3)

        # Inset zoomed on the mirrors themselves.
        (zp, rp), (zs, rs) = profiles
        # Rays run diagonally from bottom-left to top-right, so the bottom
        # -right corner is free; the legend keeps the top-left.
        inset = ax.inset_axes([0.55, 0.12, 0.42, 0.45])
        self._plot_layout_into(inset, result, profiles, full=False)
        zlo = params.z0 - params.secondary_length
        zhi = params.z0 + params.primary_length
        rlo, rhi = float(np.min(rs)), float(np.max(rp))
        zpad, rpad = .05 * (zhi - zlo), max(.05 * (rhi - rlo), 1e-3)
        inset.set_xlim(zlo - zpad, zhi + zpad)
        inset.set_ylim(rlo - rpad, rhi + rpad)
        inset.tick_params(labelsize=6)
        inset.set_title('mirrors (zoom)', fontsize=7)
        inset.grid(alpha=.3)
        ax.indicate_inset_zoom(inset, edgecolor='gray')
        self._layout_inset = inset

        ax.canvas.draw_idle()

    @staticmethod
    def _plot_layout_into(ax, result, profiles, full):
        """Draw mirrors, rays and focus into ``ax``."""
        (zp, rp), (zs, rs) = profiles
        if result.path_z is not None:
            # Columns are individual rays, rows are successive surfaces.
            ax.plot(result.path_z, result.path_r, color='#1f77b4',
                    lw=.4, alpha=.5)
        ax.plot(zp, rp, color='k', lw=2.5,
                label='Primary' if full else None)
        ax.plot(zs, rs, color='#d62728', lw=2.5,
                label='Secondary' if full else None)
        if full:
            ax.axvline(0., color='crimson', ls='--', lw=1, label='Focus')

    def _draw_ee(self, result):
        ax = self.ee_ax
        ax.clear()
        rad, frac = wolter.encircled_energy(result)
        if len(rad):
            ax.plot(rad, frac, color='#1f77b4', lw=1.5)
            # The x axis is a radius, so the half-power point sits at
            # HPD/2 -- label both so the two can't be confused.
            ax.axhline(.5, color='crimson', ls='--', lw=1)
            ax.axvline(result.hpd_arcsec / 2., color='crimson', ls='--', lw=1,
                       label='half-power radius %.4f"\n(HPD = %.4f")'
                             % (result.hpd_arcsec / 2., result.hpd_arcsec))
            ax.legend(loc='lower right', fontsize=8)
        ax.set_xlabel('radius from centroid [arcsec]')
        ax.set_ylabel('enclosed fraction')
        ax.set_title('Encircled energy')
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=.3)
        ax.canvas.draw_idle()

    def clear_all(self):
        for ax in (self.spot_ax, self.layout_ax, self.ee_ax):
            ax.clear()
            ax.canvas.draw_idle()


SCRIPT_TEMPLATE = '''"""Equivalent PyXFocus script for the current settings."""
import numpy as np
import PyXFocus.sources as sources
import PyXFocus.surfaces as surf
import PyXFocus.transformations as tran
import PyXFocus.analyses as anal
import PyXFocus.conicsolve as conic

r0, z0 = {r0!r}, {z0!r}
primary_length, secondary_length, psi = {pl!r}, {sl!r}, {psi!r}

# Primary entrance aperture.
rin = conic.primrad(z0, r0, z0, psi=psi)
rout = conic.primrad(z0 + primary_length, r0, z0, psi=psi)

np.random.seed({seed!r})
rays = sources.annulus(rin, rout, {n!r})
tran.transform(rays, 0, 0, -(z0 + primary_length + 500.), 0, 0, 0)

# Off-axis source: {off!r} arcmin at azimuth {az!r} deg.
theta = np.radians({off!r} / 60.)
phi = np.radians({az!r})
if theta:
    n_rays = len(rays[1])
    rays[4] = np.repeat(np.sin(theta) * np.cos(phi), n_rays)
    rays[5] = np.repeat(np.sin(theta) * np.sin(phi), n_rays)
    rays[6] = np.repeat(-np.cos(theta), n_rays)

# Primary.
surf.wolterprimary(rays, r0, z0, psi=psi)
tran.reflect(rays)
ind = np.logical_and(rays[3] > z0, rays[3] < z0 + primary_length)
rays = tran.vignette(rays, ind=ind)

# Secondary, in its misaligned frame.
misalign = ({dx!r}, {dy!r}, {dz!r},
            np.radians({rx!r} / 60.), np.radians({ry!r} / 60.),
            np.radians({rz!r} / 60.))
tran.transform(rays, *misalign)
surf.woltersecondary(rays, r0, z0, psi=psi)
tran.reflect(rays)
tran.itransform(rays, *misalign)
ind = np.logical_and(rays[3] > z0 - secondary_length, rays[3] < z0)
rays = tran.vignette(rays, ind=ind)

# Best focus and performance.
focus_z = surf.focusI(rays)
hpd_arcsec = anal.hpd(rays) / z0 * 180. / np.pi * 3600.
print("rays surviving:", len(rays[1]))
print("HPD [arcsec]:", hpd_arcsec)
'''


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle('PyXFocus — Wolter-I Explorer')
        self.resize(1180, 780)
        self._worker = None
        self._result = None

        self.panel = ParameterPanel()
        self.panel.changed.connect(self._on_changed)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumWidth(300)

        self.trace_button = QtWidgets.QPushButton('Trace')
        self.trace_button.setDefault(True)
        self.trace_button.clicked.connect(self.run_trace)
        self.auto_box = QtWidgets.QCheckBox('Auto-trace on change')
        self.auto_box.setChecked(True)
        reset_button = QtWidgets.QPushButton('Reset')
        reset_button.clicked.connect(self.panel.reset)
        script_button = QtWidgets.QPushButton('Show script')
        script_button.setToolTip(
            'Show the plain PyXFocus script that reproduces these settings')
        script_button.clicked.connect(self.show_script)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.trace_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(script_button)

        left = QtWidgets.QWidget()
        left_box = QtWidgets.QVBoxLayout(left)
        left_box.setContentsMargins(8, 8, 4, 8)
        left_box.addWidget(scroll, 1)
        left_box.addWidget(self.auto_box)
        left_box.addLayout(buttons)

        self.metrics = MetricsBar()
        self.tabs = PlotTabs()

        right = QtWidgets.QWidget()
        right_box = QtWidgets.QVBoxLayout(right)
        right_box.setContentsMargins(4, 8, 8, 8)
        right_box.addWidget(self.metrics)
        right_box.addWidget(self.tabs, 1)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage('Ready')

        # Coalesce rapid edits into one trace.
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.run_trace)

        self.run_trace()

    def _on_changed(self):
        if self.auto_box.isChecked():
            self._timer.start()

    def run_trace(self):
        if self._worker is not None and self._worker.isRunning():
            self._timer.start()
            return
        self.trace_button.setEnabled(False)
        self.statusBar().showMessage('Tracing…')
        self._worker = TraceWorker(self.panel.params(), self)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, result):
        self.trace_button.setEnabled(True)
        self._result = result
        if result.message:
            self.metrics.clear()
            self.tabs.clear_all()
            self.statusBar().showMessage(result.message)
            return
        self.metrics.update_metrics(result)
        self.tabs.draw_all(result)
        self.statusBar().showMessage(
            'Traced %d rays — HPD %.4f arcsec'
            % (result.num_launched, result.hpd_arcsec))

    def _on_failed(self, message):
        self.trace_button.setEnabled(True)
        self.metrics.clear()
        self.statusBar().showMessage('Trace failed')
        QtWidgets.QMessageBox.critical(self, 'Trace failed', message)

    def show_script(self):
        p = self.panel.params()
        script = SCRIPT_TEMPLATE.format(
            r0=p.r0, z0=p.z0, pl=p.primary_length, sl=p.secondary_length,
            psi=p.psi, seed=p.seed, n=int(p.num_rays), off=p.offaxis,
            az=p.azimuth, dx=p.sec_dx, dy=p.sec_dy, dz=p.sec_dz,
            rx=p.sec_rx, ry=p.sec_ry, rz=p.sec_rz)

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Equivalent PyXFocus script')
        dialog.resize(760, 620)
        box = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QPlainTextEdit(script)
        text.setReadOnly(True)
        text.setStyleSheet('font-family: Menlo, Consolas, monospace;')
        box.addWidget(text)

        row = QtWidgets.QHBoxLayout()
        copy = QtWidgets.QPushButton('Copy to clipboard')
        copy.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(script))
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(dialog.accept)
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(close)
        box.addLayout(row)
        dialog.exec_()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
