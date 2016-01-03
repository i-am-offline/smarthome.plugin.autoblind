#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2014-2016 Thomas Ernst                       offline@gmx.net
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
import logging

logger = logging.getLogger()


class AbFunctions:
    def __init__(self, smarthome):
        self.__sh = smarthome

    # return new item value for "manual" item
    # item_id: Id of "manual" item
    # caller: Caller that triggered the update
    # source: Source that triggered the update
    # The Method will determine the original caller/source and then check if this original caller/source is not
    # contained in as_manual_exclude list (if given) and is contained in as_manual_include list (if given).
    # If the original caller/source should be consiedered, the method returns the inverted value of the item.
    # Otherwise, the method returns the current value of the item, so that no change will be made
    def manual_item_update_eval(self, item_id, caller=None, source=None):
        item = self.__sh.return_item(item_id)
        original_caller, original_source = AutoBlindTools.get_original_caller(self.__sh, caller, source)

        retval_no_trigger = item()
        retval_trigger = not item()

        if "as_manual_exclude" in item.conf:
            # get list of exclude entries
            exclude = item.conf["as_manual_exclude"]
            if isinstance(exclude, str):
                exclude = [exclude, ]
            elif not isinstance(exclude, list):
                logger.error("Item '{0}', Attribute 'as_manual_exclude': Value must be a string or a list!")
                return retval_no_trigger

            # If current value is in list -> Return "NoTrigger"
            for entry in exclude:
                entry_caller, __, entry_source = entry.partition(":")
                if (entry_caller == original_caller or entry_caller == "*") and (
                        entry_source == original_source or entry_source == "*"):
                    return retval_no_trigger

        if "as_manual_include" in item.conf:
            # get list of include entries
            include = item.conf["as_manual_include"]
            if isinstance(include, str):
                include = [include, ]
            elif not isinstance(include, list):
                logger.error("Item '{0}', Attribute 'as_manual_include': Value must be a string or a list!")
                return retval_no_trigger

            # If current value is in list -> Return "Trigger"
            for entry in include:
                entry_caller, __, entry_source = entry.partition(":")
                if (entry_caller == original_caller or entry_caller == "*") and (
                        entry_source == original_source or entry_source == "*"):
                    return retval_trigger

            # Current value not in list -> Return "No Trigger
            return retval_no_trigger
        else:
            # No include-entries -> return "Trigger"
            return retval_trigger