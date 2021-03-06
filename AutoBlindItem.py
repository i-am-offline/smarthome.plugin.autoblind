#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2014-     Thomas Ernst                       offline@gmx.net
#########################################################################
#  Finite state machine plugin for SmartHomeNG
#
#  This plugin is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This plugin is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this plugin. If not, see <http://www.gnu.org/licenses/>.
#########################################################################
import time
import datetime
from . import AutoBlindTools
from .AutoBlindLogger import AbLogger
from . import AutoBlindState
from . import AutoBlindDefaults
from . import AutoBlindCurrent
from . import AutoBlindValue


# Class representing a blind item
# noinspection PyCallingNonCallable
class AbItem:
    # return item id
    @property
    def id(self):
        return self.__id

    # return instance of smarthome.py class
    @property
    def sh(self):
        return self.__sh

    # return instance of logger class
    @property
    def logger(self):
        return self.__logger

    # Constructor
    # smarthome: instance of smarthome.py
    # item: item to use
    def __init__(self, smarthome, item):
        self.__sh = smarthome
        self.__item = item
        self.__id = self.__item.id()
        self.__name = str(self.__item)
        # initialize logging
        self.__logger = AbLogger.create(self.__item)
        self.__logger.header("Initialize Item {0}".format(self.id))

        # get startup delay
        self.__startup_delay = AutoBlindValue.AbValue(self, "Startup Delay", False, "num")
        self.__startup_delay.set_from_attr(self.__item, "as_startup_delay", AutoBlindDefaults.startup_delay)
        self.__startup_delay_over = False

        # Init lock settings
        self.__item_lock = self.return_item_by_attribute("as_lock_item")
        if self.__item_lock is not None:
            self.__logger.warning("AUTOBLIND WARNING: Item {0}: Usage of 'as_log_item' is obsolete. Functionality will be removed in the future!", self.__id)

        # Init suspend settings
        self.__suspend_item = self.return_item_by_attribute("as_suspend_item")
        if self.__suspend_item is not None:
            self.__logger.warning("AUTOBLIND WARNING: Item {0}: Usage of 'as_suspend_item' is obsolete. Functionality will be removed in the future!", self.__id)
        self.__suspend_until = None
        self.__suspend_watch_items = []
        if "as_suspend_watch" in self.__item.conf:
            self.__logger.warning("AUTOBLIND WARNING: Item {0}: Usage of 'as_suspend_watch' is obsolete. Functionality will be removed in the future!", self.__id)
            suspend_on = self.__item.conf["as_suspend_watch"]
            if isinstance(suspend_on, str):
                suspend_on = [suspend_on]
            for entry in suspend_on:
                for item in self.__sh.match_items(entry):
                    self.__suspend_watch_items.append(item)
        self.__suspend_time = AutoBlindValue.AbValue(self, "Suspension time on manual changes", False, "num")
        self.__suspend_time.set_from_attr(self.__item, "as_suspend_time", AutoBlindDefaults.suspend_time)

        # Init laststate items/values
        self.__laststate_item_id = self.return_item_by_attribute("as_laststate_item_id")
        self.__laststate_internal_id = "" if self.__laststate_item_id is None else self.__laststate_item_id()
        self.__laststate_item_name = self.return_item_by_attribute("as_laststate_item_name")
        self.__laststate_internal_name = "" if self.__laststate_item_name is None else self.__laststate_item_name()

        self.__states = []
        self.__delay = 0
        self.__can_not_leave_current_state_since = 0
        self.__repeat_actions = AutoBlindValue.AbValue(self, "Repeat actions if state is not changed", False, "bool")
        self.__repeat_actions.set_from_attr(self.__item, "as_repeat_actions", True)

        self.__update_trigger_item = None
        self.__update_trigger_caller = None
        self.__update_trigger_source = None
        self.__update_trigger_dest = None
        self.__update_in_progress = False
        self.__update_original_item = None
        self.__update_original_caller = None
        self.__update_original_source = None

        # Check item configuration
        self.__check_item_config()

        # Init variables
        self.__variables = {
            "item.suspend_time": self.__suspend_time.get(),
            "item.suspend_remaining": 0,
            "current.state_id": "",
            "current.state_name": ""
        }

        # initialize states
        for item_state in self.__item.return_children():
            try:
                self.__states.append(AutoBlindState.AbState(self, item_state))
            except ValueError as ex:
                self.__logger.error("Ignoring state {0} because:  {1}".format(item_state.id(), str(ex)))

        if len(self.__states) == 0:
            raise ValueError("{0}: No states defined!".format(self.id))

        # Write settings to log
        self.__write_to_log()

        # start timer with startup-delay
        startup_delay = 0 if self.__startup_delay.is_empty() else self.__startup_delay.get()
        if startup_delay > 0:
            first_run = self.__sh.now() + datetime.timedelta(seconds=startup_delay)
            scheduler_name = self.__id + "-Startup Delay"
            value = {"item": self.__item, "caller": "Init"}
            self.__sh.scheduler.add(scheduler_name, self.__startup_delay_callback, value=value, next=first_run)
        elif startup_delay == -1:
            self.__startup_delay_over = True
            self.__add_triggers()
        else:
            self.__startup_delay_callback(self.__item, "Init", None, None)

    # Find the state, matching the current conditions and perform the actions of this state
    # caller: Caller that triggered the update
    # noinspection PyCallingNonCallable,PyUnusedLocal
    def update_state(self, item, caller=None, source=None, dest=None):
        if self.__update_in_progress or not self.__startup_delay_over:
            return

        self.__update_in_progress = True

        self.__logger.update_logfile()
        self.__logger.header("Update state of item {0}".format(self.__name))
        if caller:
            item_id = item.id() if item is not None else "(no item)"
            self.__logger.debug("Update triggered by {0} (item={1} source={2} dest={3})", caller, item_id, source, dest)

        # Find out what initially caused the update to trigger if the caller is "Eval"
        orig_caller, orig_source, orig_item = AutoBlindTools.get_original_caller(self.sh, caller, source, item)
        if orig_caller != caller:
            text = "Eval initially triggered by {0} (item={1} source={2})"
            self.__logger.debug(text, orig_caller, orig_item.id(), orig_source)

        if orig_caller == AutoBlindDefaults.plugin_identification or caller == AutoBlindDefaults.plugin_identification:
            self.__logger.debug("Ignoring changes from {0}", AutoBlindDefaults.plugin_identification)
            self.__update_in_progress = False
            return

        self.__update_trigger_item = item.id()
        self.__update_trigger_caller = caller
        self.__update_trigger_source = source
        self.__update_trigger_dest = dest
        self.__update_original_item = orig_item.id()
        self.__update_original_caller = orig_caller
        self.__update_original_source = orig_source

        # check if locked
        if self.__lock_is_active():
            self.__logger.info("AutoBlind is locked")
            self.__laststate_internal_name = AutoBlindDefaults.laststate_name_manually_locked
            self.__update_in_progress = False
            return

        # check if suspended
        if self.__suspend_is_active():
            # noinspection PyNoneFunctionAssignment
            active_timer_time = self.__suspend_get_time()
            text = "AutoBlind has been suspended after manual changes. Reactivating at {0}"
            self.__logger.info(text, active_timer_time)
            self.__laststate_internal_name = active_timer_time.strftime(AutoBlindDefaults.laststate_name_suspended)
            self.__update_in_progress = False
            return

        # Update current values
        AutoBlindCurrent.update()
        self.__variables["item.suspend_time"] = self.__suspend_time.get()
        self.__variables["item.suspend_remaining"] = -1

        # get last state
        last_state = self.__laststate_get()
        if last_state is not None:
            self.__logger.info("Last state: {0} ('{1}')", last_state.id, last_state.name)
        if self.__can_not_leave_current_state_since == 0:
            self.__delay = 0
        else:
            self.__delay = time.time() - self.__can_not_leave_current_state_since

        # check if current state can be left
        if last_state is not None and not self.__update_check_can_leave(last_state):
            self.__logger.info("Can not leave current state, staying at {0} ('{1}')", last_state.id, last_state.name)
            can_leave_state = False
            new_state = last_state
            if self.__can_not_leave_current_state_since == 0:
                self.__can_not_leave_current_state_since = time.time()
        else:
            can_leave_state = True
            new_state = None

        if can_leave_state:
            # find new state
            for state in self.__states:
                if self.__update_check_can_enter(state):
                    new_state = state
                    self.__can_not_leave_current_state_since = 0
                    break

            # no new state -> leave
            if new_state is None:
                if last_state is None:
                    self.__logger.info("No matching state found, no previous state available. Doing nothing.")
                else:
                    text = "No matching state found, staying at {0} ('{1}')"
                    self.__logger.info(text, last_state.id, last_state.name)
                    last_state.run_stay(self.__repeat_actions.get())
                self.__update_in_progress = False
                return
        else:
            # if current state can not be left, check if enter conditions are still valid.
            # If yes, set "can_not_leave_current_state_since" to 0
            if new_state.can_enter():
                self.__can_not_leave_current_state_since = 0

        # get data for new state
        if last_state is not None and new_state.id == last_state.id:
            self.__logger.info("Staying at {0} ('{1}')", new_state.id, new_state.name)
            new_state.run_stay(self.__repeat_actions.get())

            # New state is last state
            if self.__laststate_internal_name != new_state.name:
                self.__laststate_set(new_state)

        else:
            # New state is different from last state
            if last_state is not None:
                self.__logger.info("Leaving {0} ('{1}')", last_state.id, last_state.name)
                last_state.run_leave(self.__repeat_actions.get())

            self.__logger.info("Entering {0} ('{1}')", new_state.id, new_state.name)
            new_state.run_enter(self.__repeat_actions.get())

            self.__laststate_set(new_state)

        self.__update_in_progress = False

    # check if state can be left after setting state-specific variables
    # state: state to check
    def __update_check_can_leave(self, state):
        try:
            self.__variables["current.state_id"] = state.id
            self.__variables["current.state_name"] = state.name
            return state.can_leave()
        finally:
            self.__variables["current.state_id"] = ""
            self.__variables["current.state_name"] = ""

    # check if state can be entered after setting state-specific variables
    # state: state to check
    def __update_check_can_enter(self, state):
        try:
            self.__variables["current.state_id"] = state.id
            self.__variables["current.state_name"] = state.name
            return state.can_enter()
        finally:
            self.__variables["current.state_id"] = ""
            self.__variables["current.state_name"] = ""

    # region Laststate *************************************************************************************************
    # Set laststate
    # new_state: new state to be used as laststate
    def __laststate_set(self, new_state):
        self.__laststate_internal_id = new_state.id
        if self.__laststate_item_id is not None:
            # noinspection PyCallingNonCallable
            self.__laststate_item_id(self.__laststate_internal_id)

        self.__laststate_internal_name = new_state.text
        if self.__laststate_item_name is not None:
            # noinspection PyCallingNonCallable
            self.__laststate_item_name(self.__laststate_internal_name)

    # get last state object based on laststate_id
    # returns: AbState instance of last state or "None" if no last state could be found
    def __laststate_get(self):
        for state in self.__states:
            if state.id == self.__laststate_internal_id:
                return state
        return None

    # endregion

    # region Lock ******************************************************************************************************
    # get the value of lock item
    # returns: value of lock item
    def __lock_is_active(self):
        if self.__item_lock is not None:
            # noinspection PyCallingNonCallable
            return self.__item_lock()
        else:
            return False

    # callback function that is called when the lock item is being changed
    # noinspection PyUnusedLocal
    def __lock_callback(self, item, caller=None, source=None, dest=None):
        # we're just changing "lock" ourselves ... ignore
        if caller == "AutoBlind":
            return

        self.__logger.update_logfile()
        self.__logger.header("Item 'lock' changed")
        self.__logger.debug("'{0}' set to '{1}' by '{2}'", item.id(), item(), caller)

        # Any manual change of lock removes suspension
        if self.__suspend_is_active():
            self.__suspend_remove()

        # trigger delayed update
        self.__item.timer(1, 1)

    # endregion

    # region Suspend ***************************************************************************************************
    # suspend automatic mode for a given time
    def __suspend_set(self):
        suspend_time = self.__suspend_time.get()
        self.__logger.debug("Suspending automatic mode for {0} seconds.", suspend_time)
        self.__suspend_until = self.__sh.now() + datetime.timedelta(seconds=suspend_time)
        name = self.id + "SuspensionRemove-Timer"
        self.__sh.scheduler.add(name, self.__suspend_reactivate_callback, next=self.__suspend_until)
        self.__variables["item.suspend_time"] = suspend_time

        if self.__suspend_item is not None:
            self.__suspend_item(True, caller="AutoBlind")

        # trigger delayed update
        self.__item.timer(1, 1)

    # remove suspension
    def __suspend_remove(self):
        self.__logger.debug("Removing suspension of automatic mode.")
        self.__suspend_until = None
        self.__sh.scheduler.remove(self.id + "SuspensionRemove-Timer")

        if self.__suspend_item is not None:
            self.__suspend_item(False, caller="AutoBlind")

        # trigger delayed update
        self.__item.timer(1, 1)

    # check if suspension is active
    # returns: True = automatic mode is suspended, False = automatic mode is not suspended
    def __suspend_is_active(self):
        return self.__suspend_until is not None

    # return time when timer on item "suspended" will be called. None if no timer is set
    # returns: time that has been set for the timer on item "suspended"
    def __suspend_get_time(self):
        return self.__suspend_until

    # callback function that is called when one of the items given at "watch_manual" is being changed
    # noinspection PyUnusedLocal
    def __suspend_watch_callback(self, item, caller=None, source=None, dest=None):
        self.__logger.update_logfile()
        self.__logger.header("Watch suspend triggered")
        text = "Manual operation: Change of item '{0}' by '{1}' (source='{2}', dest='{3}')"
        self.__logger.debug(text, item.id(), caller, source, dest)
        self.__logger.increase_indent()
        if caller == AutoBlindDefaults.plugin_identification:
            self.__logger.debug("Ignoring changes from {0}", AutoBlindDefaults.plugin_identification)
        elif self.__lock_is_active():
            self.__logger.debug("Automatic mode already locked")
        else:
            self.__suspend_set()
        self.__logger.decrease_indent()

    # callback function that is called when the suspend time is over
    def __suspend_reactivate_callback(self):
        self.__logger.update_logfile()
        self.__logger.header("Suspend time over")
        self.__suspend_remove()

    # endregion

    # region Helper methods ********************************************************************************************
    # add all required triggers
    def __add_triggers(self):
        # add lock trigger
        if self.__item_lock is not None:
            self.__item_lock.add_method_trigger(self.__lock_callback)

        # add triggers for suspend watch items
        for item in self.__suspend_watch_items:
            item.add_method_trigger(self.__suspend_watch_callback)

        # add item trigger
        self.__item.add_method_trigger(self.update_state)

    # Check item settings and update if required
    # noinspection PyProtectedMember
    def __check_item_config(self):
        # set "enforce updates" for item
        self.__item._enforce_updates = True

        # set "eval" for item if initial
        if self.__item._eval_trigger and self.__item._eval is None:
            self.__item._eval = "1"

        # Check scheduler settings and update if requred
        job = self.__sh.scheduler._scheduler.get(self.id)
        if job is None:
            # We do not have an scheduler job so there is nothing to check and update
            return

        changed = False

        # inject value into cycle if required
        if "cycle" in job and job["cycle"] is not None:
            cycle = list(job["cycle"].keys())[0]
            value = job["cycle"][cycle]
            if value is None:
                value = "1"
                changed = True
            new_cycle = {cycle: value}
        else:
            new_cycle = None

        # inject value into cron if required
        if "cron" in job and job["cron"] is not None:
            new_cron = {}
            for entry, value in job['cron'].items():
                if value is None:
                    value = 1
                    changed = True
                new_cron[entry] = value
        else:
            new_cron = None

        # change scheduler settings if cycle or cron have been changed
        if changed:
            self.__sh.scheduler.change(self.id, cycle=new_cycle, cron=new_cron)

    # get triggers in readable format
    def __verbose_eval_triggers(self):
        # noinspection PyProtectedMember
        if not self.__item._eval_trigger:
            return "Inactive"

        triggers = ""
        # noinspection PyProtectedMember
        for trigger in self.__item._eval_trigger:
            if triggers != "":
                triggers += ", "
            triggers += trigger
        return triggers

    # get crons and cycles in readable format
    def __verbose_crons_and_cycles(self):
        # get crons and cycles
        cycles = ""
        crons = ""

        # noinspection PyProtectedMember
        job = self.__sh.scheduler._scheduler.get(self.__item.id)
        if job is not None:
            if "cycle" in job and job["cycle"] is not None:
                cycle = list(job["cycle"].keys())[0]
                cycles = "every {0} seconds".format(cycle)

            # inject value into cron if required
            if "cron" in job and job["cron"] is not None:
                for entry in job['cron']:
                    if crons != "":
                        crons += ", "
                    crons += entry

        if cycles == "":
            cycles = "Inactive"
        if crons == "":
            crons = "Inactive"
        return crons, cycles

    # log item data
    def __write_to_log(self):
        # get crons and cycles
        crons, cycles = self.__verbose_crons_and_cycles()
        triggers = self.__verbose_eval_triggers()

        # log general config
        self.__logger.header("Configuration of item {0}".format(self.__name))
        self.__startup_delay.write_to_logger()
        self.__logger.info("Cycle: {0}", cycles)
        self.__logger.info("Cron: {0}", crons)
        self.__logger.info("Trigger: {0}".format(triggers))
        self.__repeat_actions.write_to_logger()

        # log laststate settings
        if self.__laststate_item_id is not None:
            self.__logger.info("Item 'Laststate Id': {0}", self.__laststate_item_id.id())
        if self.__laststate_item_name is not None:
            self.__logger.info("Item 'Laststate Name': {0}", self.__laststate_item_name.id())

        # log lock settings
        if self.__item_lock is not None:
            self.__logger.info("Item 'Lock': {0}", self.__item_lock.id())

        # log suspend settings
        if self.__suspend_item is not None:
            self.__logger.info("Item 'Suspend': {0}", self.__suspend_item.id())
        if len(self.__suspend_watch_items) > 0:
            self.__suspend_time.write_to_logger()
            self.__logger.info("Items causing suspension when changed:")
            self.__logger.increase_indent()
            for watch_manual_item in self.__suspend_watch_items:
                self.__logger.info("{0} ('{1}')", watch_manual_item.id(), str(watch_manual_item))
            self.__logger.decrease_indent()

        # log states
        for state in self.__states:
            state.write_to_log()

    # endregion

    # region Methods for CLI commands **********************************************************************************
    def cli_list(self, handler):
        handler.push("{0}: {1}\n".format(self.id, self.__laststate_internal_name))

    def cli_detail(self, handler):
        # get data
        crons, cycles = self.__verbose_crons_and_cycles()
        triggers = self.__verbose_eval_triggers()
        handler.push("AutoState Item {0}:\n".format(self.id))
        handler.push("\tCurrent state: {0}\n".format(self.__laststate_internal_name))
        handler.push(self.__startup_delay.get_text("\t", "\n"))
        handler.push("\tCycle: {0}\n".format(cycles))
        handler.push("\tCron: {0}\n".format(crons))
        handler.push("\tTrigger: {0}\n".format(triggers))
        handler.push(self.__repeat_actions.get_text("\t", "\n"))

    # endregion

    # region Getter methods for "special" conditions *******************************************************************
    # return age of item
    def get_age(self):
        if self.__laststate_item_id is not None:
            return self.__laststate_item_id.age()
        else:
            self.__logger.warning('No item for last state id given. Can not determine age!')
            return 0

    # return delay of item
    def get_delay(self):
        return self.__delay

    # return id of last state
    def get_laststate_id(self):
        return self.__laststate_internal_id

    # return update trigger item
    def get_update_trigger_item(self):
        return self.__update_trigger_item

    # return update trigger caller
    def get_update_trigger_caller(self):
        return self.__update_trigger_caller

    # return update trigger source
    def get_update_trigger_source(self):
        return self.__update_trigger_source

    # return update trigger dest
    def get_update_trigger_dest(self):
        return self.__update_trigger_dest

    # return update original item
    def get_update_original_item(self):
        return self.__update_original_item

    # return update original caller
    def get_update_original_caller(self):
        return self.__update_original_caller

    # return update original source
    def get_update_original_source(self):
        return self.__update_original_source

    # return value of variable
    def get_variable(self, varname):
        return self.__variables[varname] if varname in self.__variables else "(Unknown variable '{0}'!)".format(varname)

    # set value of variable
    def set_variable(self, varname, value):
        if varname not in self.__variables:
            raise ValueError("Unknown variable '{0}!".format(varname))
        self.__variables[varname] = value

    # endregion

    # callback function that is called after the startup delay
    # noinspection PyUnusedLocal
    def __startup_delay_callback(self, item, caller=None, source=None, dest=None):
        self.__startup_delay_over = True
        self.update_state(item, "Startup Delay", source, dest)
        self.__add_triggers()

    # Return an item related to the AutoBlind Object Item
    # item_id: Id of item to return
    #
    # With this function it is possible to provide items relative to the current AutoBlind object item.
    # If an item_id starts with one or more ".", the item is relative to the AutoBlind object item. One "." means
    # that the given item Id is relative to the current level of the AutoBlind object item. Every additional "."
    # removes one level of the AutoBlind object item before adding the item_id.
    # Examples (based on AutoBlind object item "my.autoblind.objectitem":
    # - item_id = "not.prefixed.with.dots" will return item "not.prefixed.with.dots"
    # - item_id = ".onedot" will return item "my.autoblind.objectitem.onedot"
    # - item_id = "..twodots" will return item "my.autoblind.twodots"
    # - item_id = "..threedots" will return item "my.threedots"
    # - item_id = "..threedots.further.down" will return item "my.threedots.further.down"
    def return_item(self, item_id: str):
        if not item_id.startswith("."):
            item = self.__sh.return_item(item_id)
            if item is None:
                raise ValueError("Item '{0}' not found!".format(item_id))
            return item

        parent_level = 0
        for c in item_id:
            if c != '.':
                break
            parent_level += 1

        levels = self.id.split(".")
        use_num_levels = len(levels) - parent_level + 1
        if use_num_levels < 0:
            text = "Item '{0}' can not be determined. Parent item '{1}' has only {2} levels!"
            raise ValueError(text.format(item_id, self.id, len(levels)))
        result = ""
        for level in levels[0:use_num_levels]:
            result += level if result == "" else "." + level
        rel_item_id = item_id[parent_level:]
        if rel_item_id != "":
            result += "." + rel_item_id
        item = self.__sh.return_item(result)
        if item is None:
            raise ValueError("Determined item '{0}' does not exist.".format(result))
        return item

    # Return an item related to the AutoBlind object item
    # attribute: Name of the attribute of the AutoBlind object item, which contains the item_id to read
    def return_item_by_attribute(self, attribute):
        if attribute not in self.__item.conf:
            return None
        return self.return_item(self.__item.conf[attribute])
