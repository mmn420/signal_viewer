import pandas as pd
import pyedflib
import os
import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from fpdf import FPDF
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QSlider,
    QLabel,
    QGroupBox,
    QHBoxLayout,
)
import math
import librosa
from librosa import display
import scipy.fftpack
from scipy.io.wavfile import write
from scipy import signal as sig
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas

import sounddevice as sd
import soundfile as sf
import matplotlib.colors as colors

# A layout that contains the spectrogram and its sliders
class SpectroWidget(QWidget):
    def __init__(self, parent=None):
        super(SpectroWidget, self).__init__(parent)
        self.hbox = QHBoxLayout()
        self.sliders = []
        for i in range(2):
            self.sliders.append(QSlider(Qt.Vertical))
        self.hbox.addWidget(self.createSlider("Min", 0))
        self.hbox.addWidget(self.createSlider("Max", 1))
        self.setLayout(self.hbox)

    # Create 2 vertical sliders for vMin and vMax
    def createSlider(self, txt, ind):
        groupBox = QGroupBox()

        self.sliders[ind].setSingleStep(1)
        self.sliders[ind].valueChanged.connect(lambda: self.changeIntensity(ind))
        attribute = QLabel()
        attribute.setText(txt)
        vbox = QVBoxLayout()
        vbox.addWidget(self.sliders[ind], alignment=Qt.AlignHCenter)
        vbox.addWidget(attribute, alignment=Qt.AlignCenter)
        groupBox.setLayout(vbox)
        return groupBox

    def addWidget(self, widget):
        self.hbox.addWidget(widget)

    # Change the vMin and vMax values when the sliders are moved
    def changeIntensity(self, ind):
        ui.intensityMin = self.sliders[0].value()
        ui.intensityMax = self.sliders[1].value()

        ui.updateSpectro()


# A layout that contains the Equalizer window
class EQWidget(QWidget):
    def __init__(self, parent=None):
        super(EQWidget, self).__init__(parent)
        self.sliders = []
        self.gainLabels = []
        self.bands = []
        self.gainValues = []
        grid = QGridLayout()
        self.index = len(ui.mdi.subWindowList()) - 1 - ui.EQcount
        bandLength = (len(ui.freqs[self.index]) // 2) / 10
        for i in range(10):
            self.sliders.append(QSlider(Qt.Vertical))
            self.gainLabels.append(QLabel)
            self.bands.append(0)
            self.gainValues.append(0.0)
            grid.addWidget(
                self.createSlider(
                    int(bandLength * (i + 1)),
                    i,
                    int((ui.freqs[self.index].max() / 10) * (i + 1)),
                ),
                0,
                i,
            )

        self.setLayout(grid)

        self.setWindowTitle("Equalizer")

    def createSlider(self, txt, ind, label):
        groupBox = QGroupBox()

        self.sliders[ind].setMaximum(5)
        self.sliders[ind].setMinimum(0)
        self.sliders[ind].setValue(1)
        self.sliders[ind].setSingleStep(1)
        self.sliders[ind].sliderReleased.connect(lambda: self.updateWindows(ind))
        self.bands[ind] = txt
        freq = QLabel()
        freq.setText(str(label) + " Hz")
        self.gainLabels[ind] = QLabel()
        self.gainLabels[ind].setText("1")
        vbox = QVBoxLayout()
        vbox.addWidget(self.sliders[ind], alignment=Qt.AlignHCenter)
        vbox.addWidget(freq, alignment=Qt.AlignCenter)
        vbox.addWidget(self.gainLabels[ind], alignment=Qt.AlignCenter)
        groupBox.setLayout(vbox)

        return groupBox

    # Update  the graph and the spectrogram when the equalizer is used
    def updateWindows(self, ind):
        self.gainValues[ind] = self.sliders[ind].value()
        self.gainLabels[ind].setText(str(self.sliders[ind].value()))
        for i in range(
            (self.bands[ind] - int((len(ui.freqs[self.index]) // 2) / 10)),
            self.bands[ind],
        ):
            if i == 0:
                continue
            # Multiply the data by the gain
            ui.fftAbs[self.index][-i] = (
                ui.copyFFT[self.index][-i] * self.gainValues[ind]
            )
            ui.fftAbs[self.index][i] = ui.copyFFT[self.index][i] * self.gainValues[ind]
            # Get the inverse fourier for the amplified data
            ui.fft[self.index][i] = (
                ui.fftAbs[self.index][i] * math.cos(ui.fftPhase[self.index][i])
                + ui.fftAbs[self.index][i] * math.sin(ui.fftPhase[self.index][i]) * 1j
            )
            ui.fft[self.index][-i] = (
                ui.fftAbs[self.index][-i] * math.cos(ui.fftPhase[self.index][-i])
                + ui.fftAbs[self.index][-i] * math.sin(ui.fftPhase[self.index][-i]) * 1j
            )

        ui.updateGraph()
        ui.updateSpectro()


class MdiWind(QtWidgets.QMdiSubWindow):
    def closeEvent(self, event):
        # Checkes if there is an open subwindow
        if "Time-FFT" not in self.windowTitle():
            ui.activeWinds -= 1
            if ui.activeWinds == 0:
                ui.toggleGraphIcons(0)
        itr = 0
        # Adds closed subwindows to a list
        for widget in ui.mdi.subWindowList():
            if widget.windowTitle() == self.windowTitle():
                ui.deletedWinds.append(itr)
            itr += 1


class MainWind(QtWidgets.QMainWindow):
    def closeEvent(self, event):
        # Confirmation message when the user closes the app
        if ui.closeMssgBox:
            reply = QtWidgets.QMessageBox()
            reply.setText("Do you really want to close Sigview?")
            reply.setStandardButtons(
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            reply.setWindowTitle("Close")
            reply.setWindowIcon(QtGui.QIcon("icons/blank.png"))
            reply = reply.exec()

            if reply == QtWidgets.QMessageBox.Yes:
                event.accept()
            else:
                event.ignore()


class Ui_MainWindow(QMainWindow):
    ColorMap = "viridis"
    signals = []  # stores signals arrays
    graphRangesX = (
        []
    )  # checkpoints for the latest zoom/seek action on the graph's X-axis for all subwindows
    graphRangesY = []
    zoomRanges = []  # Stores the shown range of the X-axis for each graph
    deletedWinds = []  # Stores the closed windows to erase them from the subWindowList
    intensity = []
    fft = []
    fftAbs = []
    fftPhase = []
    freqs = []
    copyFFT = []
    EQcount = 0
    windowsCount = 0  # Apply an index for each window
    activeWinds = 0  # Stores the number of active windows
    closeMssgBox = False  # Checks if a message box should appear on close event
    plays = False  # Checks if play is clicked
    speedFactor = 1

    def Equalizer(self):
        self.activeWinds += 1
        self.EQWidget = EQWidget()
        mydialog = MdiWind(self)
        icon = QtGui.QIcon()
        icon.addPixmap(
            QtGui.QPixmap("icons/sig.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        mydialog.setWindowIcon(icon)
        mydialog.setWidget(self.EQWidget)
        mydialog.setFixedHeight(180)
        self.mdi.addSubWindow(mydialog)
        mydialog.show()
        self.EQcount += 1

    def toggleGraphIcons(self, state):
        self.actionZoomIn.setEnabled(state)
        self.actionZoomOut.setEnabled(state)
        self.actionPlay.setEnabled(state)
        self.actionSpectrogram.setEnabled(state)
        self.actionSave_as.setEnabled(state)
        self.actionForward.setEnabled(state)
        self.actionBackward.setEnabled(state)
        self.actionPause.setEnabled(state)
        self.action0_5x.setEnabled(state)
        self.action1x.setEnabled(state)
        self.action2x.setEnabled(state)
        self.actionCascade.setEnabled(state)
        self.actionTile.setEnabled(state)
        self.actionCloseAll.setEnabled(state)
        self.actionPlaySound.setEnabled(state)
        self.actionFFT.setEnabled(state)

    def toggleColors(self, state):
        self.actionViridis.setEnabled(state)
        self.actionGray.setEnabled(state)
        self.actionWinter.setEnabled(state)
        self.actionTurbo.setEnabled(state)
        self.actionHSV.setEnabled(state)
        self.actionSummer.setEnabled(state)
        self.actionCascade.setEnabled(True)
        self.actionTile.setEnabled(True)
        self.actionCloseAll.setEnabled(True)

    def uncheckColors(self):
        self.actionViridis.setChecked(False)
        self.actionGray.setChecked(False)
        self.actionWinter.setChecked(False)
        self.actionTurbo.setChecked(False)
        self.actionHSV.setChecked(False)
        self.actionSummer.setChecked(False)

    def uncheckSpeed(self):
        self.action0_5x.setChecked(False)
        self.action1x.setChecked(False)
        self.action2x.setChecked(False)

    def titleIndex(self, subWindowTitle):
        # Extracts the index of the subwindow from the window title and checks if the window is a spectrogram or a normal graph
        startInd = 0
        if subWindowTitle.find("Time-FFT") != -1:
            startInd = 12 if subWindowTitle[1] == "#" else 13

        if subWindowTitle[startInd + 1] != "#":
            index = int(subWindowTitle[startInd]) * 10 + int(
                subWindowTitle[startInd + 1]
            )
        else:
            index = int(subWindowTitle[startInd])

        return index

    def getWindow(self, windowTitle, index):
        if windowTitle.find(".wav") != -1 and windowTitle.find("FFT") == -1:
            itr = 0
            for widget in self.mdi.subWindowList():
                if widget.windowTitle().startswith(f"{index}"):
                    if windowTitle.find("modified") != -1:
                        return (self.mdi.subWindowList()[itr - 1], widget, True)
                    else:
                        return (widget, self.mdi.subWindowList()[itr + 1], True)
                itr += 1
        else:
            for widget in self.mdi.subWindowList():
                if widget.windowTitle().startswith(f"{index}"):
                    return (widget, 0, False)

    def initialize(
        self,
        sigInit,
        zoomInit,
        rangeXInit,
        intensityMin,
        intensityMax,
        freqMin,
        freqMax,
    ):
        self.signals.append(sigInit)
        self.zoomRanges.append(zoomInit)
        self.graphRangesX.append(rangeXInit)
        self.intensity.append([intensityMin, intensityMax, freqMin, freqMax])

    def fftInitialize(self, fft, fftAbs, fftPhase, freqs, copyFFT):
        self.fft.append(fft)
        self.fftAbs.append(fftAbs)
        self.fftPhase.append(fftPhase)
        self.freqs.append(freqs)
        self.copyFFT.append(copyFFT)

    # PDF
    def generatePDF(self, widget_list, filename):
        # prints all opened signals and their spectrograms (if required)
        pdf = FPDF()
        pdf.add_page()
        pdf.set_xy(0, 0)
        pdf.set_font("Arial", "B", 10)  # Font settings
        titlesList = []  # stores the titles of open widgets
        yCord = 0  # Y-coordinate on the PDF page

        # To iterate on all the opened widgets to get their title
        itr = 0
        for widget in widget_list:
            if itr not in self.deletedWinds:
                if widget.windowTitle().find("Time-FFT") == -1:
                    titlesList.append([widget.windowTitle(), itr])
                else:
                    # We put an indicator on the spectrogram widgets to mark them
                    tempStr = (
                        widget.windowTitle()[13:]
                        if widget.windowTitle()[1] != "#"
                        else widget.windowTitle()[12:]
                    )
                    tempStr = tempStr + "x"
                    titlesList.append([tempStr, itr])
            itr += 1

        titlesList.sort()

        for title in titlesList:
            index = self.titleIndex(title[0])
            if title[0][-1] != "x":
                # The widgets are transformed into images to get inserted into the PDF
                graphPlot = self.graphDraw(self.signals[index - 1])
                imgName = f"fileName{str(index)}.png"
                exporter = pg.exporters.ImageExporter(graphPlot.plotItem)
                exporter.parameters()["width"] = 250
                exporter.parameters()["height"] = 250
                exporter.export(imgName)
                title[0] = title[0][2:] if title[0][1] == "#" else title[0][3:]
                pdf.cell(0, 10, txt=title[0], ln=1, align="C")
                # We change the index of the Y-Coordinate to insert the next image
                yCord = pdf.get_y()
                pdf.image(
                    imgName,
                    x=None,
                    y=None,
                    w=95,
                    h=57,
                    type="PNG",
                    link="",
                )
                os.remove(imgName)
            else:
                self.spectroDraw(widget_list[title[1]], "pdf")
                imgName = f".fileName{str(index + 99)}.png"
                widget_list[title[1]].figure.savefig(imgName)
                pdf.image(
                    imgName,
                    x=110,
                    y=yCord - 2,
                    w=95,
                    h=60,
                    type="PNG",
                    link="",
                )
                os.remove(imgName)
        pdf.output(filename)

    def printPDF(self, widget_list):
        # allows the user to save the file and name it as they like
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export PDF", None, "PDF files (.pdf);;All Files()"
        )
        if filename:
            if QtCore.QFileInfo(filename).suffix() == "":
                filename += ".pdf"
            self.generatePDF(widget_list, filename)

    # Scroll/Zoom
    def doubleZoom(self, subwindow, type):
        index = self.titleIndex(subwindow.windowTitle())
        OGWindow, ModWindow, flag = self.getWindow(subwindow.windowTitle(), index)
        OGIndex = self.titleIndex(OGWindow.windowTitle())
        if type == "in":
            self.zoom(OGWindow, OGIndex, "in")
        else:
            self.zoom(OGWindow, OGIndex, "out")
        if flag:
            if type == "in":
                self.zoom(ModWindow, OGIndex + 1, "in")
            else:
                self.zoom(ModWindow, OGIndex + 1, "out")

    def doubleScroll(self, subwindow, type):
        index = self.titleIndex(subwindow.windowTitle())
        OGWindow, ModWindow, flag = self.getWindow(subwindow.windowTitle(), index)
        OGIndex = self.titleIndex(OGWindow.windowTitle())
        if type == "left":
            self.scroll(OGWindow, OGIndex, -1)
        else:
            self.scroll(OGWindow, OGIndex, 1)
        if flag:
            if type == "left":
                self.scroll(ModWindow, OGIndex + 1, -1)
            else:
                self.scroll(ModWindow, OGIndex + 1, 1)

    def scroll(self, subWindow, index, sign):
        subWindow.graphWidget.plotItem.getViewBox().translateBy(x=sign * 100, y=0)
        self.graphRangesX[index - 1] += sign * 100

    def zoom(self, subWindow, index, type):
        self.zoomRanges[index - 1] = (
            subWindow.graphWidget.viewRange()[0][1]
            - subWindow.graphWidget.viewRange()[0][0]
        )
        zoomFactor = 0.5 if type == "in" else 2

        if type == "in":
            zoomRange = self.zoomRanges[index - 1]
            if self.plays and zoomRange >= len(self.signals[index - 1]):
                self.play(subWindow)

        if self.zoomRanges[index - 1] > 50 or self.zoomRanges[index - 1] < len(
            self.signals[index - 1]
        ):
            subWindow.graphWidget.plotItem.getViewBox().scaleBy(x=zoomFactor, y=1)
            self.zoomRanges[index - 1] *= zoomFactor

        self.graphRangesX[index - 1] = subWindow.graphWidget.viewRange()[0][0]

        if self.zoomRanges[index - 1] >= len(self.signals[index - 1]):
            self.actionZoomOut.setEnabled(False)
        else:
            self.actionZoomOut.setEnabled(True)
        if self.zoomRanges[index - 1] > 50:
            self.actionZoomIn.setEnabled(True)
        else:
            self.actionZoomIn.setEnabled(False)

    # Play/Pause
    def playSound(self, subWindow):
        if subWindow.windowTitle().find("modified") != -1:
            data, fs = sf.read("test.wav", dtype="float32")
        else:
            data, fs = sf.read("original.wav", dtype="float32")
        sd.play(data, fs)

    def setStep(self, value, action):
        self.uncheckSpeed()
        action.setChecked(True)
        self.speedFactor = value

    def play(self, subWindow):
        index = self.titleIndex(subWindow.windowTitle())
        self.plays = True
        self.zoomRanges[index - 1] = (
            subWindow.graphWidget.viewRange()[0][1]
            - subWindow.graphWidget.viewRange()[0][0]
        )

        step = 0  # Cumulative variable that increases with time
        # Check if this is the max limit of the signal is reached or not
        while step + 40 + self.graphRangesX[index - 1] <= len(
            self.signals[index - 1]
            # while subWindow.graphWidget.viewRange()[0][1] < len(self.signals[index-1]):
        ):

            if not self.plays:
                self.graphRangesX[index - 1] += step
                break
            step += 40 * self.speedFactor
            self.playProcess(subWindow, index, step)

    def playProcess(self, subWindow, index, step):
        subWindow.graphWidget.setXRange(
            self.graphRangesX[index - 1] + step,
            self.zoomRanges[index - 1] + step + self.graphRangesX[index - 1],
        )

        QtWidgets.QApplication.processEvents()

    def stopClicked(self):
        self.plays = False
        sd.stop()

    # Spectrogram
    def updateSpectro(self):
        activeWindowTitle = self.mdi.activeSubWindow().windowTitle()
        flag = (
            activeWindowTitle == "Equalizer" or activeWindowTitle.find("modified") != -1
        )

        itr = 0
        for widget in self.mdi.subWindowList():
            if (
                (
                    flag
                    and widget.windowTitle().find("modified") != -1
                    and widget.windowTitle().find("Time-FFT") != -1
                )
                or (not flag and widget.windowTitle() == activeWindowTitle)
            ) and itr not in self.deletedWinds:
                self.spectroDraw(widget, 0)
                break
            itr += 1

    # Change the color palette
    def colorSpectro(self, color, action):
        if type(action) == type(self.actionViridis):
            self.uncheckColors()
            action.setChecked(True)
            self.ColorMap = color
        mydialog = self.mdi.subWindowList()[self.windowIndx]
        self.spectroDraw(mydialog, 0)

    def spectroDraw(self, widget, pdf):
        # Draws the spectrogram of the signal
        title = widget.windowTitle()
        index = self.titleIndex(title)
        widget.figure.clear()

        f, t, Sxx = sig.spectrogram(
            self.signals[index - 1],
            fs=200 if title.find(".wav") == -1 else self.sampling_rate,
        )

        SxxDecibel = 10 * np.log10(Sxx)
        ax = widget.figure.add_subplot()

        if self.intensity[index - 1][1] == -1:
            for i in range(4):
                if i % 2:
                    self.intensity[index - 1][i] = SxxDecibel.max()
                else:
                    self.intensity[index - 1][i] = (
                        SxxDecibel.min()
                        if SxxDecibel.min() != float("-inf")
                        else SxxDecibel.max() - 200
                    )
        elif pdf != "pdf":
            self.intensity[index - 1][0] = self.intensityMin
            self.intensity[index - 1][1] = self.intensityMax
        img = ax.pcolormesh(
            t,
            f,
            SxxDecibel,
            cmap=self.ColorMap,
            vmin=self.intensity[index - 1][0],
            vmax=self.intensity[index - 1][1],
        )
        widget.figure.colorbar(img, ax=ax)
        widget.canvas.draw()

    def Spectrogram(self, signal, title):
        # Inserts the drawn spectrogram into a widget
        index = self.titleIndex(title)
        mydialog = MdiWind(self)
        mydialog.figure = plt.figure()
        mydialog.canvas = FigureCanvas(mydialog.figure)
        mydialog.setWindowTitle(str(self.windowsCount) + "#Time-FFT: " + title)
        self.spectroDraw(mydialog, 0)
        icon = QtGui.QIcon()

        icon.addPixmap(
            QtGui.QPixmap("icons/sig.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        mydialog.setWindowIcon(icon)
        spectroWidget = SpectroWidget()

        for i in range(2):
            spectroWidget.layout().itemAt(i).widget().layout().itemAt(
                0
            ).widget().setMinimum(int(self.intensity[index - 1][2]))

            spectroWidget.layout().itemAt(i).widget().layout().itemAt(
                0
            ).widget().setMaximum(int(self.intensity[index - 1][3]))

            if not i:
                spectroWidget.layout().itemAt(i).widget().layout().itemAt(
                    0
                ).widget().setValue(int(self.intensity[index - 1][0]))
            else:
                spectroWidget.layout().itemAt(i).widget().layout().itemAt(
                    0
                ).widget().setValue(int(self.intensity[index - 1][1]))

        spectroWidget.addWidget(mydialog.canvas)

        mydialog.setWidget(spectroWidget)
        self.mdi.addSubWindow(mydialog)
        mydialog.show()

    def checkTool(self, subWindow, type):
        # checks the selected tool
        index = self.titleIndex(subWindow.windowTitle())

        self.windowsCount = self.windowsCount + 1

        if type == "s":
            self.initialize(0, 0, 0, 0, 0, 0, 0)
            self.fftInitialize(0, 0, 0, 0, 0)
            self.Spectrogram(self.signals[index - 1], subWindow.windowTitle())
        else:
            self.fftDraw(self.signals[index - 1], subWindow.windowTitle())

    # Checks if the active window is a spectrogram or an equilizer or a graph
    def checkWindow(self, subWindow):
        if subWindow:
            if subWindow.windowTitle().find("Time-FFT") != -1:
                self.toggleGraphIcons(0)
                self.toggleColors(1)

                itr = 0
                for widget in ui.mdi.subWindowList():
                    if widget.windowTitle() == subWindow.windowTitle():
                        self.windowIndx = itr
                    itr += 1
            elif subWindow.windowTitle() == "Equalizer":
                self.toggleGraphIcons(0)
                self.toggleColors(0)
            else:
                self.toggleColors(0)
                self.toggleGraphIcons(1)

        self.actionSave_as.setEnabled(True)

    # Graphs
    # Update the 'modified' graph of the signal according to the equilizer
    def updateGraph(self):

        windowsItr = 0
        for widget in self.mdi.subWindowList():
            if self.mdi.activeSubWindow() == widget:
                if widget.windowTitle().find("modified") == -1:
                    windowsItr -= 1
                break

            windowsItr += 1

        title = self.mdi.subWindowList()[windowsItr].windowTitle()
        index = self.titleIndex(title)
        ffti = []
        ffti = np.real_if_close(np.array(np.fft.ifft(self.fft[index - 1])))
        mydialog = self.mdi.subWindowList()[windowsItr]
        self.mdi.subWindowList()[windowsItr - 1].graphWidget.setXRange(
            self.graphRangesX[index - 2],
            self.graphRangesX[index - 2] + self.zoomRanges[index - 2],
        )
        self.mdi.subWindowList()[windowsItr - 1].graphWidget.setYRange(
            self.signals[index - 2].min(),
            self.signals[index - 2].max(),
        )
        mydialog.graphWidget = self.graphDraw(ffti)
        mydialog.graphWidget.setXRange(
            self.graphRangesX[index - 2],
            self.graphRangesX[index - 2] + self.zoomRanges[index - 2],
        )
        mydialog.setWidget(mydialog.graphWidget)
        self.signals[index - 1] = ffti
        write(r"test.wav", self.sampling_rate, ffti.astype(np.float64))

    # Graph the fft of the signal
    def fftDraw(self, signal, title):
        Amp = abs(np.fft.fft(signal))
        frequencies = np.fft.fftfreq(len(Amp), (1.0 / self.sampling_rate))
        self.initialize(Amp, 400, 0, 0, 0, 0, 0)
        self.fftInitialize(0, 0, 0, 0, 0)
        mydialog = MdiWind(self)
        mydialog.graphWidget = pg.PlotWidget()
        self.subwindow = mydialog.graphWidget
        mydialog.graphWidget.setBackground("w")
        mydialog.graphWidget.plot(
            x=frequencies[range(len(Amp) // 2)], y=Amp[range(len(Amp) // 2)], pen="b"
        )
        mydialog.graphWidget.showGrid(x=True, y=True)
        mydialog.graphWidget.setLimits(
            xMin=0,
            xMax=max(frequencies),
            yMin=min(Amp[range(len(Amp) // 2)]),
            yMax=max(Amp[range(len(Amp) // 2)]),
        )
        icon = QtGui.QIcon()
        icon.addPixmap(
            QtGui.QPixmap("icons/sig.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        mydialog.setWindowIcon(icon)
        mydialog.setWindowTitle(str(self.windowsCount) + "#FFT: " + title)
        mydialog.setWidget(mydialog.graphWidget)
        self.mdi.addSubWindow(mydialog)
        mydialog.show()

    def graphDraw(self, signal):
        # Plot the signal
        graphWidget = pg.PlotWidget()
        graphWidget.setBackground("w")
        graphWidget.plot(signal, pen="b")
        graphWidget.setLimits(
            xMin=0, xMax=len(signal), yMin=min(signal), yMax=max(signal)
        )
        graphWidget.showGrid(x=True, y=True)
        return graphWidget

    def Graph(self, signal, title):
        # insert the plot to a widget
        self.windowsCount = self.windowsCount + 1
        self.activeWinds += 1
        mydialog = MdiWind(self)
        icon = QtGui.QIcon()
        icon.addPixmap(
            QtGui.QPixmap("icons/sig.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        mydialog.setWindowIcon(icon)
        mydialog.setWindowTitle(str(self.windowsCount) + "#" + title)
        mydialog.graphWidget = self.graphDraw(signal)
        if title.find(".wav") == -1:
            mydialog.graphWidget.setXRange(0, 400, padding=0)
        mydialog.setWidget(mydialog.graphWidget)
        self.mdi.addSubWindow(mydialog)
        mydialog.show()
        self.toggleGraphIcons(1)

    # Reading files
    def read_edf(self, filename):
        f = pyedflib.EdfReader(filename)
        n = f.signals_in_file  # number of signals in the file
        signal_labels = f.getSignalLabels()
        # initiates an ndarry of zeroes
        sigbufs = np.zeros((n, f.getNSamples()[0]))
        for i in np.arange(n):
            # store the signal values in the array
            sigbufs[i, :] = f.readSignal(i)
        # Graph each sample in the file
        for i in range(0, n):
            self.initialize(sigbufs[i], 400, 0, 0, -1, 0, 0)
            self.fftInitialize(0, 0, 0, 0, 0)
            self.graphWidget = pg.PlotWidget()
            self.Graph(sigbufs[i], signal_labels[i])
        self.mdi.cascadeSubWindows()

    def read_txt(self, filename):
        with open(filename) as fp:
            signal_label = os.path.basename(filename)
            signal = []
            for line in fp:
                signal.append((line.rstrip().split(" ")[1]))
            data = np.array(signal).astype(np.float)
            self.initialize(data, 400, 0, 0, -1, 0, 0)
            self.fftInitialize(0, 0, 0, 0, 0)
            self.graphWidget = pg.PlotWidget()
            self.Graph(data, signal_label[0:-4])

    def read_csv(self, filename):
        data = pd.read_csv(filename).iloc[:, 1]
        signal_label = os.path.basename(filename)
        array = data.to_numpy()
        self.initialize(array, 400, 0, 0, -1, 0, 0)
        self.fftInitialize(0, 0, 0, 0, 0)
        self.graphWidget = pg.PlotWidget()
        self.Graph(array, signal_label[0:-4])

    def read_wav(self, filename):
        signal_label = os.path.basename(filename)

        samples, self.sampling_rate = librosa.load(
            filename, sr=None, mono=True, offset=0.0, duration=None
        )

        fft = np.fft.fft(samples)
        fftPhase = np.angle(fft)
        fftAbs = abs(fft)
        copyFFT = abs(fft)
        freqs = np.fft.fftfreq(len(fft), (1.0 / self.sampling_rate))
        ffti = np.real_if_close(np.array(np.fft.ifft(fft)))

        self.initialize(ffti, len(samples), 0, 0, -1, 0, 0)
        self.fftInitialize(0, 0, 0, 0, 0)

        self.Graph(ffti, signal_label)
        write(r"original.wav", self.sampling_rate, samples.astype(np.float64))

        self.initialize(ffti, len(samples), 0, 0, -1, 0, 0)
        self.fftInitialize(fft, fftAbs, fftPhase, freqs, copyFFT)
        self.Graph(ffti, signal_label + " modified")
        self.Equalizer()
        write(r"test.wav", self.sampling_rate, samples.astype(np.float64))
        self.mdi.cascadeSubWindows()

    def browsefiles(self):
        # self.mdi.closeAllSubWindows()
        self.closeMssgBox = True
        fname = QFileDialog.getOpenFileName(
            self, "Open file", "../", " *.wav;;" " *.edf;;" "*.csv;;" " *.txt;;"
        )
        file_path = fname[0]
        if file_path.endswith(".edf"):
            self.read_edf(file_path)
        elif file_path.endswith(".csv"):
            self.read_csv(file_path)
        elif file_path.endswith(".txt"):
            self.read_txt(file_path)
        elif file_path.endswith(".wav"):
            self.read_wav(file_path)

    # GUI
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        font = QtGui.QFont()
        font.setBold(False)
        font.setWeight(50)
        MainWindow.setFont(font)
        icon = QtGui.QIcon()
        icon.addPixmap(
            QtGui.QPixmap("icons/sig.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        MainWindow.setWindowIcon(icon)
        MainWindow.setStyleSheet("")
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.mdi = QtWidgets.QMdiArea()
        MainWindow.setCentralWidget(self.mdi)
        self.mdi.subWindowActivated.connect(
            lambda: self.checkWindow(self.mdi.activeSubWindow())
        )
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 579, 21))

        self.menubar.setStyleSheet(
            "QMenulBar{\n" "border-bottom: 1px solid #888888;\n" "}"
        )
        self.menubar.setInputMethodHints(
            QtCore.Qt.ImhEmailCharactersOnly
            | QtCore.Qt.ImhFormattedNumbersOnly
            | QtCore.Qt.ImhUrlCharactersOnly
        )
        self.menubar.setObjectName("menubar")
        self.menus = QtWidgets.QMenu(self.menubar)
        self.menus.setEnabled(True)
        self.menus.setObjectName("menus")
        self.menuEdit = QtWidgets.QMenu(self.menubar)
        self.menuEdit.setObjectName("menuEdit")
        self.menuSignalTools = QtWidgets.QMenu(self.menubar)
        self.menuSignalTools.setObjectName("menuSignalTools")
        self.menuPlay_navigate = QtWidgets.QMenu(self.menubar)
        self.menuPlay_navigate.setObjectName("menuPlay_navigate")
        self.menuInstruments_markers = QtWidgets.QMenu(self.menubar)
        self.menuInstruments_markers.setObjectName("menuInstruments_markers")
        self.menuPalette = QtWidgets.QMenu(self.menuInstruments_markers)
        self.menuPalette.setObjectName("menuPalette")
        self.menuWindow = QtWidgets.QMenu(self.menubar)
        self.menuWindow.setObjectName("menuWindow")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.toolBar = QtWidgets.QToolBar(MainWindow)
        self.toolBar.setEnabled(True)
        font = QtGui.QFont()
        font.setBold(False)
        font.setWeight(50)
        font.setKerning(True)
        self.toolBar.setFont(font)
        self.toolBar.setAutoFillBackground(False)
        self.toolBar.setStyleSheet(
            "QToolBar{\n"
            "background-color: rgb(255, 255, 255);\n"
            "padding: 0px;\n"
            "}\n"
            "\n"
            ""
        )
        self.toolBar.setMovable(False)
        self.toolBar.setIconSize(QtCore.QSize(30, 30))
        self.toolBar.setFloatable(True)
        self.toolBar.setObjectName("toolBar")
        MainWindow.addToolBar(QtCore.Qt.TopToolBarArea, self.toolBar)
        self.actionOpen = QtWidgets.QAction(MainWindow)
        icon1 = QtGui.QIcon()
        icon1.addPixmap(
            QtGui.QPixmap("icons/open.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionOpen.setIcon(icon1)
        self.actionOpen.setObjectName("actionOpen")
        self.actionPlay = QtWidgets.QAction(MainWindow)
        self.actionPlay.setEnabled(False)
        icon2 = QtGui.QIcon()
        icon2.addPixmap(
            QtGui.QPixmap("icons/play.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionPlay.setIcon(icon2)
        self.actionPlay.setObjectName("actionPlay")
        self.actionPlaySound = QtWidgets.QAction(MainWindow)
        self.actionPlaySound.setEnabled(False)
        icon11 = QtGui.QIcon()
        icon11.addPixmap(
            QtGui.QPixmap("icons/playSound.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionPlaySound.setIcon(icon11)
        self.actionPlaySound.setObjectName("actionPlaySound")
        self.action0_5x = QtWidgets.QAction(MainWindow)
        self.action0_5x.setEnabled(False)
        icon20 = QtGui.QIcon()
        icon20.addPixmap(
            QtGui.QPixmap("icons/0.5x.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.action0_5x.setIcon(icon20)
        self.action0_5x.setObjectName("action0_5x")
        self.action0_5x.setCheckable(True)
        self.action1x = QtWidgets.QAction(MainWindow)
        self.action1x.setEnabled(False)
        icon21 = QtGui.QIcon()
        icon21.addPixmap(
            QtGui.QPixmap("icons/1x.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.action1x.setIcon(icon21)
        self.action1x.setObjectName("action1x")
        self.action1x.setCheckable(True)
        self.action1x.setChecked(True)
        self.action2x = QtWidgets.QAction(MainWindow)
        self.action2x.setEnabled(False)
        icon22 = QtGui.QIcon()
        icon22.addPixmap(
            QtGui.QPixmap("icons/2x.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.action2x.setIcon(icon22)
        self.action2x.setObjectName("action2x")
        self.action2x.setCheckable(True)
        self.actionPause = QtWidgets.QAction(MainWindow)
        self.actionPause.setEnabled(False)
        icon3 = QtGui.QIcon()
        icon3.addPixmap(
            QtGui.QPixmap("icons/stop.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionPause.setIcon(icon3)
        self.actionPause.setObjectName("actionPause")
        self.actionBackward = QtWidgets.QAction(MainWindow)
        self.actionBackward.setEnabled(False)
        icon4 = QtGui.QIcon()
        icon4.addPixmap(
            QtGui.QPixmap("icons/back.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionBackward.setIcon(icon4)
        self.actionBackward.setObjectName("actionBackward")
        self.actionForward = QtWidgets.QAction(MainWindow)
        self.actionForward.setEnabled(False)
        icon5 = QtGui.QIcon()
        icon5.addPixmap(
            QtGui.QPixmap("icons/next.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionForward.setIcon(icon5)
        self.actionForward.setObjectName("actionForward")
        self.actionZoomIn = QtWidgets.QAction(MainWindow)
        self.actionZoomIn.setEnabled(False)
        icon6 = QtGui.QIcon()
        icon6.addPixmap(
            QtGui.QPixmap("icons/zoom in.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionZoomIn.setIcon(icon6)
        self.actionZoomIn.setObjectName("actionZoomIn")
        self.actionZoomOut = QtWidgets.QAction(MainWindow)
        self.actionZoomOut.setEnabled(False)
        icon7 = QtGui.QIcon()
        icon7.addPixmap(
            QtGui.QPixmap("icons/zoom out.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionZoomOut.setIcon(icon7)
        self.actionZoomOut.setObjectName("actionZoomOut")
        self.actionSpectrogram = QtWidgets.QAction(MainWindow)
        icon8 = QtGui.QIcon()
        icon8.addPixmap(
            QtGui.QPixmap("icons/spectr.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionSpectrogram.setIcon(icon8)
        self.actionSpectrogram.setObjectName("actionSpectrogram")
        self.actionSpectrogram.setEnabled(False)
        self.actionFFT = QtWidgets.QAction(MainWindow)
        icon10 = QtGui.QIcon()
        icon10.addPixmap(
            QtGui.QPixmap("icons/fft.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionFFT.setIcon(icon10)
        self.actionFFT.setObjectName("actionFFT")
        self.actionFFT.setEnabled(False)
        self.actionSave_as = QtWidgets.QAction(MainWindow)
        icon9 = QtGui.QIcon()
        icon9.addPixmap(
            QtGui.QPixmap("icons/save.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off
        )
        self.actionSave_as.setIcon(icon9)
        self.actionSave_as.setObjectName("actionSave_as")
        self.actionSave_as.setEnabled(False)
        self.actionExit = QtWidgets.QAction(MainWindow)
        self.actionExit.setObjectName("actionExit")
        self.actionCascade = QtWidgets.QAction(MainWindow)
        self.actionCascade.setEnabled(False)
        self.actionCascade.setObjectName("actionCascade")
        self.actionTile = QtWidgets.QAction(MainWindow)
        self.actionTile.setEnabled(False)
        self.actionTile.setObjectName("actionTile")
        self.actionCloseAll = QtWidgets.QAction(MainWindow)
        self.actionCloseAll.setEnabled(False)
        self.actionCloseAll.setObjectName("actionCloseAll")
        self.actionGray = QtWidgets.QAction(MainWindow)
        self.actionGray.setCheckable(True)
        self.actionGray.setEnabled(False)
        self.actionGray.setObjectName("actionGray")
        self.actionHSV = QtWidgets.QAction(MainWindow)
        self.actionHSV.setCheckable(True)
        self.actionHSV.setEnabled(False)
        self.actionHSV.setObjectName("actionHSV")
        self.actionSummer = QtWidgets.QAction(MainWindow)
        self.actionSummer.setCheckable(True)
        self.actionSummer.setEnabled(False)
        self.actionSummer.setObjectName("actionSummer")
        self.actionViridis = QtWidgets.QAction(MainWindow)
        self.actionViridis.setCheckable(True)
        self.actionViridis.setChecked(True)
        self.actionViridis.setEnabled(False)
        self.actionViridis.setObjectName("actionViridis")
        self.actionTurbo = QtWidgets.QAction(MainWindow)
        self.actionTurbo.setCheckable(True)
        self.actionTurbo.setEnabled(False)
        self.actionTurbo.setObjectName("actionTurbo")
        self.actionWinter = QtWidgets.QAction(MainWindow)
        self.actionWinter.setCheckable(True)
        self.actionWinter.setEnabled(False)
        self.actionWinter.setObjectName("actionWinter")

        self.menus.addAction(self.actionOpen)
        self.menus.addSeparator()
        self.menus.addAction(self.actionSave_as)
        self.menus.addSeparator()
        self.menus.addAction(self.actionExit)
        self.menuEdit.addAction(self.actionZoomIn)
        self.menuEdit.addAction(self.actionZoomOut)
        self.menuPlay_navigate.addAction(self.actionBackward)
        self.menuPlay_navigate.addAction(self.actionForward)
        self.menuPlay_navigate.addSeparator()
        self.menuPlay_navigate.addAction(self.actionPlay)
        self.menuPlay_navigate.addSeparator()
        self.menuPlay_navigate.addAction(self.actionPlaySound)
        self.menuPlay_navigate.addSeparator()
        self.menuPlay_navigate.addAction(self.action0_5x)
        self.menuPlay_navigate.addAction(self.action1x)
        self.menuPlay_navigate.addAction(self.action2x)
        self.menuPlay_navigate.addSeparator()
        self.menuPlay_navigate.addAction(self.actionPause)
        self.menuPalette.addAction(self.actionGray)
        self.menuPalette.addAction(self.actionHSV)
        self.menuPalette.addAction(self.actionSummer)
        self.menuPalette.addAction(self.actionViridis)
        self.menuPalette.addAction(self.actionTurbo)
        self.menuPalette.addAction(self.actionWinter)
        self.menuSignalTools.addAction(self.actionFFT)
        self.menuInstruments_markers.addAction(self.actionSpectrogram)
        self.menuInstruments_markers.addSeparator()
        self.menuInstruments_markers.addAction(self.menuPalette.menuAction())
        self.menuWindow.addAction(self.actionCascade)
        self.menuWindow.addAction(self.actionTile)
        self.menuWindow.addAction(self.actionCloseAll)
        self.menubar.addAction(self.menus.menuAction())
        self.menubar.addAction(self.menuEdit.menuAction())
        self.menubar.addAction(self.menuPlay_navigate.menuAction())
        self.menubar.addAction(self.menuSignalTools.menuAction())
        self.menubar.addAction(self.menuInstruments_markers.menuAction())
        self.menubar.addAction(self.menuWindow.menuAction())
        self.toolBar.addAction(self.actionOpen)
        self.toolBar.addAction(self.actionSave_as)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.actionZoomIn)
        self.toolBar.addAction(self.actionZoomOut)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.actionBackward)
        self.toolBar.addAction(self.actionPlay)
        self.toolBar.addAction(self.actionPlaySound)
        self.toolBar.addAction(self.actionForward)
        self.toolBar.addAction(self.actionPause)
        self.toolBar.addAction(self.action0_5x)
        self.toolBar.addAction(self.action1x)
        self.toolBar.addAction(self.action2x)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.actionFFT)
        self.toolBar.addAction(self.actionSpectrogram)

        # Connect the UI buttons to the logic of the program
        self.retranslateUi(MainWindow)
        self.actionExit.triggered.connect(MainWindow.close)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)
        self.actionOpen.triggered.connect(lambda: self.browsefiles())
        self.actionZoomIn.triggered.connect(
            lambda: self.doubleZoom(self.mdi.activeSubWindow(), "in")
        )
        self.actionZoomOut.triggered.connect(
            lambda: self.doubleZoom(self.mdi.activeSubWindow(), "out")
        )
        self.actionPlaySound.triggered.connect(
            lambda: self.playSound(self.mdi.activeSubWindow())
        )
        self.actionPlay.triggered.connect(lambda: self.play(self.mdi.activeSubWindow()))
        self.actionPause.triggered.connect(lambda: self.stopClicked())
        self.actionSpectrogram.triggered.connect(
            lambda: self.checkTool(self.mdi.activeSubWindow(), "s")
        )
        self.actionFFT.triggered.connect(
            lambda: self.checkTool(self.mdi.activeSubWindow(), "f")
        )
        self.actionForward.triggered.connect(
            lambda: self.doubleScroll(self.mdi.activeSubWindow(), "right")
        )
        self.actionBackward.triggered.connect(
            lambda: self.doubleScroll(self.mdi.activeSubWindow(), "left")
        )
        self.actionSave_as.triggered.connect(
            lambda: self.printPDF(self.mdi.subWindowList())
        )
        self.action0_5x.triggered.connect(lambda: self.setStep(0.5, self.action0_5x))
        self.action1x.triggered.connect(lambda: self.setStep(1, self.action1x))
        self.action2x.triggered.connect(lambda: self.setStep(2, self.action2x))
        self.actionGray.triggered.connect(
            lambda: self.colorSpectro("gray", self.actionGray)
        )
        self.actionHSV.triggered.connect(
            lambda: self.colorSpectro("hsv", self.actionHSV)
        )
        self.actionWinter.triggered.connect(
            lambda: self.colorSpectro("winter", self.actionWinter)
        )
        self.actionSummer.triggered.connect(
            lambda: self.colorSpectro("summer", self.actionSummer)
        )

        self.actionTurbo.triggered.connect(
            lambda: self.colorSpectro("turbo", self.actionTurbo)
        )
        self.actionViridis.triggered.connect(
            lambda: self.colorSpectro("viridis", self.actionViridis)
        )
        self.actionCascade.triggered.connect(lambda: self.mdi.cascadeSubWindows())
        self.actionTile.triggered.connect(lambda: self.mdi.tileSubWindows())
        self.actionCloseAll.triggered.connect(lambda: self.mdi.closeAllSubWindows())

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "SIGVIEW"))
        self.menus.setStatusTip(_translate("MainWindow", "Creates a new document"))
        self.menus.setTitle(_translate("MainWindow", "File"))
        self.menuEdit.setTitle(_translate("MainWindow", "Edit"))
        self.menuSignalTools.setTitle(_translate("MainWindow", "Signal Tools"))
        self.menuPlay_navigate.setTitle(_translate("MainWindow", "Play && navigate"))
        self.menuInstruments_markers.setTitle(_translate("MainWindow", "3D tools"))
        self.menuWindow.setTitle(_translate("MainWindow", "Window"))
        self.toolBar.setWindowTitle(_translate("MainWindow", "toolBar"))
        self.actionOpen.setText(_translate("MainWindow", "Open signal..."))
        self.actionOpen.setStatusTip(_translate("MainWindow", "Opens new signal"))
        self.actionOpen.setShortcut(_translate("MainWindow", "Ctrl+O"))
        self.actionPlay.setText(_translate("MainWindow", "Play signal (no sound)"))
        self.actionPlay.setShortcut(_translate("MainWindow", "F5"))
        self.actionPlaySound.setText(
            _translate("MainWindow", "Play signal (with sound)")
        )
        self.actionPlaySound.setShortcut(_translate("MainWindow", "F4"))
        self.actionPause.setText(_translate("MainWindow", "Stop playing"))
        self.actionPause.setStatusTip(_translate("MainWindow", "Stops acqusition"))
        self.actionPause.setShortcut(_translate("MainWindow", "F6"))
        self.actionBackward.setText(_translate("MainWindow", "Backward"))
        self.actionBackward.setShortcut(_translate("MainWindow", "Left"))
        self.actionForward.setText(_translate("MainWindow", "Forward"))
        self.actionForward.setShortcut(_translate("MainWindow", "Right"))
        self.actionZoomIn.setText(_translate("MainWindow", "Zoom In"))
        self.actionZoomIn.setStatusTip(_translate("MainWindow", "Zoom selected part"))
        self.actionZoomIn.setShortcut(_translate("MainWindow", "Ctrl+Up"))
        self.actionZoomOut.setText(_translate("MainWindow", "Zoom Out"))
        self.actionZoomOut.setStatusTip(_translate("MainWindow", "Show previous zoom"))
        self.actionZoomOut.setShortcut(_translate("MainWindow", "Ctrl+Down"))
        self.actionSpectrogram.setText(_translate("MainWindow", "Spectrogram..."))
        self.actionSpectrogram.setShortcut(_translate("MainWindow", "Ctrl+G"))
        self.actionTile.setShortcut(_translate("MainWindow", "Ctrl+Shift+T"))
        self.actionFFT.setText(_translate("MainWindow", "FFT spectrum analysis"))
        self.actionFFT.setStatusTip(
            _translate("MainWindow", "Spectrum of the visible part of the signal")
        )
        self.actionFFT.setShortcut(_translate("MainWindow", "Ctrl+F"))
        self.actionSave_as.setText(_translate("MainWindow", "Save signal as..."))
        self.actionSave_as.setShortcut(_translate("MainWindow", "Ctrl+S"))
        self.actionExit.setText(_translate("MainWindow", "Exit"))
        self.actionExit.setShortcut(_translate("MainWindow", "Alt+F4"))
        self.actionExit.setStatusTip(_translate("MainWindow", "Quits SIGVIEW"))
        self.actionCascade.setText(_translate("MainWindow", "Cascade"))
        self.actionCascade.setStatusTip(
            _translate("MainWindow", "Cascades open windows")
        )
        self.actionTile.setStatusTip(_translate("MainWindow", "Tiles open windows"))
        self.actionTile.setText(_translate("MainWindow", "Tile"))
        self.actionCloseAll.setText(_translate("MainWindow", "Close All"))
        self.actionCloseAll.setStatusTip(
            _translate("MainWindow", "Closes all open windows")
        )
        self.action0_5x.setText(_translate("MainWindow", "Slower"))
        self.action1x.setText(_translate("MainWindow", "Normal"))
        self.action2x.setText(_translate("MainWindow", "Faster"))
        self.menuPalette.setTitle(_translate("MainWindow", "Palette"))
        self.actionGray.setText(_translate("MainWindow", "Gray"))
        self.actionHSV.setText(_translate("MainWindow", "HSV"))
        self.actionSummer.setText(_translate("MainWindow", "Summer"))
        self.actionViridis.setText(_translate("MainWindow", "Viridis"))
        self.actionTurbo.setText(_translate("MainWindow", "Turbo"))
        self.actionWinter.setText(_translate("MainWindow", "Winter"))


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    MainWindow = MainWind()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec_())
