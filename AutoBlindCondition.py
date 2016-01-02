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
from . import AutoBlindValue
from . import AutoBlindEval


# Class representing a single condition
class AbCondition(AutoBlindTools.AbItemChild):
    # Name of condition
    @property
    def name(self):
        return self.__name

    # Error in condition
    @property
    def error(self):
        return self.__error

    # Initialize the condition
    # abitem: parent AbItem instance
    # name: Name of condition
    def __init__(self, abitem, name: str):
        super().__init__(abitem)
        self.__name = name
        self.__item = None
        self.__eval = None
        self.__value = AutoBlindValue.AbValue(self._abitem, "value", True)
        self.__min = AutoBlindValue.AbValue(self._abitem, "min")
        self.__max = AutoBlindValue.AbValue(self._abitem, "max")
        self.__negate = False
        self.__agemin = AutoBlindValue.AbValue(self._abitem, "agemin")
        self.__agemax = AutoBlindValue.AbValue(self._abitem, "agemax")
        self.__agenegate = None
        self.__error = None

    # set a certain function to a given value
    # func: Function to set ('item', 'eval', 'value', 'min', 'max', 'negate', 'agemin', 'agemax' or 'agenegate'
    # value: Value for function
    def set(self, func, value):
        if func == "as_item":
            self.__item = self._abitem.return_item(value)
        elif func == "as_eval":
            self.__eval = value
        if func == "as_value":
            self.__value.set(value, self.__name)
        elif func == "as_min":
            self.__min.set(value, self.__name)
        elif func == "as_max":
            self.__max.set(value, self.__name)
        elif func == "as_agemin":
            self.__agemin.set(value, self.__name)
        elif func == "as_agemax":
            self.__agemax.set(value, self.__name)
        elif func == "as_negate":
            self.__negate = value
        elif func == "as_agenegate":
            self.__agenegate = value

    # Complete condition (do some checks, cast value, min and max based on item or eval data types)
    # item_state: item to read from
    # abitem_object: Related AbItem instance for later determination of current age and current delay
    def complete(self, item_state):
        # check if it is possible to complete this condition
        if self.__min.is_empty() and self.__max.is_empty() and self.__value.is_empty() \
                and self.__agemin.is_empty() and self.__agemax.is_empty():
            return False

        # set 'eval' for some known conditions if item and eval are not set, yet
        if self.__item is None and self.__eval is None:
            if self.__name == "weekday":
                self.__eval = AutoBlindCurrent.values.get_weekday
            elif self.__name == "sun_azimut":
                self.__eval = AutoBlindCurrent.values.get_sun_azimut
            elif self.__name == "sun_altitude":
                self.__eval = AutoBlindCurrent.values.get_sun_altitude
            elif self.__name == "age":
                self.__eval = self._abitem.get_age
            elif self.__name == "delay":
                self.__eval = self._abitem.get_delay
            elif self.__name == "time":
                self.__eval = AutoBlindCurrent.values.get_time
            elif self.__name == "random":
                self.__eval = AutoBlindCurrent.values.get_random
            elif self.__name == "month":
                self.__eval = AutoBlindCurrent.values.get_month
            elif self.__name == "laststate":
                self.__eval = self._abitem.get_laststate_id
            elif self.__name == "trigger_item":
                self.__eval = self._abitem.get_update_trigger_item
            elif self.__name == "trigger_caller":
                self.__eval = self._abitem.get_update_trigger_caller
            elif self.__name == "trigger_source":
                self.__eval = self._abitem.get_update_trigger_source
            elif self.__name == "trigger_dest":
                self.__eval = self._abitem.get_update_trigger_dest
            elif self.__name == "original_item":
                self.__eval = self._abitem.get_update_original_item
            elif self.__name == "original_caller":
                self.__eval = self._abitem.get_update_original_caller
            elif self.__name == "original_source":
                self.__eval = self._abitem.get_update_original_source

        # missing item in condition: Try to find it
        if self.__item is None:
            result = AutoBlindTools.find_attribute(self._sh, item_state, "as_item_" + self.__name)
            if result is not None:
                self.__item = self._abitem.return_item(result)

        # missing eval in condition: Try to find it
        if self.__eval is None:
            result = AutoBlindTools.find_attribute(self._sh, item_state, "as_eval_" + self.__name)
            if result is not None:
                self.__eval = result

        # no we should have either 'item' or 'eval' set. If not ... very bad ....
        if self.__item is None and self.__eval is None:
            self.__error = "Condition {}: Neither 'item' nor 'eval' given!".format(self.__name)
            raise ValueError(self.__error)

        # cast stuff
        try:
            if self.__item is not None:
                self.__cast_all(self.__item.cast)
            elif self.__name in ("weekday", "sun_azimut", "sun_altitude", "age", "delay", "random", "month"):
                self.__cast_all(AutoBlindTools.cast_num)
            elif self.__name in (
                    "laststate", "trigger_item", "trigger_caller", "trigger_source", "trigger_dest", "original_item",
                    "original_caller", "original_source"):
                self.__cast_all(AutoBlindTools.cast_str)
            elif self.__name == "time":
                self.__cast_all(AutoBlindTools.cast_time)
        except Exception as ex:
            self.__error = str(ex)
            raise ValueError(self.__error)

        # 'min' must not be greater than 'max'
        if self.__min.get_type() == "value" and self.__max.get_type() == "value":
            if self.__min.get() > self.__max.get():
                self.__error = "Condition {}: 'min' must not be greater than 'max'!".format(self.__name)
                raise ValueError(self.__error)

        # 'agemin' and 'agemax' can only be used for items, not for eval
        if self.__item is None and not (self.__agemin.is_empty() and self.__agemax.is_empty()):
            self.__error = "Condition {}: 'agemin'/'agemax' can not be used for eval!".format(self.__name)
            raise ValueError(self.__error)

        return True

    # Check if condition is matching
    def check(self):
        # Ignore if errors occured during preparing
        if self.__error is not None:
            self._log_info("condition'{0}': Ignoring because of error: {1}", self.__name, self.__error)
            return True

        # Ignore if no current value can be determined (should not happen as we check this earlier, but to be sure ...)
        if self.__item is None and self.__eval is None:
            self._log_info("condition '{0}': No item or eval found! Considering condition as matching!", self.__name)
            return True

        if not self.__check_value():
            return False
        if not self.__check_age():
            return False
        return True

    # Write condition to logger
    def write_to_logger(self):
        if self.__error is not None:
            self._log_debug("error: {0}", self.__error)
        if self.__item is not None:
            self._log_debug("item: {0}", self.__item.id())
        if self.__eval is not None:
            self._log_debug("eval: {0}", AutoBlindTools.get_eval_name(self.__eval))
        self.__value.write_to_logger()
        self.__min.write_to_logger()
        self.__max.write_to_logger()
        if self.__negate is not None:
            self._log_debug("negate: {0}", self.__negate)
        self.__agemin.write_to_logger()
        self.__agemax.write_to_logger()
        if self.__agenegate is not None:
            self._log_debug("age negate: {0}", self.__agenegate)

    # Cast 'value', 'min' and 'max' using given cast function
    # cast_func: cast function to use
    def __cast_all(self, cast_func):
        self.__value.set_cast(cast_func)
        self.__min.set_cast(cast_func)
        self.__max.set_cast(cast_func)
        if self.__negate is not None:
            self.__negate = AutoBlindTools.cast_bool(self.__negate)
        self.__agemin.set_cast(AutoBlindTools.cast_num)
        self.__agemax.set_cast(AutoBlindTools.cast_num)
        if self.__agenegate is not None:
            self.__agenegate = AutoBlindTools.cast_bool(self.__agenegate)

    # Check if value conditions match
    def __check_value(self):
        current = self.__get_current()
        try:
            if not self.__value.is_empty():
                # 'value' is given. We ignore 'min' and 'max' and check only for the given value
                value = self.__value.get()

                if type(value) == list:
                    self._log_debug("Condition '{0}': value={1} negate={2} current={3}", self.__name, value,
                                    self.__negate,
                                    current)
                    self._log_increase_indent()

                    for element in value:
                        if type(element) != type(current):
                            element = str(element)
                            current = str(current)
                        if self.__negate:
                            if current == element:
                                self._log_debug("{0} found but negated -> not matching".format(element))
                                return False
                        else:
                            if current == element:
                                self._log_debug("{0} found -> matching".format(element))
                                return True

                    if self.__negate:
                        self._log_debug("{0} not in list -> matching".format(current))
                        return True
                    else:
                        self._log_debug("{0} not in list -> not matching".format(current))
                        return False

                else:
                    # If current and value have different types, convert both to string
                    if type(value) != type(current):
                        value = str(value)
                        current = str(current)

                    self._log_debug("Condition '{0}': value={1} negate={2} current={3}", self.__name, value,
                                    self.__negate,
                                    current)
                    self._log_increase_indent()

                    if self.__negate:
                        if current != value:
                            self._log_debug("not OK but negated -> matching")
                            return True
                    else:
                        if current == value:
                            self._log_debug("OK -> matching")
                            return True

                    self._log_debug("not OK -> not matching")
                    return False

            else:

                min_value = self.__min.get()
                max_value = self.__max.get()

                # 'value' is not given. We check 'min' and 'max' (if given)
                self._log_debug("Condition '{0}': min={1} max={2} negate={3} current={4}", self.__name, min_value,
                                max_value, self.__negate, current)
                self._log_increase_indent()

                if min_value is None and max_value is None:
                    self._log_debug("no limit given -> matching")
                    return True

                if not self.__negate:
                    if min_value is not None and current < min_value:
                        self._log_debug("to low -> not matching")
                        return False

                    if max_value is not None and current > max_value:
                        self._log_debug("to high -> not matching")
                        return False
                else:
                    if min_value is not None and current > min_value and (max_value is None or current < max_value):
                        self._log_debug("not lower than min -> not matching")
                        return False

                    if max_value is not None and current < max_value and (min_value is None or current > min_value):
                        self._log_debug("not higher than max -> not matching")
                        return False

                self._log_debug("given limits ok -> matching")
                return True
        finally:
            self._log_decrease_indent()

    # Check if age conditions match
    def __check_age(self):
        # No limits given -> OK
        if self.__agemin.is_empty() and self.__agemax.is_empty():
            self._log_info("Age of '{0}': No limits given", self.__name)
            return True

        # Ignore if no current value can be determined (should not happen as we check this earlier, but to be sure ...)
        if self.__item is None:
            self._log_info("Age of '{0}': No item found! Considering condition as matching!", self.__name)
            return True

        current = self.__item.age()
        agemin = None if self.__agemin.is_empty() else self.__agemin.get()
        agemax = None if self.__agemax.is_empty() else self.__agemax.get()
        try:
            # We check 'min' and 'max' (if given)
            self._log_debug("Age of '{0}': min={1} max={2} negate={3} current={4}", self.__name, agemin, agemax,
                            self.__agenegate, current)
            self._log_increase_indent()

            if not self.__agenegate:
                if agemin is not None and current < agemin:
                    self._log_debug("to young -> not matching")
                    return False

                if agemax is not None and current > agemax:
                    self._log_debug("to old -> not matching")
                    return False
            else:
                if agemin is not None and current > agemin and (agemax is None or current < agemax):
                    self._log_debug("not younger than min -> not matching")
                    return False

                if agemax is not None and current < agemax and (agemin is None or current > agemin):
                    self._log_debug("not older than max -> not matching")
                    return False

            self._log_debug("given age limits ok -> matching")
            return True
        finally:
            self._log_decrease_indent()

    # Current value of condition (based on item or eval)
    def __get_current(self):
        if self.__item is not None:
            # noinspection PyCallingNonCallable
            return self.__item()
        if self.__eval is not None:
            if isinstance(self.__eval, str):
                # noinspection PyUnusedLocal
                sh = self._sh
                if self.__eval.startswith("autoblind_eval"):
                    # noinspection PyUnusedLocal
                    autoblind_eval = AutoBlindEval.AbEval(self._abitem)
                try:
                    value = eval(self.__eval)
                except Exception as e:
                    raise ValueError("Condition {}: problem evaluating {}: {}".format(self.__name, str(self.__eval), e))
                else:
                    return value
            else:
                # noinspection PyCallingNonCallable
                return self.__eval()
        raise ValueError("Condition {}: Neither 'item' nor eval given!".format(self.__name))
