#!/usr/bin/env python

"""
UniDAQ

This program is developed for IV/CV measurements as well as strip scan
measurements for the QTC setup at HEPHY Vienna.
All rights are to the Programmer(s) and the HEPHY Vienna.
Distributing/using this software without permission of the programmer will be
punished!
 - Punishments: Death by hanging, Decapitation and/or ethernal contemption
 - Should the defendant demand trail by combat, than the combat will be three
   rounds of "rock-paper-scissors-lizard-spock".
   If the defendant should win, he/she can use the software as he/she wishes,
   otherwise he/she will be punished as described before.
"""

import glob
import logging
import signal
import time
import sys
import os

from PyQt5 import QtCore
from PyQt5 import QtWidgets

from . import utilities
from . import boot_up
from .gui.PreferencesDialog import PreferencesDialog
from .GUI_classes import GUI_classes
from .VisaConnectWizard import VisaConnectWizard
from .measurement_event_loop import (
    measurement_event_loop,
    message_to_main,
    message_from_main,
    queue_to_GUI
)

def main():
    """Main application entry point."""

    # Create timestamp
    start_time = time.time()

    # Load Style sheet
    StyleSheet = utilities.load_QtCSS_StyleSheet("Qt_Style.css")

    # Create app
    app = QtWidgets.QApplication(sys.argv)

    # Create application settings.
    app.setOrganizationName("HEPHY")
    app.setOrganizationDomain("hephy.at")
    app.setApplicationName("comet")

    # Init global settings.
    QtCore.QSettings()

    # Set Style of the GUI
    style = "Fusion"
    app.setStyle(QtWidgets.QStyleFactory.create(style))
    app.setStyleSheet(StyleSheet)
    app.setQuitOnLastWindowClosed(False)

    # Terminate application on SIG_INT signal.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Create a custom exception handler
    sys.excepthook = utilities.exception_handler

    # Initialize logger using configuration
    rootdir = os.path.dirname(os.path.abspath(__file__))
    config = os.path.join(rootdir, "loggerConfig.yml")
    utilities.LogFile(config)

    # Get logger
    log = logging.getLogger(__name__)
    log.info("Logfile initiated...")
    log.critical("Initializing programm:")

    # Loading all config files
    active_setup = QtCore.QSettings().value('active_setup', None)
    # TODO on missing setup do a quick and dirty selection
    # replace this by creating a pretty awesome welcome dialog ;)
    if active_setup is None:
        dialog = PreferencesDialog(None)
        dialog.exec_()
        active_setup = dialog.activeSetup() # Potential mismatch of setups if setup changes in between
        del dialog

    log.critical("Loading setup '%s'...", active_setup)
    setup_loader = boot_up.SetupLoader()
    setup_loader.load(active_setup)
    setup_loader.default_values_dict = boot_up.update_defaults_dict(setup_loader.configs["config"], setup_loader.configs["config"].get("framework_variables", {}))

    # Initializing all modules
    log.critical("Initializing modules ...")
    vcw = VisaConnectWizard()


    # Tries to connect to all available devices in the network, it returns a dict of
    # a dict. First dict contains the the device names as keys, the value is a dict
    # containing key words of settings
    log.critical("Try to connect to devices ...")
    # Connects to all devices and initiates them and returns the updated device_dict
    # with the actual visa resources
    devices_dict = boot_up.connect_to_devices(vcw, setup_loader.configs["config"]["settings"]["Devices"],
                                              setup_loader.configs.get("device_lib", {}))
    devices_dict = devices_dict.get_new_device_dict()

    log.critical("Starting the event loops ... ")
    table = utilities.table_control_class(
        setup_loader.configs["config"],
        devices_dict,
        message_to_main,
        vcw
    )
    if "Table_control" not in devices_dict:
        table = None
    switching = utilities.switching_control(
        setup_loader.configs["config"],
        devices_dict,
        message_to_main,
    )

    # Gather auxiliary modules
    aux = {"Table": table, "Switching": switching,
           "VCW": vcw, "Devices": devices_dict,
           "rootdir": rootdir, "App": app,
           "Message_from_main": message_from_main, "Message_to_main": message_to_main,
           "Queue_to_GUI": queue_to_GUI, "Configs": setup_loader.configs}

    # Starts a new Thread for the measurement event loop
    MEL = measurement_event_loop(aux)
    MEL.start()

    log.critical("Starting GUI ...")
    gui = GUI_classes(aux)
    # Init the framework for update plots etc.
    frame = utilities.Framework(gui.give_framework_functions)
    # Starts the timer
    frame.start_timer()

    log.critical("Start rendering GUI...")
    gui.app.exec_() # Starts the actual event loop for the GUI
    end_time = time.time()

    log.critical("Run time: %s seconds.", round(end_time-start_time, 2))
    log.critical("Reset all devices...")

    # Reset all devices
    utilities.reset_devices(devices_dict, vcw)

    log.critical("Close visa connections...")
    vcw.close_connections()
    log.critical("Exiting Main Thread")
    sys.exit(0)

if __name__ == '__main__':
    main()
