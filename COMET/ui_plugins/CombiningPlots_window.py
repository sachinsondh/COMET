
from PyQt5.QtWidgets import QWidget, QFileDialog, QTreeWidgetItem
from PyQt5.QtCore import QUrl, Qt
from PyQt5 import QtGui
from PyQt5 import QtCore
import threading
import ast
import re
from ..utilities import save_dict_as_hdf5, save_dict_as_json, save_dict_as_xml

import yaml
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

from ..misc_plugins.PlotScripts.myplot import *

class CombiningPlots_window:

    def __init__(self, GUI, layout):

        self.variables = GUI
        self.layout = layout
        self.log = logging.getLogger(__name__)
        self.plotting_sessions = None
        self.allFiles = []
        self.plot_path = {} # The plot hierachy inside the "all" entry of the plotObject
        self.plot_analysis = {} # The analysis each individual plot comes from
        self.selected_plot_option = ()
        self.current_plot_object = None
        self.plotting_thread = None

        # Device communication widget
        self.VisWidget = QWidget()
        self.widget = self.variables.load_QtUi_file("CombinePlots.ui",  self.VisWidget)
        self.layout.addWidget(self.VisWidget)

        # Config
        self.config_save_options()

        # Connect buttons
        #self.widget.files_toolButton.clicked.connect(self.select_files_action)
        #self.widget.select_template_toolButton.clicked.connect(self.select_analysis_template)
        #self.widget.upload_pushButton.clicked.connect(self.upload_to_DB)
        self.widget.save_toolButton.clicked.connect(self.select_save_to_action)
        self.widget.refresh_pushButton.clicked.connect(self.refresh_action)
        #self.widget.render_pushButton.clicked.connect(self.render_action)
        #self.widget.output_tree.itemClicked.connect(self.load_html_to_screen)
        #self.widget.plot_options_treeWidget.itemClicked.connect(self.tree_option_select_action)
        #self.widget.save_as_pushButton.clicked.connect(self.save_as_action)
        #self.widget.apply_option_pushButton.clicked.connect(self.apply_option_button)

    def refresh_action(self):
        """Refreshes the possible runs with plots"""
        try:
            self.plotting_sessions = self.variables.all_plugin_modules["DataVisualization_window"].plotting_sessions
            self.widget.files_comboBox.addItems(self.plotting_sessions.keys())
            self.update_plt_tree(self.plotting_sessions(self.widget.files_comboBox.currentText()))
        except Exception as err:
            self.log.error("Could not load any plot sessions. It seems the plotting Tab is not rendered, or the plotting output is corrupted. Error: {}".format(err))

    def load_html_to_screen(self, item):
        """Loads a html file plot to the screen"""
        self.variables.app.setOverrideCursor(Qt.WaitCursor)
        try:
            for analy in self.plotting_Object.plotObjects:
                if self.plot_analysis[item.text(0)] == analy["Name"]:
                    plot = analy["All"]
                    for path_part in self.plot_path[item.text(0)]:
                        plot = getattr(plot, path_part)
                    filepath = self.plotting_Object.temp_html_output(plot)
                    self.widget.webEngineView.load(QUrl.fromLocalFile(filepath))
                    self.current_plot_object = plot
                    self.update_plot_options_tree(plot)
                    break
        except Exception as err:
            self.log.error("Plot could not be loaded. If this issue is not resolvable, re-render the plots! Error: {}".format(err))
        self.variables.app.restoreOverrideCursor()

    def replot_and_reload_html(self, plot):
        """Replots a plot and displays it"""
        filepath = self.plotting_Object.temp_html_output(plot)
        self.widget.webEngineView.load(QUrl.fromLocalFile(filepath))

    def select_save_to_action(self):
        """Lets you select the output folder"""
        fileDialog = QFileDialog()
        dirr = fileDialog.getExistingDirectory()
        self.widget.save_lineEdit.setText(dirr)


    def render_action(self):
        """Stats the plotting scripts"""
        # Sets the cursor to wait
        self.variables.app.restoreOverrideCursor()
        self.variables.app.setOverrideCursor(Qt.WaitCursor)
        os.mkdir(os.path.join(os.getcwd(), "COMET", "temp")) if not os.path.exists(os.path.join(os.getcwd(), "COMET", "temp")) else True

        # Find template and load the yaml file
        plotConfigs = self.variables.framework_variables["Configs"]["additional_files"].get("Plotting", {})
        if not "data" in plotConfigs[(self.widget.templates_comboBox.currentText())]:
            template = plotConfigs[(self.widget.templates_comboBox.currentText())]["raw"]
            template = self.parse_yaml_string(template)
            plotConfigs[(self.widget.templates_comboBox.currentText())]["data"] = template
        else:
            template = plotConfigs[(self.widget.templates_comboBox.currentText())]["data"]

        # Add the parameters
        template["Files"] = [self.widget.files_comboBox.itemText(i) for i in range(self.widget.files_comboBox.count())]
        template["Output"] = self.widget.save_lineEdit.text()

        # Dump the yaml file in the output directory
        filepath = os.path.normpath(os.path.join(os.getcwd(), "COMET", "temp", "{}.yml".format("tempCONFIG")))
        with open(filepath, 'w') as outfile:
            yaml.dump(template, outfile, default_flow_style=False)

        args = ["--config", "{}".format(filepath), "--show"]
        plotting = PlottingMain(configs=args)
        try:
            plotting.run()
            self.update_plt_tree(plotting)
            # Store current session
            self.plotting_Object = plotting
        except Exception as err:
            self.log.error("An error happened during plotting with error {}".format(err))
            # Try to extract data until crash (this is just wishfull thinking, in most cases this will fail)
            try:
                self.update_plt_tree(plotting)
                # Store current session
                self.plotting_Object = plotting
            except:
                pass
            # Restore Cursor
            self.variables.app.restoreOverrideCursor()
            raise
        # Restore Cursor
        self.variables.app.restoreOverrideCursor()


    def tree_option_select_action(self, item):
        """Action what happens when an option is selected"""
        key = item.text(0)
        value = item.text(1)
        self.widget.options_lineEdit.setText("{}: {}".format(key, value))

    def update_plt_tree(self, plotting_output):
        """Updates the plot tree"""
        # Delete all values from the combo box
        self.widget.output_tree.clear()
        self.widget.plot_options_treeWidget.clear()
        self.widget.options_lineEdit.setText("")
        self.selected_plot_option = ()
        self.current_plot_object = None

        for analy in plotting_output.plotObjects:
            Allplots = analy.get("All", {})

            # Plot the inindividual plots/subplots
            if isinstance(Allplots,hv.core.layout.Layout):
                try:
                    for path in Allplots.keys():
                        tree = QTreeWidgetItem(["_".join(path)])
                        self.plot_path["_".join(path)] = path
                        self.plot_analysis["_".join(path)] = analy.get("Name", "")
                        self.widget.output_tree.addTopLevelItem(tree)
                except AttributeError as err:
                    self.log.warning("Attribute error happened during plot object access. Error: {}. "
                                     "Tyring to adapt...".format(err))
                    tree = QTreeWidgetItem([Allplots._group_param_value])
                    self.widget.output_tree.addTopLevelItem(tree)
                    self.plot_path[Allplots._group_param_value] = ()
                    self.plot_analysis[Allplots._group_param_value] = analy["Name"]
                except Exception as err:
                    self.log.error("An error happened during plot object access. Error: {}".format(err))
            else:
                try:
                    tree = QTreeWidgetItem(["Plot"])
                    self.plot_path["Plot"] = ()
                    self.plot_analysis["Plot"] = analy.get("Name", "")
                    self.widget.output_tree.addTopLevelItem(tree)
                except Exception as err:
                    self.log.error("An error happened during plot object access. Error: {}".format(err))

    def config_save_options(self):
        """Configs the save options like json,hdf5,etc"""
        options = ["html/png", "html", "png"]
        self.widget.save_as_comboBox.addItems(options)

    def config_selectable_templates(self):
        """Configs the combo box for selectable analysis templates"""
        self.widget.templates_comboBox.clear()
        plotConfigs = self.variables.framework_variables["Configs"]["additional_files"].get("Plotting", {})
        self.widget.templates_comboBox.addItems(plotConfigs.keys())

    def save_as_action(self):
        """Saves the plots etc to the defined directory"""

        # Sets the cursor to wait
        self.variables.app.setOverrideCursor(Qt.WaitCursor)

        if self.not_saving:
            # Check if valid dir was given
            directory = self.widget.save_lineEdit.text()
            if os.path.exists(directory) and self.plotting_Object:

                # Save the config.yml file
                self.log.info("Saving config file...")
                self.save_config_yaml(self.plotting_Object.config, os.path.join(os.path.normpath(directory), "CONFIG.yml"))

                # Get save option
                options = self.widget.save_as_comboBox.currentText().split("/")

                plotters = ["html", "png", "svg"]
                data = ["json", "hdf5", "xml"]

                # Start data saver
                for ty in data:
                    if ty in options:
                        self.save_data(ty, directory, os.path.basename(directory))

                # Start renderer
                if self.plotting_Object.config:
                    self.plotting_Object.config["Save_as"] = []
                    self.plotting_Object.config["Output"] = directory
                    for plot in plotters:
                        if plot in options:
                            self.plotting_Object.config["Save_as"].append(plot)
                    if not self.plotting_thread:
                        self.plotting_thread = threading.Thread(target=self.plotting_Object.save_to, args=(
                            self.variables.framework_variables["Message_to_main"],))
                        self.not_saving = True
                    else:
                        if self.plotting_thread.isAlive():
                            self.not_saving = False
                        else:
                            self.plotting_thread = threading.Thread(target=self.plotting_Object.save_to, args=(
                            self.variables.framework_variables["Message_to_main"],))
                            self.not_saving = True
                    #self.plotting_Object.save_to(progress_queue=self.variables.framework_variables["Queue_to_GUI"]) # Starts the routine
                    if self.not_saving:
                        self.plotting_thread.start()
                    else:
                        self.log.error("Saving of plots is currently ongoing, please wait until saving is complete!")
            else:
                self.log.error("Either the path {} does not exist, or you must first render a few plots".format(directory))

        # Restore Cursor
        self.variables.app.restoreOverrideCursor()