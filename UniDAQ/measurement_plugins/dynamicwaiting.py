# This file manages the dynamic waiting time measurements and it is intended to be used as a plugin for the QTC software

import logging
from time import time, sleep
import sys
import re
sys.path.append('../UniDAQ')
from ..utilities import timeit, transformation, create_new_file
from ..VisaConnectWizard import VisaConnectWizard


trans = transformation()
ttime = time
import numpy as np

class dynamicwaiting_class:

    def __init__(self, main_class):
        self.main = main_class
        self.vcw = main_class.framework["VCW"]
        self.switching = self.main.switching
        self.biasSMU = self.main.devices["BiasSMU"]
        self.compliance = self.main.job_details["dynamicwaiting"]["Compliance"]
        self.justlength = 24
        # The intervall of every measurement, (is something else then the delay value!)
        self.interval = self.main.job_details["dynamicwaiting"]["Interval"]/1000.
        self.buffer = self.main.job_details["dynamicwaiting"]["Samples"]
        # This delay is the fixed measurement delay, which delays EVERY measurement before a value is aquired
        # If you get bad values increase this to give the ADC some time to aquire a value
        self.delay = self.main.job_details["dynamicwaiting"]["Delay"]
        self.NPLC = self.main.job_details["dynamicwaiting"]["NPLC"]
        # The Start delay defines a global offset before a measurement series actually starts
        self.start_delay = self.main.job_details["dynamicwaiting"]["start_delay"]
        self.SMURange = self.main.job_details["dynamicwaiting"]["Range"]
        self.current_voltage = None
        self.voltage_step_list = []
        self.get_data_query = "printbuffer(1, {samples!s}, measbuffer)"
        self.get_timestamps_query = "printbuffer(1, {samples!s}, measbuffer.timestamps)"
        self.SMU_clean_buffer = "measbuffer = nil"
        self.log = logging.getLogger(__name__)
        self.xvalues = []
        self.yvalues = []

        self.SMU_config = "smua.measure.count = {samples!s} \n" \
                          "smua.measure.interval = {interval!s}\n" \
                          "measbuffer = smua.makebuffer(smua.measure.count)\n" \
                          "measbuffer.collecttimestamps = 1" \

        self.measureItobuffer = "smua.source.levelv = {level!s} \n" \
                                "delay(" + str(self.start_delay) + ")"\
                                "smua.measure.overlappedi(measbuffer)\n" \
                                "waitcomplete()\n"


    def run(self):
        # Starts the actual measurement
        time = self.do_dynamic_waiting()
        self.log.info("Dynamic warting time took: {} sec".format(time))

    def stop_everything(self):
        """Stops the measurement"""
        order = {"ABORT_MEASUREMENT": True}  # just for now
        self.main.queue_to_main.put(order)

    @timeit
    def do_dynamic_waiting(self):
        """
        This function does everything concerning the dynamic waiting time measurement
        :return:
        """

        # Config the SMU
        self.do_preparations(self.biasSMU, self.buffer, self.interval)

        # Construct results array
        self.xvalues = np.zeros((len(self.voltage_step_list), int(self.buffer)))
        self.yvalues = np.zeros((len(self.voltage_step_list), int(self.buffer)))
        # Conduct the measurement
        for i, voltage in enumerate(self.voltage_step_list):
            if not self.main.main.stop_measurement:  # To shut down if necessary

                # Some elusive error happens sometimes, where the smu forgets its pervious config
                #self.main.send_to_device(self.biasSMU, self.SMU_config.format(samples=self.buffer, interval=self.interval))
                # Here the magic happens it changes all values and so on
                self.xvalues[i], self.yvalues[i], time = self.do_dynamic_measurement("dynamicwaiting", self.biasSMU, voltage, self.buffer, self.interval, True)

                if self.main.check_complience(self.biasSMU, float(self.compliance), command="get_read",):
                    self.stop_everything()  # stops the measurement if compliance is reached

                if not self.main.steady_state_check(self.biasSMU, command="get_read_current", max_slope=1e-6, wait=0, samples=5, Rsq=0.5, complience=self.compliance):  # Is a dynamic waiting time for the measuremnts
                    self.stop_everything()

                sleep(1.)

        # Ramp down and switch all off
        self.current_voltage = self.main.main.default_dict["bias_voltage"]
        self.main.ramp_voltage(self.biasSMU, "set_voltage", self.current_voltage, 0, 20, 0.01)
        self.main.change_value(self.biasSMU, "set_voltage", "0")
        self.main.change_value(self.biasSMU, "set_output", "0")

        self.write_dyn_to_file(self.main.measurement_files["dynamicwaiting"], self.voltage_step_list, self.xvalues, self.yvalues)

    def write_dyn_to_file(self, file, voltages, xvalues, yvalues):
        """
        :param file: filepointer
        :param dataarray: nd.array with the data each entry has to be a one measurement with its current values
        :return: None
        """

        # Check if length of voltages matches the length of data array
        if len(xvalues) == len(yvalues):
            data = np.array([xvalues, yvalues])
            #data = np.transpose(data)
            # Write voltage header for each measurement
            self.main.write(file, ''+''.join([format(el, '<{}'.format(self.justlength*2)) for el in voltages])+"\n")
            for i in range(len(data[0,0,:])):
                times = [format(time, '<{}'.format(self.justlength)) for time in data[:, :, i][0]]
                curr = [format(curr, '<{}'.format(self.justlength)) for curr in data[:, :, i][1]]
                final = "".join([t+c for t, c in zip(times, curr)])
                self.main.write(file, final+"\n")
        else:
            self.log.error("Length of results array are non matching, abort storing data to file")

    def do_preparations(self, device, samples = 100, interval = 0.01):
        """This function prepares the setup, like ramping the voltage and steady state check
        """

        # Get ramping list
        voltage_Start = self.main.job_details["dynamicwaiting"].get("StartVolt", 0)
        voltage_End = self.main.job_details["dynamicwaiting"].get("EndVolt", 0)
        voltage_steps = self.main.job_details["dynamicwaiting"].get("Steps", 10)
        self.voltage_step_list = self.main.ramp_value(voltage_Start, voltage_End, voltage_steps)

        # Switch to IV for correct biasing for ramp
        if not self.switching.switch_to_measurement("IV"):
            self.stop_everything()

        # Configure the setup, compliance and switch on the smu
        self.main.send_to_device(self.biasSMU, self.SMU_clean_buffer)
        self.main.change_value(self.biasSMU, "set_voltage", "0")
        self.main.config_setup(self.biasSMU, [("set_complience_current", str(self.compliance)),
                                              ("set_NPLC", "{!s}".format(self.NPLC)),
                                              #("set_measurement_delay_factor", "{!s}".format(self.delay)),
                                              ("set_measure_adc", "smua.ADC_FAST"),
                                              ("set_current_range_low", str(self.SMURange)),
                                              ("set_meas_delay", str(self.delay))
                                             ])
        self.main.send_to_device(self.biasSMU, self.SMU_config.format(samples = samples, interval = interval))
        # Todo: set a first voltage to make sure it measures not only noise
        self.main.change_value(self.biasSMU, "set_voltage", "0.0")
        self.main.change_value(self.biasSMU, "set_output", "1")

        if self.main.steady_state_check(self.biasSMU, command="get_read_current", max_slope=1e-6, wait=0, samples=3, Rsq=0.5, complience=self.compliance):  # Is a dynamic waiting time for the measuremnts
            self.current_voltage = self.main.main.default_dict["bias_voltage"]
        else:
            self.stop_everything()

        # Try out the measurement a few time ( the 2657 does not behave correct in the first 2-4 iterations
        #for i in range(3):
        #    self.main.send_to_device(device, self.measureItobuffer.format(level=0))

        #self.file = create_new_file(self.main.job_details["dynamicwaiting"]["filename"],
        #                            self.main.job_details["dynamicwaiting"]["filepath"])

    def do_dynamic_measurement(self, str_name, device, voltage = 0, samples = 100, interval = 0.01, write_to_main = True):
        '''
         Does a simple dynamic waiting time measurement

        :param str_name: What measurement is conducted, only important when write_to_main is true
        :param device: Which device should be used
        :param xvalue: XValue used
        :param samples: How many samples should be taken
        :param interval: measurement interval
        :param write_to_main: Writes the value back to the main loop (default: True)
        :return: Returns the mean of all acquired values
        '''
        from time import time
        #self.main.send_to_device(self.biasSMU, self.SMU_clean_buffer)

        # Send the command to the device and wait till complete
        starttime = time()
        self.main.send_to_device(device, self.measureItobuffer.format(level=voltage))

        # Get the data from the device
        device_ansered = False
        iter = 0
        while not device_ansered:
            ans = self.vcw.query(device, self.get_data_query.format(samples=samples)).strip()
            times = self.vcw.query(device, self.get_timestamps_query.format(samples=samples)).strip()
            if ans:
                device_ansered = True
            elif iter > 5:
                ans = ""
                break
            else:
                iter += 1

        endtime = time()
        time = abs(endtime - starttime)

        if ans:
            #xvalues, yvalues = self.pic_device_answer(ans, time/self.buffer)
            xvalues, yvalues = self.pic_device_answer(ans, times, self.start_delay)

            if write_to_main: # Writes data to the main, or not
                self.main.queue_to_main.put({str(str_name): [xvalues, yvalues]})
            # Clear buffer
            #self.main.send_to_device(device, self.SMU_clean_buffer)
            return xvalues, yvalues, time

        else:
            self.log.error("Timeout occured while reading from the device! Increase timeout for devices if necessary"
                           "Or a buffer overflow happend. Check the buffer of the device!")
            return [], [], 0.0

    def pic_device_answer(self, values, times, offset):
        """
        Dissects the answer string and returns 2 array containing the x an y values
        :param answer_string: String to dissect
        :param interval: interval defined
        :return: xvalues, yvalues
        """
        expression = re.compile("\S+e-\d+")
        yvalues = list(map(float, expression.findall(values)))
        xvalues = list(map(float, expression.findall(times)))
        xvalues.append(xvalues[-1]+abs(xvalues[-2]-xvalues[-1]))
        xvalues = [x+offset for x in xvalues]
        #yvalues = answer_string.strip("[").strip("]").split(",")
        #yvalues = list(map(float, yvalues))
        #xvalues = [interval*x for x in range(len(yvalues))]
        # todo: somehowe i get one timestep fewer as measurement values
        return xvalues, yvalues
