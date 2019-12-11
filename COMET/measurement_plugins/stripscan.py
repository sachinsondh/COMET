# This file manages the stripscan measurements and it is intended to be used as a plugin for the QTC software

import logging
import sys
import numpy as np
from scipy import stats
sys.path.append('../COMET')
from time import time, sleep
from ..utilities import timeit, transformation
from .forge_tools import tools

class Stripscan_class(tools):

    def __init__(self, main_class):
        """
        This class can conduct a stripscan. Furthermore, it is baseclass for shortend stripscan measurements like
        singlestrip and freqquencyscan. These measurements, in principal do the same like stripscan but only on one
        strip. Therefore, we can derive.

        :param main_class:
        """
        self.main = main_class
        super(Stripscan_class, self).__init__(self.main.framework, self.main)
        self.log = logging.getLogger(__name__)

        # Aux. classes
        self.trans = transformation()
        self.vcw = self.main.framework["VCW"]
        self.switching = self.main.switching
        self.wedge_card_size = 2 # Number of strips, which can be contacted with one touchdown

        self.user_configs = self.main.settings["settings"].get("Measurement_configs", {}).get("Stripscan",
                                                                                              {})  # Loads the configs for IVCV measurements

        # These are generall parameters which can either be changed here or in the settings in the optional parameter seen above
        self.IVCV_configs = {
            # Devices Configs
            "BiasSMU": "BiasSMU",
            "LCRMeter": "LCRMeter",
            "DischargeSMU": "2410SMU",
            "Switching": "temphum_controller",
            "Elmeter": "Elektrometer",
            "SMU2": "2410SMU",

            # Commands Configs
            "Discharge": ("set_terminal", "FRONT"),
            "OutputON": ("set_output", "1"),
            "OutputOFF": ("set_output", "0"),
            "GetReadSMU": "get_read",  # This read can be a single current read or current, voltage pair
            "GetReadLCR": "get_read",
            "GetReadSMU2": "get_read",
            "GetReadElmeter": "get_read",

            # General Configs for the measurement
            "BaseConfig": [],
            "IstripConfig": [],
            "IdielConfig": [],
            "IdarkConfig": [],
            "RpolyConfig": [],
            "RintConfig": [],
            "CacConfig": [],
            "CintConfig": [],

        }

        self.log.info("Acquiring devices for stripscan measurements...")
        self.discharge_SMU = None
        self.bias_SMU = None
        self.LCR_meter = None
        self.discharge_switching = None
        self.elmeter = None
        self.SMU2 = None
        try:
            self.bias_SMU = self.main.devices[self.IVCV_configs["BiasSMU"]]
            self.LCR_meter = self.main.devices[self.IVCV_configs["LCRMeter"]]
            self.discharge_SMU = self.main.devices[self.IVCV_configs["DischargeSMU"]]
            self.elmeter = self.main.devices[self.IVCV_configs["Elmeter"]]
            self.SMU2 = self.main.devices[self.IVCV_configs["SMU2"]]
            self.discharge_switching = self.main.devices[self.IVCV_configs["Switching"]]
        except KeyError as valErr:
            self.log.critical(
                "One or more devices could not be found for the Stripscan measurements. Error: {}".format(valErr))

        # Measurements and corresponding units
        self.measurement_order = ["Istrip", "Rpoly", "Idark", "Cac", "Cint", "Cback", "Idiel", "Rint"]

        self.units = [("Istrip","current[A]"),
                      ("Rpoly", "res[Ohm]"),
                      ("Idiel","current[A]"),
                      ("Idark","current[A]"),
                      ("Rint", "res[Ohm]"),
                      ("Cac", "Cp[F]", "Rp[Ohm]"),
                      ("Cint", "Cp[F]", "Rp[Ohm]"),
                      ("Cback", "Cp[F]", "Rp[Ohm]")]
        # Misc.
        self.job = self.main.job_details
        self.sensor_pad_data = self.main.framework["Configs"]["additional_files"]["Pad_files"][self.job["Project"]][
            self.job["Sensor"]]
        self.strips = len(self.sensor_pad_data["data"])
        self.current_strip = self.main.framework['Configs']['config']['settings']["current_strip"]# Current pad position of the table
        self.height = self.main.framework['Configs']['config']['settings']["height_movement"]
        self.samples = 3
        self.last_istrip_pad = -1 # Number of the last pad on which a I strip was conducted, important for rpoly
        self.T = self.main.framework['Configs']['config']['settings']["trans_matrix"]
        self.V0 = self.main.framework['Configs']['config']['settings']["V0"]
        self.justlength = 24
        self.rintslopes = [] # here all values from the rint is stored
        self.project = self.main.job_details["Project"]
        self.sensor = self.main.job_details["Sensor"]
        self.current_voltage = self.main.framework['Configs']['config']['settings'].get("bias_voltage", 0)
        self.cal_to = {"Cac": 1000, "Cac_beta": 1000, "Cint": 1000000, "Cint_beta": 1000000}
        self.open_corrections = {}

        if "Rint_MinMax" not in self.main.framework['Configs']['config']['settings']:
            self.main.framework['Configs']['config']['settings']["Rint_MinMax"] = [-1.,1.,0.1]
            self.log.warning("No Rint boundaries given, defaulting to [-1.,1.,0.1]. Consider adding it to your settings")


        self.log = logging.getLogger(__name__)
        self.main.queue_to_main.put({"INFO": "Initialization of stripscan finished."})



    def run(self):
        # Check if alignment is present or not, if not stop measurement
        if not self.main.framework['Configs']['config']['settings']["Alignment"]:
            self.log.error("Alignment is missing. Stripscan can only be conducted if a valid alignment is present.")
            self.stop_everything()
            return


        # Preconfig the electrometer for current measurements, zero corr etc.
        commands = [("set_zero_check", "ON"),
                    ("set_measure_current", ""),
                    ("set_auto_current_range", "OFF"),
                    ("set_current_range", "20e-12"),
                    ("set_zero_correlation", "ON"),
                    ("set_current_range", "20e-9"),
                    ("set_auto_current_range", "ON")
                    ]
        self.config_setup(self.elmeter, commands)

        # Actually does something
        if "Stripscan" in self.main.job_details:

            # Some parameters which a specific for stripscan
            self.main.queue_to_main.put({"INFO": "Started Stripscan measurement routines..."})
            self.voltage_End = self.main.job_details["Stripscan"]["General"]["Bias Voltage [V]"]
            self.voltage_Start = 0
            self.voltage_steps = self.main.job_details["Stripscan"]["General"]["Voltage Step [V]"]
            self.compliance = self.main.job_details["Stripscan"]["General"]["Compliance [uA]"]

            self.do_stripscan()
        else:
            self.log.error("Howdy partner, seems like you started the stripscan but no data for a stripscan is set.")
            return

        self.clean_up()


    def clean_up(self):
        # Ramp down the voltage after stripscan
        # Discharge the capacitors in the decouple box
        # Switch to IV for correct biasing for ramp
        self.switching.switch_to_measurement("IV")  # correct bias is applied

        self.do_ramp_value(self.bias_SMU, "set_voltage", self.current_voltage, 0, self.voltage_steps, wait_time=0.3, compliance=0.001)
        self.change_value(self.bias_SMU,"set_voltage", "0")
        self.main.framework['Configs']['config']['settings']["bias_voltage"] = 0.
        self.change_value(self.bias_SMU, "set_output", "0")

        if not self.capacitor_discharge(self.discharge_SMU, self.discharge_switching, *self.IVCV_configs["Discharge"], do_anyway=True):
            self.stop_everything()
        #self.save_rint_slopes()

    def stop_everything(self):
        """Stops the measurement
        A signal will be genereated and send to the event loops, which sets the statemachine to stop all measurements"""
        self.main.queue_to_main.put({"Warning": "Stop Stripscan was called..."})
        order = {"ABORT_MEASUREMENT": True}  # just for now
        self.main.queue_to_main.put(order)
        self.log.warning("Measurement STOP was called, check logs for more information")

    def save_rint_slopes(self):
        # If a rint measurement was done save the data to a file
        # Todo: save rint slopes as well
        if self.main.save_data and self.rintslopes:

            filepath = self.main.job_details["Filepath"]
            filename = "rint_ramp_" + self.main.job_details["Filename"]

            rintsettings = self.main.framework['Configs']['config']['settings']["Rint_MinMax"]
            header = self.main.job_details["Header"]
            header += " #Ramp Voltage: " + str(rintsettings[0]) + " - "+ str(rintsettings[0])+ "V\n"
            header += " #Delta V: " + str(int(rintsettings[2])) + " V\n\n"

            unitsheader = "Pad[#]".ljust(self.justlength) + "Voltage[V]".ljust(self.justlength) + "Current[A]".ljust(self.justlength)

            header += [unitsheader for i in self.rintslopes]
            header += "\n"
            file = self.main.create_data_file(header, filepath, filename)

    def do_preparations_for_stripscan(self, do_cal = True, measurement="Stripscan"):
        """This function prepares the setup, like ramping the voltage and steady state check
        """
        self.main.queue_to_main.put({"INFO": "Preparing setup for {}...".format(measurement)})
        if self.main.save_data and "Frequency Scan" not in self.main.job_details[measurement]:
            self.main.write(self.main.measurement_files[measurement], self.main.job_details[measurement].get("Additional Header", ""))  # TODO: pretty useless, an additional header to the file if necessary

            # Add the additional params to the header
            params_string = ""
            for key, value in self.sensor_pad_data.get("additional_params", {}).items():
                params_string += "# " + str(key) + ": " + str(value) + "\n"
            params_string += "\n\n"
            self.main.write(self.main.measurement_files[measurement], params_string)
        # extend for additional files

        # Switch to IV for correct biasing for ramp
        if not self.switching.switch_to_measurement("IV"):
            self.stop_everything()

        #Configure the setup, compliance and switch on the smu
        self.config_setup(self.bias_SMU, [("set_compliance_current", str(self.compliance))])
        self.change_value(self.bias_SMU, "set_output", "1")

        # Move the table down while ramp
        self.main.table.move_down(self.height)

        # Ramps the voltage, if ramp voltage returns false something went wrong -> stop
        self.main.queue_to_main.put({"INFO": "Ramping up to bias voltage..."})
        if not self.do_ramp_value(self.bias_SMU, "set_voltage", self.voltage_Start, self.voltage_End, self.voltage_steps, wait_time = 1, compliance=self.compliance):
            self.current_voltage = self.main.framework['Configs']['config']['settings']["bias_voltage"]
            self.stop_everything()

        #If everything works make steady state check
        else:
            if self.steady_state_check(self.bias_SMU, command="get_read_current", max_slope = 1e-6, wait = 0.1, samples = 3, Rsq = 0.5, compliance=self.compliance): # Is a dynamic waiting time for the measuremnts
                self.current_voltage = self.main.framework['Configs']['config']['settings']["bias_voltage"]
                if self.check_compliance(self.bias_SMU, self.compliance): #if compliance is reached stop everything
                    self.stop_everything()
            else:
                self.stop_everything()

        # Perform the open correction
        if do_cal:
            self.main.queue_to_main.put({"INFO": "Performing open correction on LCR Meter..."})
            self.perform_open_correction(self.LCR_meter, self.cal_to)
            self.main.queue_to_main.put({"INFO": "Open correction done..."})

        # Move the table up again
        self.main.queue_to_main.put({"INFO": "Lowering the probe card to sensor..."})
        self.main.table.move_up(self.height)

        self.main.queue_to_main.put({"INFO": "{} preparation done...".format(measurement)})

    def perform_open_correction(self, LCR, measurements, count=15):
        read_command = self.main.build_command(LCR, "get_read")
        for meas, freq in measurements.items():
            data = []
            self.main.queue_to_main.put({"INFO": "LCR open calibration on {} path...".format(meas)})
            if not self.switching.switch_to_measurement(meas):
                self.stop_everything()
                return
            self.change_value(LCR, "set_frequency", freq)
            sleep(0.2)
            for i in range(count):
                data.append(self.vcw.query(LCR, read_command).split(LCR.get("separator", ","))[0])
            self.open_corrections[meas] = np.mean(data)
        self.switching.switch_to_measurement("IV")
        self.main.queue_to_main.put({"INFO": "LCR open calibration finished!"})

    @timeit
    def do_stripscan(self):
        '''This function manages all stripscan measurements, also the frequency scan things
        Its ment to be used only once during the initiatior of the class'''

        self.do_preparations_for_stripscan()
        if not self.main.event_loop.stop_all_measurements_query():
            # generate the list of strips per measurement which should be conducted and the units and so on for the
            measurement_header = "Pad".ljust(self.justlength) # indicates the measurement
            unit_header = "#".ljust(self.justlength) # indicates the units for the measurement
            for measurement in self.measurement_order:
                if measurement in self.main.job_details["Stripscan"]:  # looks if measurement should be done
                    # Now generate a list of strips from the settings of the measurement
                    min = self.main.job_details["Stripscan"][measurement]["Start Strip"]
                    max = self.main.job_details["Stripscan"][measurement]["End Strip"]
                    delta = self.main.job_details["Stripscan"][measurement]["Measure Every"]
                    strip_list = self.ramp_value(min, max, delta)
                    self.main.job_details["Stripscan"][measurement].update({"strip_list": strip_list})
                    unit_index = [x[0] for x in self.units].index(measurement) # gets me the index for the units
                    #unit_header += str(self.units[unit_index][1]).ljust(self.justlength)
                    unit_header += "".join([format(el, '<{}'.format(self.justlength)) for el in self.units[unit_index][1:]])
                    measurement_header += str(measurement).ljust(self.justlength)

            # Now add humidity and temperature header
            if self.main.job_details.get("environemnt", True):
                measurement_header += "Temperature".ljust(self.justlength)+"Humidity".ljust(self.justlength)
                unit_header += "degree[C]".ljust(self.justlength)+"rel. percent[rel%]".ljust(self.justlength)

            # Now add the new header to the file
            if self.main.save_data:
                self.main.write(self.main.measurement_files["Stripscan"], measurement_header + "\n" + unit_header + "\n")

            # Discharge the capacitors in the decouple box
            if not self.capacitor_discharge(self.discharge_SMU, self.discharge_switching, *self.IVCV_configs["Discharge"], do_anyway=True):
                self.stop_everything()

            #  Do the actual measurements
            ###############################################################################
            # Find last strip or last strip of first half
            if "second_side_start" in self.sensor_pad_data["additional_params"]:
                partials = (
                            (1, int(self.sensor_pad_data["additional_params"]["second_side_start"])),
                            (int(self.sensor_pad_data["additional_params"]["second_side_start"]), int(self.strips)+1)
                            )
            else:
                partials = ((1, int(self.strips)+1),)


            for reverse_needles, part in enumerate(partials):
                if not self.main.event_loop.stop_all_measurements_query():
                    self.last_move = 9999999 # Ensuring that the table moves to the first point

                    for current_strip in range(*part): # Loop over all strips
                        if not self.main.event_loop.stop_all_measurements_query():
                            # Switch to normal IV mode
                            self.switching.switch_to_measurement("IV")
                            # If the table needs to be moved
                            # If the difference between last move and strip to measure is bigger than the probecard size
                            if abs(current_strip-self.last_move)>=self.wedge_card_size:
                                # Now check if we are not near the edge
                                if abs(part[1]-current_strip)>=self.wedge_card_size:
                                    move = True
                                    self.last_move = current_strip
                                # If we are near the edge, move card to fit the edge and say we donnot need to move
                                else:
                                    if self.main.table.move_to_strip(self.sensor_pad_data,
                                                                     part[1] - self.wedge_card_size + reverse_needles,
                                                                     self.trans, self.T, self.V0, self.height):
                                        self.last_move = part[1] - self.wedge_card_size  # Last strip the table moved to
                                    move = False

                            # If the next strip is contacted and we can accesss it with alternate switching
                            else:
                                move = False

                        # Do the strip measurement
                        self.do_one_strip(current_strip, move, reverse_needles)

                        # Change the progress
                        self.main.settings["settings"]["progress"] = self.strips/current_strip


    def do_one_strip(self, strip, move, reverse_needles):
        """
        Does all measurements which are to be done on one strip
        :param strip: The strip to measure
        :param move: Move the table (True) or switch to other needles (False)
        :return:
        """
        if not self.main.event_loop.stop_all_measurements_query():  # Prevents that empty entries will be written to file after aborting the measurement
            self.current_strip = strip
            # results.append({}) # Adds an empty dict to the results for the bad strip detection
            start = time()  # start timer for a strip measurement
            if self.main.save_data:
                self.main.write(self.main.measurement_files["Stripscan"],
                                str(self.sensor_pad_data["data"][str(strip)][0]).ljust(
                                    self.justlength))  # writes the strip to the file
            for measurement in self.measurement_order:
                if measurement in self.main.job_details[
                    "Stripscan"] and not self.main.event_loop.stop_all_measurements_query():  # looks if measurement should be done
                    # Now conduct the measurement
                    # But first check if this strip should be measured with this specific measurement
                    if strip in self.main.job_details["Stripscan"][measurement]["strip_list"]:
                        # Move to the strip if specified
                        if move:
                            if self.main.table.move_to_strip(self.sensor_pad_data, strip+reverse_needles, self.trans, self.T, self.V0, self.height):
                                self.last_move = strip
                        else:
                            self.log.info("Did not move to strip {}, switching is done instead".format(strip))
                        if not self.main.event_loop.stop_all_measurements_query() and not self.check_compliance(self.bias_SMU,
                                                                                                  self.compliance):
                            value = 0
                            try:
                                self.log.info("Conducting measurement: {!s}".format(measurement))
                                value = getattr(self, "do_" + measurement)(strip, self.samples, alternative_switching = move if reverse_needles else not move)
                                if not value:
                                    self.log.error(
                                        "An Error happened during strip measurement {!s}, please check logs!".format(
                                            measurement))
                            except Exception as err:
                                self.log.error(
                                    "During strip measurement {!s} a fatal error occured: {!s}".format(measurement,
                                                                                                       err),
                                    exc_info=True)  # log exception info at FATAL log level

                            # Write this to the file
                            if value and self.main.save_data:
                                if isinstance(value, float):
                                    value = [value]
                                self.main.write(self.main.measurement_files["Stripscan"],
                                                "".join([format(el, '<{}'.format(self.justlength)) for el in value]))
                    else:
                        if self.main.save_data:
                            self.main.write(self.main.measurement_files["Stripscan"], "--".ljust(
                                self.justlength))  # Writes nothing if no value is aquired

            # In the end do a quick bad strip detection
            try:
                badstrip = self.analysis.do_contact_check(self.main.measurement_data)
                if badstrip:
                    self.log.error("Bad contact of needles detected!: " + str(strip))
                    # Add the bad strip to the list of bad strips
                    if str(strip) in self.main.badstrip_dict:
                        self.main.badstrip_dict[str(strip)].update(badstrip)
                    else:
                        self.main.badstrip_dict[str(strip)] = badstrip
                        self.main.framework['Configs']['config']['settings']["Bad_strips"] += 1  # increment the counter
            except Exception as e:
                self.log.error("An error happened while performing the bad contact determination with error: "
                               "{}".format(e))

            if not self.main.event_loop.stop_all_measurements_query():
                # After all measurements are conducted write the environment variables to the file
                string_to_write = ""
                if self.main.job_details.get("environment", False):                    string_to_write = str(self.main.measurement_data["temperature"][1][-1]).ljust(self.justlength) + str(
                        self.main.measurement_data["humidity"][-1]).ljust(self.justlength)
                self.main.write(self.main.measurement_files["Stripscan"], string_to_write)

                # Write new line
                if self.main.save_data:
                    self.main.write(self.main.measurement_files["Stripscan"], "\n")

            if abs(float(start - time())) > 1.:  # Rejects all measurements which are to short to be real measurements
                delta = float(self.main.framework['Configs']['config']['settings']["strip_scan_time"]) + abs(start - time())
                self.main.framework['Configs']['config']['settings']["strip_scan_time"] = str(
                    delta / 2.)  # updates the time for strip measurement

    def __do_simple_measurement(self, str_name, device, xvalue = -1,
                                samples = 5, write_to_main = True,
                                query="get_read", apply_to=None):
        '''
         Does a simple measurement - really simple. Only acquire some values and build the mean of it

        :param str_name: What measurement is conducted
        :param device: Which device schould be used
        :param xvalue: Which strip we are on, -1 means arbitrary
        :param samples: How many samples should be taken
        :param write_to_main: Writes the value back to the main loop
        :param query: what query should be used
        :param apply_to: data array will be given to a function for further calculations
        :return: Returns the mean of all aquired values
        '''
        # Do some averaging over values
        values = []
        command = self.main.build_command(device, query)
        for i in range(samples): # takes samples
            values.append(self.vcw.query(device, command))
        values = np.array(list(map(lambda x: x.split(device.get("separator", ",")), values)), dtype=float)
        values = np.mean(values, axis=0)

        if apply_to:
            # Only a single float or int are allowed as returns
            value = apply_to(values)
        elif values.shape == (1,) or isinstance(values, float):
            value = values
        else:
            value = values[0]

        if write_to_main: # Writes data to the main, or not
            # Currently only x and y data are allowed for the gui to plot and to store the data temporarily.
            # If the device returns more then one value only the first value will be stored here
            # This changes nothing for the read out, all values will be stored!!!
            self.main.measurement_data[str(str_name)][0] = np.append(self.main.measurement_data[str(str_name)][0],
                                                                     [float(xvalue)])
            self.main.measurement_data[str(str_name)][1] = np.append(self.main.measurement_data[str(str_name)][1],
                                                                     [float(value)])
            self.main.queue_to_main.put({str(str_name): [float(xvalue), float(value)]})

        return value

    def do_Rpoly(self,  xvalue = -1, samples = 5, write_to_main = True, alternative_switching = False):
        '''Does the rpoly measurement'''
        device_dict = self.SMU2
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Rpoly", alternative_switching)):
                self.stop_everything()
                return
            voltage = -1.
            self.config_setup(device_dict, [("set_source_voltage", ""), ("set_measure_current", ""),("set_voltage", voltage), ("set_compliance", 90E-6), ("set_output", "ON")])  # config the 2410 for 1V bias on bias and DC pad
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.5, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Rpoly", device_dict, xvalue, samples, write_to_main=False) # This value is istrip +
            else:
                self.config_setup(device_dict, [("set_output", "OFF"), ("set_voltage", 0)])
                return False
            # Now subtract the Istrip
            if self.last_istrip_pad == xvalue:
                #todo: richtiger wert nehemen
                Istrip = self.main.measurement_data["Istrip"][1][-1]
            else:# If no Istrip then aquire a value
                self.log.info("No Istrip value for Rpoly calculation could be found, Istrip measurement will be conducted on strip {}".format(int(xvalue)))
                Istrip = self.do_Istrip(xvalue, samples, False)
                # Iges = Ipoly+Istrip
            value = float(value)-float(Istrip) # corrected current value

            rpoly = voltage/float(value)

            if write_to_main:  # Writes data to the main, or not
                self.main.measurement_data[str("Rpoly")][0] = np.append(self.main.measurement_data[str("Rpoly")][0],[float(xvalue)])
                self.main.measurement_data[str("Rpoly")][1] = np.append(self.main.measurement_data[str("Rpoly")][1],[float(rpoly)])
                self.main.queue_to_main.put({str("Rpoly"): [float(xvalue), float(rpoly)]})

            self.config_setup(device_dict, [("set_output", "OFF"), ("set_voltage", 0)])

            return rpoly

    def do_Rint(self, xvalue = -1, samples = 5, write_to_main = True, alternative_switching = False):
        '''Does the Rint measurement'''
        device_dict = self.elmeter
        voltage_device = self.SMU2
        d = device_dict
        rint = 0
        config_commands = [("set_zero_check", "ON"), ("set_measure_current", ""), ("set_zero_check", "OFF")]
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Rint", alternative_switching)):
                self.stop_everything()
                return
            self.config_setup(voltage_device, [("set_voltage", 0), ("set_compliance", 50E-6)])  # config the 2410
            self.config_setup(device_dict, config_commands)  # config the elmeter
            self.change_value(voltage_device, "set_output", "ON") # Sets the output of the device to on

            rintsettings = self.main.framework['Configs']['config']['settings']["Rint_MinMax"]
            minvoltage = rintsettings[0]
            maxvoltage = rintsettings[1]
            steps = rintsettings[2]

            voltage_list = self.ramp_value(minvoltage, maxvoltage, steps)

            # Get to the first voltage and wait till steady state
            self.change_value(voltage_device, "set_voltage", minvoltage)
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-2, wait=0.0, samples=2, Rsq=0.3, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                values_list = []
                past_volts = []
                for i, voltage in enumerate(voltage_list): # make all measurements for the Rint ramp
                    if not self.main.event_loop.stop_all_measurements_query():
                        self.change_value(voltage_device, "set_voltage", voltage)
                        value = self.__do_simple_measurement("Rint_scan", device_dict, xvalue, samples, write_to_main=False)
                        values_list.append(float(value))
                        past_volts.append(float(voltage))
                        self.main.queue_to_main.put({"Rint_scan": [past_volts, values_list]})

                if not self.main.event_loop.stop_all_measurements_query():
                    # Now make the linear fit for the ramp
                    slope, intercept, r_value, p_value, std_err = stats.linregress(voltage_list[2:], values_list[2:])
                    # TODO: make some comparision if it is ok, write this to a separate file etc.
                    rint = 1./slope
                    self.rintslopes.append([xvalue, rint, voltage_list, values_list ,slope, intercept, r_value, p_value, std_err]) # so everything is saved in the end
            else:
                self.main.queue_to_main.put({"MeasError": "Steady state could not be reached for the Rint measurement"})

        self.change_value(voltage_device, "set_voltage", 0)
        self.change_value(voltage_device, "set_output", "OFF")  # Sets the output of the device to off
        self.config_setup(device_dict, [("set_zero_check", "ON")])  # unconfig elmeter

        if write_to_main:  # Writes data to the main, or not
            self.main.measurement_data[str("Rint")][0] = np.append(self.main.measurement_data[str("Rint")][0],[float(xvalue)])
            self.main.measurement_data[str("Rint")][1] = np.append(self.main.measurement_data[str("Rint")][1],[float(rint)])
            self.main.queue_to_main.put({str("Rint"): [float(xvalue), float(rint)]})

        return rint

    def do_Idiel(self, xvalue = -1, samples = 5, write_to_main = True, alternative_switching = False):
        '''Does the idiel measurement'''
        device_dict = self.SMU2
        #config_commands = [("set_zero_check", "ON"), ("set_measure_current", ""), ("set_zero_check", "OFF")]
        config_commands = [("set_source_voltage", ""), ("set_measure_current", ""), ("set_current_range", 2.0E-6), ("set_compliance", 1.0E-6), ("set_voltage", "5.0"), ("set_output", "ON")]

        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Idiel", alternative_switching)):
                self.stop_everything()
                return
            self.config_setup(device_dict, config_commands) # config the elmeter
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.3, check_compliance=False): # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Idiel", device_dict, xvalue, samples, write_to_main=write_to_main)
            else:
                value =  False
            #self.config_setup(device_dict, [("set_zero_check", "ON")])  # unconfig elmeter
            self.config_setup(device_dict, [("set_voltage", "0"), ("set_output", "OFF"), ("set_current_range", device_dict.get("default_current_range",10E6))])  # unconfig elmeter
            return value

    def do_Istrip(self, xvalue = -1, samples = 5, write_to_main = True, alternative_switching = False):
        '''Does the istrip measurement'''
        device_dict = self.elmeter
        d=device_dict # alias for faster writing
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Istrip", alternative_switching)):
                self.stop_everything()
                return
            config_commands = [("set_zero_check", "ON"), ("set_measure_current", ""), ("set_zero_check", "OFF")]
            self.config_setup(device_dict, config_commands)  # config the elmeter
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0., samples=2, Rsq=0.5, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Istrip", device_dict, xvalue, samples, write_to_main=write_to_main)
            else:
                value = False
            self.config_setup(device_dict, [("set_zero_check", "ON")])  # unconfig elmeter
            self.last_istrip_pad = xvalue
            return value

    def do_Idark(self, xvalue = -1, samples = 5, write_to_main = True, alternative_switching = False):
        '''Does the idark measurement'''
        device_dict = self.bias_SMU
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Idark", alternative_switching)):
                self.stop_everything()
                return
            if self.steady_state_check(device_dict, command="get_read_current", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.5):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Idark", device_dict, xvalue, samples, query="get_read_current", write_to_main=write_to_main)
            else:
                return False
            return value
        else:
            return None

    def do_Cint(self, xvalue = -1, samples = 5,  freqscan = False, write_to_main = True, alternative_switching = False, frequency=1000000):
        '''Does the cint measurement'''
        device_dict = self.LCR_meter
        # Config the LCR to the correct freq of 1 MHz
        self.change_value(device_dict, "set_frequency", frequency)
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Cint", alternative_switching)):
                self.stop_everything()
                return
            sleep(0.2)  # Is need due to some stray capacitances which corrupt the measurement
            if self.steady_state_check(device_dict,  command="get_read", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.3, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Cint", device_dict, xvalue, samples, write_to_main=not freqscan)
            else:
                return False
            # Apply the correction fort this measurement
            corr = self.open_corrections.get("Cint_beta" if alternative_switching else "Cint", 0.0)
            return value - corr

    def do_CintAC(self, xvalue= -1, samples=5, freqscan=False, write_to_main=True, alternative_switching = False, frequency=1000000):
        '''Does the cint measurement on the AC strips'''
        device_dict = self.LCR_meter
        # Config the LCR to the correct freq of 1 MHz
        self.change_value(device_dict, "set_frequency", frequency)
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("CintAC", alternative_switching)):
                self.stop_everything()
                return
            sleep(0.2) #Because fuck you thats why. (Brandbox to LCR meter)
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.5,
                                         check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("CintAC", device_dict, xvalue, samples, write_to_main=not freqscan)
            else:
                return False
            # Apply the correction fort this measurement
            corr = self.open_corrections.get("CintAC_beta" if alternative_switching else "CintAC", 0.0)
            return value - corr

    def do_Cac(self, xvalue = -1, samples = 5, freqscan = False, write_to_main = True, alternative_switching = False, frequency=1000):
        '''Does the cac measurement'''
        device_dict = self.LCR_meter
        # Config the LCR to the correct freq of 1 kHz
        self.change_value(device_dict, "set_frequency", frequency)
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Cac", alternative_switching)):
                self.stop_everything()
                return
            sleep(0.2) # Is need due to some stray capacitances which corrupt the measurement
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0.0, samples=2,Rsq=0.5, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Cac", device_dict, xvalue, samples, write_to_main=not freqscan)
            else: return False

            # Apply the correction fort this measurement
            corr = self.open_corrections.get("Cac_beta" if alternative_switching else "Cac" , 0.0)
            return value-corr

    def do_Cback(self, xvalue = -1, samples = 5, freqscan = False, write_to_main = True, alternative_switching = False, frequency=1000):
        '''Does a capacitance measurement from one strip to the backside'''
        device_dict = self.LCR_meter
        # Config the LCR to the correct freq of 1 MHz
        self.change_value(device_dict, "set_frequency", frequency)
        if not self.main.event_loop.stop_all_measurements_query():
            if not self.switching.switch_to_measurement(self.get_switching_for_measurement("Cback", alternative_switching)):
                self.stop_everything()
                return
            sleep(0.2)  # Is need due to some stray capacitances which corrupt the measurement
            if self.steady_state_check(device_dict, command="get_read", max_slope=1e-6, wait=0.0, samples=2, Rsq=0.5, check_compliance=False):  # Is a dynamic waiting time for the measuremnt
                value = self.__do_simple_measurement("Cback", device_dict, xvalue, samples, write_to_main=not freqscan)
            else: return 0
            # Apply the correction fort this measurement
            corr = self.open_corrections.get("Cback_beta" if alternative_switching else "Cback", 0.0)
            return value - corr

    def get_switching_for_measurement(self, meas, alt):
        """Gehts the name for the measuremnt, either normal or alternate switching"""
        if alt:
            return "{}_beta".format(meas)
        else:
            return meas
