import os
import asyncio
import logging
import dbus
from dbus_settings_service import DbusSettingsService
from ble_role import BleRole
from conf import PROCESS_NAME, PROCESS_VERSION, DBUS_ROLE_SERVICES_TIMEOUT
from vedbus import VeDbusService, VeDbusItemImport, VeDbusItemExport


class DbusRoleService(object):
    """
    Role service class. Responsible for holding and sharing data through a dedicated dbus service.
    """
    

    def __init__(self, ble_device, ble_role: BleRole):
        # private=True to allow creation of multiple services in the same app
        self._bus: dbus.Bus = dbus.SessionBus(
            private=True) if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus(private=True)
        self._ble_device = ble_device
        self.ble_role = ble_role
        self._dbus_service: VeDbusService = None  # Is velib_python good enough to be a parent class ?
        self._dbus_service_timer = None
        self._service_name: str = None
        self._dbus_iface = dbus.Interface(
            self._bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
            'org.freedesktop.DBus')
        self._dev_id = self._ble_device.info['dev_id']
        self._dbus_id = f"{self._dev_id}/{self.ble_role.get_name()}"
        self.init_service()

    def is_connected(self) -> bool:
        # Local check
        if self._dbus_service is None:
            return False

        # Dbus check
        return self._dbus_iface.NameHasOwner(self._service_name)

    def _get_vrm_instance(self) -> int:
        # Try and get instance saved in settings
        if (dev_instance := DbusSettingsService.get().get_value(f"/Settings/Devices/{self._dbus_id}/VrmInstance")):
            logging.info(f"{self._ble_device._plog} vrm instance {dev_instance} found for device {self._dbus_id}")
            return dev_instance

        # Load devices from settings
        devices_string: dict = DbusSettingsService.get().get_item('/Settings/Devices').get_value()
        if not devices_string:
            return -1

        # Filter existing ClassAndVrmInstance and get VrmInstance
        role_name = self.ble_role.get_name()
        existing_instances = set()
        for key, value in devices_string.items():
            if '/ClassAndVrmInstance' in key and value.startswith(role_name):
                existing_instances.add(int(value[len(role_name) + 1:]))
            elif f"{role_name}/VrmInstance" in key:
                existing_instances.add(int(value))

        # Increment instance until free one found
        cur_instance = int(self.ble_role.info['dev_instance'])
        while cur_instance in existing_instances:
            cur_instance += 1

        # Save instance in settings
        logging.info(f"{self._ble_device._plog} assigning vrm instance {cur_instance} for role {role_name}")
        DbusSettingsService.get().set_item(f"/Settings/Devices/{self._dbus_id}/VrmInstance", cur_instance)
        return cur_instance

    def init_service(self):
        self._service_name = f"com.victronenergy.{self.ble_role.get_name()}.{self._dev_id}"

        logging.debug(f"{self._ble_device._plog} initializing dbus '{self._service_name}'")
        self._dbus_service = VeDbusService(self._service_name, self._bus, False)

        # Add mandatory data
        self._dbus_service.add_path('/Mgmt/ProcessName', PROCESS_NAME)
        self._dbus_service.add_path('/Mgmt/ProcessVersion', PROCESS_VERSION)
        self._dbus_service.add_path('/Mgmt/Connection', "Bluetooth LE")
        # Device instance will be set at connection to avoid conflicts
        self._dbus_service.add_path('/ProductId', self._ble_device.info['product_id'])
        self._dbus_service.add_path('/ProductName', self._ble_device.info['product_name'])
        self._dbus_service.add_path('/FirmwareVersion', self._ble_device.info['firmware_version'])
        self._dbus_service.add_path('/HardwareVersion', self._ble_device.info['hardware_version'])
        self._dbus_service.add_path('/Connected', 1, writeable=True)
        self._dbus_service.add_path('/Status', 0, writeable=True)

    def connect(self):
        if self.is_connected():
            self._dbus_service_timer.cancel()
        else:
            # Device instance check
            if not self._get_value('/DeviceInstance'):
                self._set_value('/DeviceInstance', self._get_vrm_instance())

            logging.info(f"{self._ble_device._plog} registrating '{self._service_name}' dbus service on bus {self._bus}")
            self._dbus_service.register()
        self._dbus_service_timer = asyncio.create_task(self._connection_timeout())

    def disconnect(self):
        if not self.is_connected():
            return
        logging.info(f"{self._ble_device._plog} releasing '{self._service_name}' dbus service")
        self._dbus_service._dbusname.__del__()
        self._dbus_service._dbusname = None

    async def _connection_timeout(self):
        await asyncio.sleep(DBUS_ROLE_SERVICES_TIMEOUT)
        logging.warning(
            f"{self._ble_device._plog} no data received since {DBUS_ROLE_SERVICES_TIMEOUT} seconds, disconnecting dbus service")
        self.disconnect()

    @staticmethod
    def _clear_path(path: str) -> str:
        return f"/{path.lstrip('/').rstrip('/')}"

    def _get_item(self, path: str) -> VeDbusItemExport:
        return self._dbus_service._dbusobjects.get(self._clear_path(path), None)

    def _get_value(self, path: str) -> any:
        if (item := self._get_item(path)):
            return item.local_get_value()
        return None

    def _set_value(self, path: str, value: any):
        clean_path = self._clear_path(path)
        with self._dbus_service as service:
            if clean_path not in service:
                logging.debug(f"{self._ble_device._plog} setting item {self._service_name}@{clean_path} to {value}")
                service.add_path(clean_path, value, writeable=True)
            elif service[clean_path] != value:
                logging.debug(f"{self._ble_device._plog} creating item {self._service_name}@{clean_path} to {value}")
                service[clean_path] = value

    def _delete_item(self, path: str):
        clean_path = self._clear_path(path)
        if self._dbus_service._dbusobjects.get(clean_path, None) is None:
            logging.error(f"Can not delete unexisting {clean_path}")
        else:
            logging.debug(f"Deleting item {self._service_name}@{clean_path}")
            with self._dbus_service as service:
                del service[clean_path]

    def __getitem__(self, path: str) -> any:
        return self._get_value(path)

    def __setitem__(self, path: str, new_value: any):
        self._set_value(path, new_value)

    def __delitem__(self, path: str):
        self._delete_item(path)

    def _set_proxy_callback(self, item_path: str, setting_item: VeDbusItemImport, callback=None):
        def _callback(change_path, new_value):
            if change_path != item_path:
                return 0
            if new_value != setting_item.get_value():
                setting_item.set_value(new_value)
            if callback:
                callback(new_value)
            return 1
        self._dbus_service._dbusobjects[item_path]._onchangecallback = _callback

    def _init_proxy_setting(self, setting_path: str, item_path: str, default_value: any, min_value: int = 0, max_value: int = 0, callback=None):
        logging.debug(
            f"Creating setting '{setting_path}' proxy to '{item_path}' with: '{default_value}' '{min_value}' '{max_value}' '{callback}'")
        # Get or set setting
        setting_item = DbusSettingsService.get().get_item(setting_path, default_value, min_value, max_value)

        # Init item and custom callback
        item = self._set_value(item_path, setting_item.get_value())
        self._set_proxy_callback(item_path, setting_item, callback)

        # Set settings callback
        setting_item = DbusSettingsService.get().set_proxy_callback(setting_path, self._get_item(item_path))

    def get_dev_id(self) -> str:
        return self._dev_id

    def get_dbus_id(self) -> str:
        return self._dbus_id

    def init_custom_name(self):
        self._init_proxy_setting(
            f"/Settings/Devices/{self._dbus_id}/CustomName",
            '/CustomName',
            '',
        )

    def get_custom_name(self) -> str:
        return self._get_value('/CustomName')

    def set_device_name(self):
        self._set_value('/DeviceName', self._ble_device.info['DeviceName'])

    def get_device_name(self) -> str:
        return self._get_value('/DeviceName')

    def add_setting(self, setting: dict, callback=None):
        name = self._clear_path(setting['name'])
        props = setting['props']
        self._init_proxy_setting(
            f"/Settings/Devices/{self._dbus_id}{name}",
            name,
            props['def'],
            props['min'],
            props['max'],
            callback=callback
        )

    def add_alarm(self, alarm: dict):
        self._set_value(alarm['name'], 0)

    def update_alarm(self, alarm: dict):
        alarm_state = alarm['update'](self)
        self._set_value(alarm['name'], alarm_state)
