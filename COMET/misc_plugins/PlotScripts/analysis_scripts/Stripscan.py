"""This script plots IVCV files together for files generated by QTC
Data must be """

import logging
import holoviews as hv
from holoviews import opts

hv.extension('bokeh')

from forge.tools import convert_to_df
from forge.tools import plot_all_measurements, convert_to_EngUnits
from forge.specialPlots import *


class Stripscan:

    def __init__(self, data, configs):

        self.log = logging.getLogger(__name__)
        self.data = convert_to_df(data, abs=False, keys=["Idark", "Idiel", "Istrip", "Cac", "Cint", "Rpoly", "Rint", "Strip",
                                                         "Humidity", "Temperature"])
        self.config = configs
        self.finalPlot = None
        self.df = []
        self.measurements = self.data["columns"]
        self.donts = ()
        try:
            if "Strip" not in self.measurements:
                self.data = convert_to_df(data, abs=False,
                                          keys=["Idark", "Idiel", "Istrip", "Cac", "Cint", "Rpoly", "Rint", "Pad"])
                self.measurements = self.data["columns"]
                padidx = self.measurements.index("Pad")
                self.xrow = "Pad"

            elif "Strip" in self.measurements:
                padidx = self.measurements.index("Strip")
                self.xrow = "Strip"

            else:
                self.log.critical("Neither the row 'Strip' nor 'Pad' could be found in the data! Analysis will fail!")

            del self.measurements[padidx]
            self.PlotDict = {"Name": "Stripscan"}
            self.donts = ("Pad", "Strip", "current", "voltage", "capacitance", "1C2", "temperature", "humidity")
        except:
            self.log.error("Stripscan plotting anlysis will fail, due to missing 'Strip' data row! Please add them to do an analysis!")

        #hv.renderer('bokeh').theme = "dark_minimal"

        # Convert the units to the desired ones
        for meas in self.measurements:
            unit = self.config["Stripscan"].get(meas, {}).get("UnitConversion", None)
            if unit:
                self.data = convert_to_EngUnits(self.data, meas, unit)


    def run(self):
        """Runs the script"""

        # Plot all Measurements
        self.basePlots = plot_all_measurements(self.data, self.config, self.xrow, "Stripscan", do_not_plot=self.donts)
        #self.finalPlot.Overlay.Humidity = addHistogram(self.finalPlot.Overlay.Humidity, dimensions="Humidity")
        self.PlotDict["BasePlots"] = self.basePlots
        self.PlotDict["All"] = self.basePlots


        # Plot all special Plots:
        # Histogram Plot
        self.Histogram = dospecialPlots(self.data, self.config, "Stripscan", "concatHistogram", self.measurements,
                                        **self.config["Stripscan"].get("AuxOptions", {}).get("concatHistogram", {}))
        if self.Histogram:
            self.PlotDict["Histogram"] = self.Histogram
            self.PlotDict["All"] = self.PlotDict["All"] + self.Histogram

        # Whiskers Plot
        self.WhiskerPlots = dospecialPlots(self.data, self.config, "Stripscan", "BoxWhisker", self.measurements)
        if self.WhiskerPlots:
            self.PlotDict["Whiskers"] = self.WhiskerPlots
            self.PlotDict["All"] = self.PlotDict["All"] + self.WhiskerPlots


        # Violin Plot
        self.Violin = dospecialPlots(self.data, self.config, "Stripscan", "Violin", self.measurements)
        if self.Violin:
            self.PlotDict["Violin"] = self.Violin
            self.PlotDict["All"] = self.PlotDict["All"] + self.Violin

        # Reconfig the plots to be sure
        self.PlotDict["All"] = config_layout(self.PlotDict["All"], **self.config["Stripscan"].get("Layout", {}))
        return self.PlotDict

