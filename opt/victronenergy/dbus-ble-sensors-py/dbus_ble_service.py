from __future__ import annotations
import logging
import sys
import os
import dbus
from dbus_settings_service import DbusSettingsService
from vedbus import VeDbusService, VeDbusItemImport, VeDbusItemExport


class DbusBleService(object):

    _BLE_SERVICENAME = 'com.victronenergy.ble'
    _INSTANCE: DbusBleService = None

    def __init__(self):
        DbusBleService._INSTANCE = self
        self._bus: dbus.Bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        self._paths: dict = {}

        # Dbus local service, if needed
        self._dbus_service: VeDbusService = None

        # List services
        dbus_iface_names = dbus.Interface(
            self._bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
            'org.freedesktop.DBus'
        ).ListNames()

        # Check and create ble service
        if self._BLE_SERVICENAME in dbus_iface_names:
            logging.critical(f"Service {self._BLE_SERVICENAME} already running, stop it and restart")
            sys.exit(1)
        else:
            logging.info(f"Creating dbus service {self._BLE_SERVICENAME} on bus {self._bus}")
            self._dbus_service = VeDbusService(self._BLE_SERVICENAME, self._bus, False)
            self._dbus_service.register()

        self.init_continuous_scanning()

    @staticmethod
    def get() -> DbusBleService:
        return DbusBleService._INSTANCE

    def _clear_path(self, path: str) -> str:
        return f"/{path.lstrip('/').rstrip('/')}"

    def get_item(self, path: str) -> VeDbusItemExport:
        return self._paths.get(self._clear_path(path), None)

    def get_value(self, path: str) -> any:
        return self.get_item(path).Get_Value()

    def set_item(self, path: str, value: any, callback=None) -> VeDbusItemExport:
        clean_path = self._clear_path(path)
        if clean_path not in self._paths or self._paths[clean_path] != value:
            logging.debug(f"Setting item {self._BLE_SERVICENAME}@{clean_path} to {value}")
            if self._dbus_service is not None:
                busitem = self._dbus_service.add_path(clean_path, value, writeable=True, onchangecallback=callback)
            else:
                busitem = VeDbusItemExport(self._bus, clean_path, value)

        self._paths[clean_path] = busitem
        return busitem

    def set_value(self, path: str, new_value: any):
        if (item := self._paths.get(path, None)) == None:
            logging.error(f"Can not set value of unexisting '{path}' to '{new_value}'")
        else:
            result = item.SetValue(new_value)
            if result != 0:
                logging.error(f"Failed to set '{path}' to '{new_value}': result={result}")

    def set_event_callback(self, path: str, callback):
        busitem = self._paths[path]._onchangecallback = callback

    def set_proxy_callback(self, item_path: str, setting_item: VeDbusItemImport, callback=None):
        def _callback(change_path, new_value):
            if change_path != item_path:
                return 0
            if new_value != setting_item.get_value():
                setting_item.set_value(new_value)
            if callback:
                callback(new_value)
            return 1
        self.set_event_callback(item_path, _callback)

    def delete_item(self, path: str):
        if (item := self._paths.get(path, None)) == None:
            logging.warning(f"Can not delete unexisting {path}")
        del item
        del self._paths[path]

    def __getitem__(self, path: str) -> any:
        return self.get_value(path)

    def __setitem__(self, path: str, new_value: any):
        self.set_value(path, new_value)

    def __delitem__(self, path: str):
        self.delete_item(path)

    def add_ble_adapter(self, name: str, mac: str):
        self.set_item(f"/Interfaces/{name}/Address", mac)

    def remove_ble_adapter(self, name: str):
        self.delete_item(f"/Interfaces/{name}/Address")

    def set_device_name(self, device_info: dict):
        custom_name = DbusSettingsService.get().get_custom_name(device_info)
        name = custom_name if custom_name else device_info['DeviceName']
        self.set_item(f"/Devices/{device_info['dev_id']}/Name", name)

    def _init_proxy_setting(self, setting_path: str, item_path: str, default_value: any, min_value: int = 0, max_value: int = 0, callback=None):
        logging.debug(
            f"Creating setting '{setting_path}' proxy to '{item_path}' with: '{default_value}' '{min_value}' '{max_value}'")
        # Get or set setting
        setting_item = DbusSettingsService.get().get_item(setting_path, default_value, min_value, max_value)

        # Init item and custom callback
        item = self.set_item(item_path, setting_item.get_value())
        self.set_proxy_callback(item_path, setting_item, callback)

        # Set settings callback
        setting_item = DbusSettingsService.get().set_proxy_callback(setting_path, item)

    def init_continuous_scanning(self):
        self._init_proxy_setting(
            '/Settings/BleSensors/ContinuousScan',
            '/ContinuousScan',
            0,
            0,
            1,
        )

    def get_continuous_scanning(self) -> bool:
        return bool(self._paths['/ContinuousScan'].local_get_value())

    def init_enabled_status(self, device_info: dict, callback):
        self._init_proxy_setting(
            f"/Settings/Devices/{device_info['dev_id']}/Enabled",
            f"/Devices/{device_info['dev_id']}/Enabled",
            0,
            0,
            1,
            callback=callback
        )

    def is_device_enabled(self, device_info: dict) -> bool:
        return bool(self._paths[f"/Devices/{device_info['dev_id']}/Enabled"].local_get_value())
