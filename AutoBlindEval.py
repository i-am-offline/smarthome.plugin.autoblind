#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2014-2015 Thomas Ernst                       offline@gmx.net
#########################################################################
#  This file is part of SmartHome.py.
#
#  SmartHome.py is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHome.py is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHome.py. If not, see <http://www.gnu.org/licenses/>.
#########################################################################
from . import AutoBlindTools
from . import AutoBlindCurrent
from random import randint
import subprocess
import datetime


class AbEval(AutoBlindTools.AbItemChild):
    # Initialize
    # abitem: parent AbItem instance
    def __init__(self, abitem):
        super().__init__(abitem)

    # Get lamella angle based on sun_altitute for sun tracking
    def sun_tracking(self):
        self._log_debug("Executing method 'SunTracking'")
        self._log_increase_indent()

        altitude = AutoBlindCurrent.values.get_sun_altitude()
        self._log_debug("Current sun altitude is {0}°", altitude)

        value = 90 - altitude
        self._log_debug("Blinds at right angle to the sun at {0}°", value)

        self._log_decrease_indent()
        return value

    # Return random integer
    # min_value: minimum value for random integer (default 0)
    # max_value: maximum value for random integer (default 255)
    def get_random_int(self, min_value=0, max_value=255):
        self._log_debug("Executing method 'GetRandomInt({0},{1}'", min_value, max_value)
        return randint(min_value, max_value)

    # Execute a command
    # command: command to execute
    def execute(self, command):
        try:
            return subprocess.call(command, shell=True)
        except Exception as ex:
            self._log_exception(ex)

    # Return a variable
    # varname: name of variable to return
    def get_variable(self, varname):
        try:
            return self._abitem.get_variable(varname)
        except Exception as ex:
            self._log_exception(ex)

    # Return an item based on the main autoblind item
    # subitem_id: Id of subitem to return
    # parent_level: number of levels above main autoblind item to start
    def get_item(self, subitem_id, parent_level=0):
        try:
            levels = self._abitem.id.split(".")
            use_num_levels = len(levels) - parent_level
            if use_num_levels < 0:
                raise ValueError(
                    "parent_level {2} ist zu groß. Das Item '{0}' hat nur {1} Elemente".format(self._abitem.id,
                                                                                               len(levels),
                                                                                               parent_level))
            result = ""
            for level in levels[0:use_num_levels]:
                result += level + "."
            result += subitem_id
            if self._abitem.sh.return_item(result) is None:
                raise ValueError("Determined item '{0}' does not exist.".format(result))
            return result
        except Exception as ex:
            self._log_exception(ex)

    # Insert end time of suspension into text
    # suspend_item_id: Item whose age is used to determine how much of the suspend time is already over
    # suspend_text: Text to insert end time of suspension into. Use strftime/strptime format codes for the end time
    #               (see https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior)
    def insert_suspend_time(self, suspend_item_id, suspend_text="Ausgesetzt bis %X"):
        try:
            suspend_time = self._abitem.get_variable("item.suspend_time")
            suspend_item = self._abitem.sh.return_item(suspend_item_id)
            if suspend_item is None:
                text = "Eval-Method 'insert_suspend_time': Suspend Item {0} not found!"
                raise ValueError(text.format(suspend_item_id))
            suspend_over = suspend_item.age()
            suspend_remaining = suspend_time - suspend_over
            if suspend_remaining < 0:
                raise ValueError("Eval-Method 'insert_suspend_time': Suspend should alredy be finished!")
            suspend_until = self._abitem.sh.now() + datetime.timedelta(seconds=suspend_remaining)
            return suspend_until.strftime(suspend_text)
        except Exception as ex:
            self._log_exception(ex)
            return "(Error while determining text. Check log)"
