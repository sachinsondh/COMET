import logging
import numpy as np
import pyqtgraph as pq

from time import sleep, time
from PyQt5.QtWidgets import *
from ..misc_plugins import engineering_notation as en
from .Pause_stripscan_widget import pause_stripscan_widget


from ..utilities import (
    raise_exception,
    change_axis_ticks,
    get_thicks_for_timestamp_plot,
)

l = logging.getLogger(__name__)


class Stripscan_window:
    def __init__(self, GUI_classes, layout):

        self.variables = GUI_classes
        self.layout = layout

        self.ticksStyle = {"pixelsize": 10}
        self.labelStyle = {"color": "#FFF", "font-size": "13px"}
        self.titleStyle = {"color": "#FFF", "size": "10pt"}

        self.measurement_list = [
            ("Idark", ["Pad", "#"], ["Current", "A"], [False, False], True),
            ("Idiel", ["Pad", "#"], ["Current", "A"], [False, False], True),
            ("Istrip", ["Pad", "#"], ["Current", "A"], [False, False], True),
            ("Rpoly", ["Pad", "#"], ["Resistance", "Ohm"], [False, False], False),
            ("Rint", ["Pad", "#"], ["Resistance", "Ohm"], [False, False], False),
            ("Cac", ["Pad", "#"], ["Capacitance", "F"], [False, False], False),
            ("Cint", ["Pad", "#"], ["Capacitance", "F"], [False, False], False),
        ]

        # Settings tab
        stripscan_widget = QWidget()

        self.stripscan = self.variables.load_QtUi_file("stripscan.ui", stripscan_widget)
        self.layout.addWidget(stripscan_widget)
        self.strip = -1
        self.variables.default_values_dict["settings"]["current_strip"] = self.strip
        self.variables.default_values_dict["settings"]["Bad_strips"] = 0
        self.variables.default_values_dict["settings"]["Start_time"] = None
        self.variables.default_values_dict["settings"]["End_time"] = None
        self.stripscan_time = np.array([])
        self.strip_times = []
        self.variables.default_values_dict["settings"]["strip_scan_time"] = 0
        self.new_meas = True
        self.number_of_strips = 1

        # Config plots
        for items in self.measurement_list:
            self.config_plot(items[0], items[1], items[2], items[3], items[4])

        # Config value text
        self.update_text()

        # Button actions
        self.stripscan.Pause_button.clicked.connect(self.pause_button_action)

        # Adds the function to the framework function, so that they called everytime the framework is updated
        self.variables.add_update_function(self.update_strip_stat)
        self.variables.add_update_function(self.update_plots)
        self.variables.add_update_function(self.update_text)

    def config_plot(self, Title, xAxis, yAxis, logscale, inverty=False):
        """configs the plot for the different plots"""
        object = getattr(self.stripscan, Title.lower() + "_plot")

        object.setTitle(str(Title), **self.titleStyle)
        object.setLabel("bottom", str(xAxis[0]), units=str(xAxis[1]), **self.labelStyle)
        object.setLabel("left", str(yAxis[0]), units=str(yAxis[1]), **self.labelStyle)
        object.showAxis("top", show=True)
        object.showAxis("right", show=True)
        object.showGrid(x=True, y=True, alpha=None)
        object.setLogMode(x=logscale[0], y=logscale[1])
        object.setContentsMargins(0.0, 0.0, 0.0, 0.0)
        object.getPlotItem().invertY(inverty)
        self.variables.plot_objs[Title] = object

        change_axis_ticks(object, self.ticksStyle)

    def update_text(self):
        """This function updates the stext for the measurements"""
        if self.variables.default_values_dict["settings"][
            "new_data"
        ]:  # New data available ?
            try:
                self.stripscan.Idark_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Idark"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Idark"][1]))
                        if len(self.variables.meas_data["Idark"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Idiel_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Idiel"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Idiel"][1]))
                        if len(self.variables.meas_data["Idiel"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Istrip_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Istrip"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Istrip"][1]))
                        if len(self.variables.meas_data["Istrip"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Cac_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Cac"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Cac"][1]))
                        if len(self.variables.meas_data["Cac"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Rpoly_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Rpoly"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Rpoly"][1]))
                        if len(self.variables.meas_data["Rpoly"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Cint_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.mean(self.variables.meas_data["Cint"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Cint"][1]))
                        if len(self.variables.meas_data["Cint"][1]) > 0
                        else "NaN",
                    )
                )

                self.stripscan.Rint_value.setText(
                    "{} +- {}".format(
                        en.EngNumber(np.median(self.variables.meas_data["Rint"][1])),
                        en.EngNumber(np.std(self.variables.meas_data["Rint"][1]))
                        if len(self.variables.meas_data["Rint"][1]) > 0
                        else "NaN",
                    )
                )
            except:
                pass

    def update_plots(self):
        """This function updates all strip data plots"""

        # Loop over all plots/measurements
        if self.variables.default_values_dict["settings"]["new_data"]:
            for meas in self.measurement_list:
                plot_item = getattr(
                    self.stripscan, meas[0].lower() + "_plot"
                )  # gets me the plot item
                if len(self.variables.meas_data[meas[0]][0]) == len(
                    self.variables.meas_data[meas[0]][1]
                ):  # sometimes it happens that the values are not yet ready
                    plot_item.plot(
                        self.variables.meas_data[meas[0]][0],
                        self.variables.meas_data[meas[0]][1],
                        pen="#e53d46",
                        clear=True,
                    )

        # Config value text
        self.update_text()

    def to_many_bad_strips_action(self):
        """Things to do when to many bad strips are detected"""
        pass

    def pause_button_action(self):
        """This button pauses the strip scan, it asks if the HV should be shut of or not and if the table should go into the down position"""
        self.stripscan.Pause_button.setEnabled(False)
        dialog = pause_stripscan_widget(self, parent=self.layout)
        dialog.exec_()
        self.stripscan.Pause_button.setEnabled(True)
        sleep(3.0)

    def update_strip_stat(self):
        """This function updates the statistics window"""

        # Reset routine (does something when certain settings are right)
        self.reset_stat()

        # Update strip
        self.update_strip()

        # Update bad strip
        self.update_bad_strip()

        # Update stat text
        self.update_text_stat()

    def update_strip(self):
        """Updates the strip number and the progress bar"""
        # Loop over all possible measurement and find the highest strip number, which defines the current strip

        current_strip = self.variables.default_values_dict["settings"]["current_strip"]
        self.stripscan.currentstrip_lcd.display(
            current_strip
        )  # sets the display to the desired value
        try:
            self.stripscan.stripscan_progressBar.setValue(
                ((float(current_strip) + 1.0) / self.number_of_strips) * 100
            )
        except:
            self.stripscan.stripscan_progressBar.setValue(
                (1.0 / self.number_of_strips) * 100
            )

    def update_bad_strip(self):
        """Updates the bad strip number"""
        self.stripscan.badstrip_lcd.display(
            self.variables.default_values_dict["settings"]["Bad_strips"]
        )  # sets the display to the desired value

    def update_text_stat(self):
        """Updates the statistic text"""

        try:
            self.strip_times.append(
                self.variables.default_values_dict["settings"]["strip_scan_time"]
            )
            elapsedtime = (
                time() - self.variables.default_values_dict["settings"]["Start_time"]
            )
            percper = elapsedtime / (
                self.variables.default_values_dict["settings"]["progress"]
            )
            self.variables.default_values_dict["settings"]["End_time"] = (
                1 - self.variables.default_values_dict["settings"]["progress"]
            ) * percper
        except:
            pass

        self.stripscan.start_time.setText(
            self.variables.default_values_dict["settings"]["Start_time"]
        )  # sets the display to the desired value
        self.stripscan.end_time.setText(
            self.variables.default_values_dict["settings"]["End_time"]
        )  # sets the display to the desired value
        self.stripscan.strip_time.setText(
            str(
                round(
                    float(
                        self.variables.default_values_dict["settings"][
                            "strip_scan_time"
                        ]
                    ),
                    2,
                )
            )
        )  # sets the display to the desired value

    def reset_stat(self, kwargs=None):
        """Resets the statistics panel"""
        if (
            self.new_meas
            and self.variables.default_values_dict["settings"]["Measurement_running"]
            or True
        ):
            self.strip = -1  # All other values are reseted/updated automatically
            self.new_meas = False
            sensor = self.variables.default_values_dict["settings"].get(
                "Current_sensor", "None"
            )
            project = self.variables.default_values_dict["settings"]["Current_project"]
            try:
                self.number_of_strips = len(
                    self.variables.additional_files["Pad_files"][project][sensor][
                        "data"
                    ]
                )  # Acesses the last value of the pad file -> last strip number
            except:
                self.number_of_strips = 1

            if not self.number_of_strips:
                self.number_of_strips = 1

        if (
            not self.new_meas
            and not self.variables.default_values_dict["settings"][
                "Measurement_running"
            ]
        ):
            self.new_meas = True

    def temphum_plot(self):
        """Also button corresponding to temphum plot included"""

        def valuechange():
            """This is the function which is called, when a value is changed in the spin boxes"""

            tempmin.setMaximum(tempmax.value())
            tempmax.setMinimum(tempmin.value())
            hummin.setMaximum(hummax.value())
            hummax.setMinimum(hummin.value())

            self.variables.default_values_dict["settings"][
                "current_tempmin"
            ] = tempmin.value()
            self.variables.default_values_dict["settings"][
                "current_tempmax"
            ] = tempmax.value()
            self.variables.default_values_dict["settings"][
                "current_hummin"
            ] = hummin.value()
            self.variables.default_values_dict["settings"][
                "current_hummax"
            ] = hummax.value()

        def dry_air_action():

            if dry_air_btn.isChecked():
                dry_air_btn.setText("Humidity ctl. on")
                self.variables.default_values_dict["settings"][
                    "humidity_control"
                ] = True
            else:
                dry_air_btn.setText("Humidity ctl. off")
                self.variables.default_values_dict["settings"][
                    "humidity_control"
                ] = False

        def light_action():
            if light_btn.isChecked():
                self.variables.default_values_dict["settings"]["lights"] = True
            else:
                self.variables.default_values_dict["settings"]["lights"] = False

        def check_light_state():
            if (
                self.variables.default_values_dict["settings"]["lights"]
                and not light_btn.text() == "Lights on"
            ):  # Checks if the lights are on and the button is off
                light_btn.setText("Lights on")
            elif (
                not self.variables.default_values_dict["settings"]["lights"]
                and not light_btn.text() == "Lights off"
            ):
                light_btn.setText("Lights off")

        def config_temphum_plot(plot, plot2, pg):
            plot = plot.plotItem
            plot.setLabel("right", "humidity", units="%")
            plot.setLabel("bottom", "time")
            plot.setLabel("left", "temperature", units="Celsius")
            plot.getAxis("left").setPen(pg.mkPen(color="#c4380d", width=3))
            plot.getAxis("right").setPen(pg.mkPen(color="#025b94", width=3))
            plot.showAxis("top", show=True)
            plot.getAxis("top").setTicks([])
            plot.getAxis("bottom").setScale(1e-9)
            # plot.setRange(yRange=[15, 35])

            # For second plot
            plot.scene().addItem(
                plot2
            )  # inserts the second plot into the scene of the first
            plot2.setGeometry(plot.vb.sceneBoundingRect())
            plot.getAxis("right").linkToView(
                plot2
            )  # links the second y axis to the second plot
            plot2.setXLink(plot)  # sync the x axis of both plots
            # plot2.setRange(yRange=[0, 50])

        def __cut_arrays(data_array, maximum_time, arrays_to_cut):
            """This function cuts an array to a maximum time difference
            This function is supposed to be used only for temp and humidity shaped arrays
            """

            try:
                begin_time = data_array[arrays_to_cut[0]][0][0]
                end_time = data_array[arrays_to_cut[0]][0][-1]
                delta_time = (
                    data_array[arrays_to_cut[0]][0][1]
                    - data_array[arrays_to_cut[0]][0][0]
                )
                total_time = end_time - begin_time
                if total_time > maximum_time:
                    over_time = total_time - maximum_time
                    array_elm_to_drop = int(over_time / delta_time)
                    for arrays in arrays_to_cut:
                        data_array[arrays][0] = data_array[arrays][0][
                            array_elm_to_drop:
                        ]
                        data_array[arrays][1] = data_array[arrays][1][
                            array_elm_to_drop:
                        ]
            except:
                pass

        @raise_exception
        def update_temphum_plots(kwargs=None):
            # for rooms in self.rooms:
            if self.variables.default_values_dict["settings"]["new_data"]:
                temphum_plot.clear()  # clears the plot and prevents a memory leak
                hum_plot_obj.clear()
                p1 = temphum_plot.plotItem

                ax = p1.getAxis("bottom")  # This is the trick
                __cut_arrays(
                    self.variables.meas_data,
                    float(
                        self.variables.default_values_dict["settings"].get(
                            "temp_history", 3600
                        )
                    ),
                    ["temperature", "humidity"],
                )
                ax.setTicks(
                    [
                        get_thicks_for_timestamp_plot(
                            self.variables.meas_data["temperature"][0],
                            5,
                            self.variables.default_values_dict["settings"][
                                "time_format"
                            ],
                        )
                    ]
                )

                try:
                    if len(self.variables.meas_data["temperature"][0]) == len(
                        self.variables.meas_data["humidity"][1]
                    ):  # sometimes it happens that the values are not yet ready
                        p1.plot(
                            self.variables.meas_data["temperature"][0],
                            self.variables.meas_data["temperature"][1],
                            pen={"color": "r", "width": 2},
                            clear=True,
                        )
                        plot_item = setpg.PlotCurveItem(
                            self.variables.meas_data["humidity"][0],
                            self.variables.meas_data["humidity"][1],
                            pen={"color": "b", "width": 2},
                            clear=True,
                        )
                        hum_plot_obj.addItem(plot_item)
                        del plot_item  # the plot class needs a plot item which can be rendered, to avoid a mem leak delete the created plot item or 20k ram will be used
                        # hum_plot_obj.addItem(setpg.plot(self.variables.meas_data["humidity"][0],self.variables.meas_data["humidity"][1],pen={'color': "b", 'width': 2}, clear=True))
                        hum_plot_obj.setGeometry(
                            p1.vb.sceneBoundingRect()
                        )  # resize the second plot!
                except:
                    pass

        # Create sublayout
        temphum_layout = QGridLayout()

        # Frame over the objects
        frame = QLabel()
        frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        frame.setLineWidth(0)
        frame.setMidLineWidth(2)

        self.layout.addWidget(
            frame, self.temp_ypos, self.temp_xpos, self.temp_ysize, self.temp_xsize
        )

        x = np.zeros(1)
        y = np.zeros(1)

        setpg = pq
        # date_axis = CAxisTime(orientation='bottom')  # Correctly generates the time axis
        hum_plot_obj = setpg.ViewBox()  # generate new plot item
        temphum_plot = pq.PlotWidget()
        config_temphum_plot(temphum_plot, hum_plot_obj, setpg)  # config the plot items

        self.variables.add_update_function(update_temphum_plots)

        # Additional Variables will be generated for temp and hum
        # self.variables.default_values_dict["settings"].update({"lights": False, "humidity_control": True, "current_tempmin": 20, "current_tempmax": 25, "current_hummin": 20,"current_hummax": 25})

        # Spin Boxes for temp and humidity

        tempmin = QSpinBox()
        tempmax = QSpinBox()
        hummin = QSpinBox()
        hummax = QSpinBox()

        # Spinbox label
        textbox_temp = QLabel()
        textbox_temp.setText("Min temp.           Max temp.")
        textbox_temp.setFont(self.font)
        textbox_hum = QLabel()
        textbox_hum.setText("Min hum.          Max hum.")
        textbox_hum.setFont(self.font)

        # Config

        tempmin.setRange(15, 35)
        tempmin.setValue(
            float(self.variables.default_values_dict["settings"]["current_tempmin"])
        )
        tempmax.setRange(15, 35)
        tempmax.setValue(
            float(self.variables.default_values_dict["settings"]["current_tempmax"])
        )
        tempmin.valueChanged.connect(valuechange)
        tempmax.valueChanged.connect(valuechange)

        hummin.setRange(0, 70)
        hummin.setValue(
            float(self.variables.default_values_dict["settings"]["current_hummin"])
        )
        hummax.setRange(0, 70)
        hummax.setValue(
            float(self.variables.default_values_dict["settings"]["current_hummax"])
        )
        hummin.valueChanged.connect(valuechange)
        hummax.valueChanged.connect(valuechange)

        # Push buttons on the right for humidity control and light control

        dry_air_btn = QPushButton("Humidity ctl. on")
        self.variables.default_values_dict["settings"]["humidity_control"] = True
        dry_air_btn.setCheckable(True)
        dry_air_btn.toggle()
        dry_air_btn.clicked.connect(dry_air_action)

        light_btn = QPushButton()
        light_btn.setCheckable(True)
        # light_btn.toggle()
        light_btn.clicked.connect(light_action)

        # Humidity
        # temphum_plot.plot(x,y, pen="b")

        # Widgets add
        temphum_layout.addWidget(textbox_temp, 0, 0, 1, 2)
        temphum_layout.addWidget(tempmin, 1, 0)
        temphum_layout.addWidget(tempmax, 1, 1)

        temphum_layout.addWidget(textbox_hum, 2, 0, 1, 2)
        temphum_layout.addWidget(hummin, 3, 0)
        temphum_layout.addWidget(hummax, 3, 1)

        temphum_layout.addWidget(dry_air_btn, 4, 0, 1, 2)
        temphum_layout.addWidget(light_btn, 5, 0, 1, 2)

        temphum_layout.addWidget(temphum_plot, 0, 3, 10, 2)

        temphum_layout.setContentsMargins(8, 8, 0, 8)  # Makes a margin to the layout

        # Add the layout to the main layout
        self.layout.addLayout(
            temphum_layout,
            self.temp_ypos,
            self.temp_xpos,
            self.temp_ysize,
            self.temp_xsize,
        )
