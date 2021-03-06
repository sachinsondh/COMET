# This starts the event loop for the GUI
# from GUI_classes import *
from PyQt5.QtCore import QCoreApplication, QThread, pyqtSignal
import numpy as np
import logging
from datetime import datetime


class GUI_event_loop(QThread):
    """ This class is for starting and managing the event loop for the GUI. It starts the syncronised connection betweent ifself and the
        measurement event loop. Message based on dictionaries. """

    # Create the signal for errBox handling
    Errsig = pyqtSignal(str)
    # message_from_main, message_to_main, devices_dict, default_values_dict, pad_files_dict, visa,
    def __init__(self, main, framework_variables, meas_data):

        # Initialise the GUI class, classes
        super(GUI_event_loop, self).__init__()

        self.main = main
        self.message_to_main = self.main.message_to_main
        self.message_from_main = self.main.message_from_main
        self.vcw = framework_variables["VCW"]
        self.device_dict = framework_variables["Devices"]
        self.default_values_dict = framework_variables["Configs"]["config"]
        self.default_values_dict["settings"]["State"] = "IDLE"
        self.stop_GUI_loop = False
        self.close_program = False
        self.measurement_running = False
        self.measurement_loop_running = True
        self.error_types = [
            "Critical",
            "CRITICAL",
            "Info",
            "INFO",
            "MeasError",
            "DataError",
            "RequestError",
            "MEASUREMENT_FAILED",
            "Warning",
            "WARNING",
            "FatalError",
            "ThresholdError",
            "ERROR",
            "Error",
        ]
        self.fatal_errors = [
            "MeasError",
            "DataError",
            "RequestError",
            "MEASUREMENT_FAILED",
            "FatalError",
            "ThresholdError",
        ]
        self.measurement_types = self.default_values_dict["settings"].get(
            "measurement_types", []
        )
        self.event_types = [
            "MEASUREMENT_STATUS",
            "MEASUREMENT_FINISHED",
            "CLOSE_PROGRAM",
            "ABORT_MEASUREMENT",
            "START_MEASUREMENT",
            "MEASUREMENT_EVENT_LOOP_STOPED",
            "PROGRESS",
            "STATE",
            "SAVE_SESSION",
            "LOAD_SESSION",
            "SAVE_ALIGNMENT",
            "LOAD_ALIGNMENT",
        ]
        self.error_list = []
        self.measurement_list = []
        self.event_list = []  # Messages send to the loop
        self.pending_events = (
            {}
        )  # Messages which should processed after all other orders are processed
        self.error_log = []
        self.default_values_dict["settings"]["new_data"] = True
        self.default_values_dict["settings"]["update_counter"] = 0
        self.default_values_dict["settings"]["last_plot_update"] = 0
        self.log = logging.getLogger(__name__)

        # Plot data
        self.meas_data = meas_data  # This is a dict with keys like "IV" etc. and than [np.array, np.array] for x,y

    def run(self):
        # Start additional timer for pending events, so that the GUI can shutdown properly
        self.main.add_update_function(self.process_pending_events)

        # Start the event loop
        self.start_loop()

    def start_loop(self):
        """ This function actually starts the event loop. """
        self.log.info("Starting GUI event loop...")
        while not self.stop_GUI_loop:
            message = (
                self.message_to_main.get()
            )  # This function waits until a message is received from the measurement loop!
            if message and isinstance(message, dict):
                self.log.debug("Got message: " + str(message))
                self.translate_message(message)  # This translates the message
                self.process_message(message)  # Here the message will be processed
                self.process_pending_events()  # Here all events during message work will be send or done
            elif not isinstance(message, dict):
                self.log.error(
                    "Messages to the GUI event loop "
                    "have to be of type dict, not type {}. Got message:".format(
                        type(message), message
                    )
                )

    def translate_message(self, message):
        """This function converts the message to a measurement list which can be processed"""

        # A measurement message is a Dict of a Dict {SignalMessage: {Orders}, ...}
        # Other messages like errors or data from the measurement event loop can be simple dicts like {IV: value} etc..
        if isinstance(message, dict):
            message_key_set = set(message.keys())
        else:
            self.log.error(
                "Got a message which is not a dict object, please check log, "
                "where this message comes from an fix the problem."
            )
            message_key_set = []

        # Create list of all errors in the message Dict
        self.error_list = list(set(self.error_types).intersection(message_key_set))

        # Create list of all measurements which are send (data from measurement loop)
        self.measurement_list = list(
            set(self.measurement_types).intersection(message_key_set)
        )

        # Create list of all events which are send (also all from the gui like measurements orders)
        self.event_list = list(set(self.event_types).intersection(message_key_set))

    def process_message(self, message):
        """This function will do some actions in case of a valid new operation"""

        # Show all errors which has occured in a message box
        for error in self.error_list:
            prepend = ""
            if "INFO" in error.upper():
                prepend = '<font color="green">'
            elif "ERROR" in error.upper():
                prepend = '<font color="#cc1414">'
                # Emit the signal
                self.Errsig.emit(str(message[str(error)]))
            elif "WARNING" in error.upper():
                prepend = '<font color="yellow">'
            elif "CRITICAL" in error.upper():
                prepend = '<font color="orange">'

            now = datetime.now()
            self.error_log.append(
                (
                    str(now),
                    prepend
                    + str(error).upper()
                    + ": "
                    + str(message[str(error)])
                    + "</font> <br/>",
                )
            )

        for (
            event
        ) in (
            self.event_list
        ):  # besser if "dfdf" in self.events oder? TODO vlt hier die abfrage der events anders machen
            if event == "START_MEASUREMENT":
                if not self.measurement_running:
                    # self.measurement_running = True # If a measurement is running the loop will send and MeasError in which this value will be correted
                    self.message_from_main.put(
                        {"Measurement": message.get["START_MEASUREMENT", {}]}
                    )
                    self.measurement_running = True
                else:
                    self.message_to_main.put({"MeasError": True})

            elif event == "ABORT_MEASUREMENT":
                self.message_from_main.put({"Status": {"ABORT_MEASUREMENT": True}})
                if self.measurement_running:
                    self.message_to_main.put(
                        {"Critical": "Measurement aborted by user interaction..."}
                    )

            elif event == "SAVE_ALIGNMENT":
                self.log.critical("Saving current alignment...")
                try:
                    import pickle, os
                    topickle = {"Alignment": self.default_values_dict["settings"]["Alignment"],
                                "trans_matrix": self.default_values_dict["settings"]["trans_matrix"],
                                "V0": self.default_values_dict["settings"]["V0"],
                                }

                    with open(
                        os.path.normpath("./COMET/resources/alignment_save.pkl"), "wb"
                    ) as output:
                        pickle.dump(
                            topickle, output, pickle.HIGHEST_PROTOCOL
                        )
                except Exception as err:
                    self.log.error("Saving alignment was not possible...", exc_info=True)

            elif event == "LOAD_ALIGNMENT":
                self.log.critical("Loading saved alignment...")
                try:
                    import pickle, os
                    with open(
                        os.path.normpath("./COMET/resources/alignment_save.pkl"), "rb"
                    ) as input:
                        alignment = pickle.load(input)
                        for key, value in alignment.items():
                            self.default_values_dict["settings"][key] = value
                except Exception as err:
                    self.log.error("Loading alignment was not possible...", exc_info=True)

            elif event == "SAVE_SESSION":
                self.log.critical("Saving current session...")
                try:
                    import pickle, os
                    from copy import deepcopy
                    topickle = deepcopy(self.default_values_dict)
                    del(topickle["settings"]["Devices"])
                    with open(
                        os.path.normpath("./COMET/resources/session_save.pkl"), "wb"
                    ) as output:
                        pickle.dump(
                            topickle, output, pickle.HIGHEST_PROTOCOL
                        )
                except Exception as err:
                    self.log.error("Saving session was not possible...", exc_info=True)

            elif event == "LOAD_SESSION":
                self.log.critical("Loading saved session...")
                try:
                    import pickle, os

                    with open(
                        os.path.normpath("./COMET/resources/session_save.pkl"), "rb"
                    ) as input:
                        self.default_values_dict.update(pickle.load(input))
                except Exception as err:
                    self.log.error("Loading session was not possible...", exc_info=True)

            elif event == "CLOSE_PROGRAM":
                if (
                    not self.measurement_running
                ):  # Prevents closing the program if a measurement is currently running
                    order = {"Status": {"CLOSE": True}}
                    self.close_program = True
                    self.message_from_main.put(order)
                else:
                    self.pending_events.update(
                        {"MeasRunning": True}
                    )  # message to user if measurement is running

            elif (
                event == "MEASUREMENT_FINISHED"
            ):  # Message from the event loop when measurement ist finished
                self.measurement_running = False

            elif (
                event == "MEASUREMENT_EVENT_LOOP_STOPED"
            ):  # Signals that the event loop has stoped which means that the main gui loop needs to be stoped
                self.measurement_loop_running = (
                    False  # This will be processed in the pending event function
                )

            elif event == "MEASUREMENT_STATUS":
                self.measurement_running = message["MEASUREMENT_STATUS"]

            elif event.upper() == "PROGRESS":
                # Updates the progress
                self.default_values_dict["settings"]["progress"] = float(message[event])

            elif event.upper() == "STATE":
                # Updates the State of the program
                self.default_values_dict["settings"]["State"] = str(message[event])

            else:
                self.log.warning(
                    "Event: {} was not recognised. No action taken!".format(event)
                )

        # Handles all data for coming from the measurements
        for measurement in self.measurement_list:

            # Correctly write the data to the arrays for plotting
            if measurement in self.default_values_dict["settings"]["measurement_types"]:
                if isinstance(message[measurement][0], float) or isinstance(
                    message[measurement][0], int
                ):
                    self.meas_data[measurement][0] = np.append(
                        self.meas_data[measurement][0], message[measurement][0]
                    )
                    self.meas_data[measurement][1] = np.append(
                        self.meas_data[measurement][1], message[measurement][1]
                    )
                elif isinstance(message[measurement][0], np.ndarray):
                    try:
                        if len(self.meas_data[measurement][0]):
                            self.meas_data[measurement][0] = np.vstack(
                                [
                                    self.meas_data[measurement][0],
                                    np.array(message[measurement][0]),
                                ]
                            )
                            self.meas_data[measurement][1] = np.vstack(
                                [
                                    self.meas_data[measurement][1],
                                    np.array(message[measurement][1]),
                                ]
                            )
                        else:
                            self.meas_data[measurement][0] = np.array(
                                message[measurement][0]
                            )
                            self.meas_data[measurement][1] = np.array(
                                message[measurement][1]
                            )

                    except Exception as e:
                        self.log.warning(
                            "Warning passed wrong dimensional arrays to array. Array must have same dimensions. Errorcode: {error!s}. "
                            "WARNING: This error can happen ones in the beginning, when the datatype changes or a np array is not yet initialized".format(
                                error=e
                            )
                        )
                        self.meas_data[measurement][0] = np.append(
                            [], np.array(message[measurement][0])
                        )
                        self.meas_data[measurement][1] = np.append(
                            [], np.array(message[measurement][1])
                        )
                self.default_values_dict["settings"][
                    "new_data"
                ] = True  # Initiates the update of the plots
                self.default_values_dict["settings"][
                    "last_plot_update"
                ] = self.default_values_dict["settings"]["update_counter"]
            else:
                self.log.error(
                    "Measurement "
                    + str(measurement)
                    + " could not be found in active data arrays. Data discarded."
                )

    def process_pending_events(self):
        """This function sends all occured events to the measurement loop and does some cleaning in the program"""

        if (
            not self.measurement_loop_running
            and not self.measurement_running
            and self.close_program
        ):
            # This if checks if the program should be closed
            self.log.info("Exiting GUI event loop")
            self.stop_GUI_loop = True  # Stops the event loop

            QCoreApplication.instance().quit()  # Stops the GUI
            self.log.info("Exiting GUI")

        # This function checks if updates of plots has been made and sets the variable back to False, so that no unnessesary plotting is done
        # Will be called as last update function
        # print(self.default_values_dict["settings"])
        if self.default_values_dict["settings"]["new_data"] and (
            self.default_values_dict["settings"]["update_counter"]
            > self.default_values_dict["settings"]["last_plot_update"]
        ):
            self.default_values_dict["settings"][
                "last_plot_update"
            ] = self.default_values_dict["settings"]["update_counter"]
            self.default_values_dict["settings"]["new_data"] = False

        self.default_values_dict["settings"]["update_counter"] += 1
