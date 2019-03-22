import logging

from UniDAQ.core.measurement import Measurement
from UniDAQ.core.process import Process

from UniDAQ.VisaConnectWizard import VisaConnectWizard as DeviceManager

class ProcessY(Process):

    default_delay = 0.1

    def is_alive(self):
        return self.iteration < 4

    def iteration_begin(self):
        x = self.parent.iteration
        y = self.iteration
        logging.info("X=%s Y=%s", x, y)
        # self.parent.manager.getDevice('table').move(x, y)

class ProcessX(Process):

    def is_alive(self):
        return self.iteration < 4

    def iteration_begin(self):
        ProcessY(self, self.delay).run()

class TableMeasurement(Measurement):

    def process(self):
        ProcessX(self).run()

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)

    manager = DeviceManager()

    measurement = TableMeasurement(manager)
    measurement.run()
