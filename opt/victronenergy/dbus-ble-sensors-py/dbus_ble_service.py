from __future__ import annotations
import logging
import sys
import os
import dbus
from dbus_settings_service import DbusSettingsService
from vedbus import VeDbusService, VeDbusItemImport, VeDbusItemExport


class DbusBleService(object):
    """
    Main service listing and enabling/disabling scan settings and device role services through the UI.
    """

    _BLE_SERVICENAME = 'com.victronenergy.ble'
    _INSTANCE: DbusBleService = None

    def __init__(self):
        DbusBleService._INSTANCE = self
        self._bus: dbus.Bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()

        # Dbus local service, if needed
        self._dbus_ble_service: VeDbusService = None

        # List services
        dbus_iface_names = dbus.Interface(
            self._bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
            'org.freedesktop.DBus'
        ).ListNames()

        # Check and create ble service
        if self._BLE_SERVICENAME in dbus_iface_names:
            logging.critical(f"Service {self._BLE_SERVICENAME} already running, stop it and restart")
            sys.exit(1)

        logging.info(f"Creating dbus service {self._BLE_SERVICENAME} on bus {self._bus}")
        self._dbus_ble_service = VeDbusService(self._BLE_SERVICENAME, self._bus, False)
        self.init_continuous_scan()
        self._dbus_ble_service.register()

        self.boolean = False

    @staticmethod
    def get() -> DbusBleService:
        return DbusBleService._INSTANCE

    @staticmethod
    def _clear_path(path: str) -> str:
        return f"/{path.lstrip('/').rstrip('/')}"

    def _get_item(self, path: str) -> VeDbusItemExport:
        return self._dbus_ble_service._dbusobjects.get(self._clear_path(path), None)

    def _get_value(self, path: str) -> any:
        if (item := self._get_item(path)):
            return item.local_get_value()
        return None

    def _set_value(self, path: str, value: any):
        clean_path = self._clear_path(path)
        with self._dbus_ble_service as service:
            if clean_path not in service:
                logging.debug(f"Creating item {self._BLE_SERVICENAME}@{clean_path} to '{value}'")
                service.add_path(clean_path, value, writeable=True)
            elif service[clean_path] != value:
                logging.debug(f"Updating item {self._BLE_SERVICENAME}@{clean_path} to '{value}'")
                service[clean_path] = value

    def _delete_item(self, path: str):
        clean_path = self._clear_path(path)
        if self._dbus_ble_service._dbusobjects.get(clean_path, None) is None:
            logging.error(f"Can not delete unexisting {clean_path}")
        else:
            logging.debug(f"Deleting item {self._BLE_SERVICENAME}@{clean_path}")
            with self._dbus_ble_service as service:
                del service[clean_path]

    def __getitem__(self, path: str) -> any:
        return self._get_value(path)

    def __setitem__(self, path: str, new_value: any):
        self._set_value(path, new_value)

    def __delitem__(self, path: str):
        self._delete_item(path)

    def set_proxy_callback(self, item_path: str, setting_item: VeDbusItemImport, callback=None):
        def _callback(change_path, new_value):
            if change_path != item_path:
                return 0
            if new_value != setting_item.get_value():
                setting_item.set_value(new_value)
            if callback:
                callback(new_value)
            return 1
        self._dbus_ble_service._dbusobjects[item_path]._onchangecallback = _callback

    def _init_proxy_setting(self, setting_path: str, item_path: str, default_value: any, min_value: int = 0, max_value: int = 0, callback=None):
        logging.debug(
            f"Creating setting '{setting_path}' proxy to '{item_path}' with: '{default_value}' '{min_value}' '{max_value}'")
        # Get or set setting
        setting_item = DbusSettingsService.get().get_item(setting_path, default_value, min_value, max_value)

        # Init item and custom callback
        item = self._set_value(item_path, setting_item.get_value())
        self.set_proxy_callback(item_path, setting_item, callback)

        # Set settings callback
        setting_item = DbusSettingsService.get().set_proxy_callback(setting_path, self._get_item(item_path))

    def add_ble_adapter(self, name: str, mac: str):
        self._set_value(f"/Interfaces/{name}/Address", mac)

    def remove_ble_adapter(self, name: str):
        self._delete_item(f"/Interfaces/{name}/Address")

    def register_role_service(self, dbus_role_service, enable_callback):
        role_name = dbus_role_service.ble_role.get_name()
        dev_id = dbus_role_service.get_dev_id()

        # Add name
        custom_name = dbus_role_service.get_custom_name()
        name = custom_name if custom_name else dbus_role_service.get_device_name()
        self._set_value(f"/Devices/{dev_id}_{role_name}/Name", f"{name} {role_name}")

        # Add enable entry
        self._init_proxy_setting(
            f"/Settings/Devices/{dbus_role_service.get_dbus_id()}/Enabled",
            f"/Devices/{dev_id}_{role_name}/Enabled",
            0,
            0,
            1,
            callback=enable_callback
        )

    def is_device_enabled(self, device_info: dict) -> bool:
        """
        Check if at least one of the device sensors is enabled
        """
        for role_name in device_info['roles']:
            if self._get_value(f"/Devices/{device_info['dev_id']}_{role_name}/Enabled"):
                return True
        return False

    def init_continuous_scan(self):
        def log(value):
            logging.info(f"Continuous scanning set to '{value}'")
        self._init_proxy_setting(
            '/Settings/BleSensors/ContinuousScan',
            '/ContinuousScan',
            0,
            0,
            1,
            log
        )

    def get_continuous_scan(self) -> bool:
        return bool(self._dbus_ble_service['/ContinuousScan'])
