from __future__ import annotations
import os
import inspect
import logging
import importlib.util
import dbus
from functools import partial
from dbus_ble_service import DbusBleService
from dbus_role_service import DbusRoleService
from ble_role import BleRole


class BleDevice(object):
    """
    Device base class.
    
    Children class:
        - must overload class variable 'MANUFACTURER_ID' and 'configure' method with self.info.update
    method to overload entries as described in code.
        - can overload 'update_data' method to add post parsing custom logic
    """

    _ALLOWED_TYPES = [dbus.types.Boolean, dbus.types.Byte, dbus.types.Int16, dbus.types.UInt16, dbus.types.Int32,
                      dbus.types.UInt32, dbus.types.Int64, dbus.types.UInt64, dbus.types.Double, dbus.types.String]

    _SIGNED_TYPES = [dbus.types.Int16, dbus.types.Int32, dbus.types.Int64]

    MANUFACTURER_ID = 0  # To be overloaded in children classes: int, ble manufacturer id

    # Dict of devices classes, key is manufacturer id
    DEVICE_CLASSES = {}

    def __init__(self, dev_mac: str, dev_name: str):
        self._role_services: dict = {}
        self._plog: str = None

        # Mandatory fields must be overloaded by subclasses, optional ones can be left as is.
        self.info = {
            'dev_mac': dev_mac,         # Internal
            'product_id': 0x0000,       # Mandatory, int, custom product id. As no product ID list exists, invent one.
            'product_name': None,       # Mandatory, str, product name without spaces or special chars
            'DeviceName': dev_name,     # Optional, str, human friendly device name, i.e. Ruuvi AABB
            'hardware_version': '1.0.0',  # Optional,  str, Device harware version
            'firmware_version': '1.0.0',  # Optional,  str, Device firmware version
            'dev_prefix': None,         # Mandatory, str, device prefix, used in dbus path, must be short, without spaces
            'roles': [],                # Mandatory, list of str in : temperature, tank, battery, digitalinput
            'regs': [],                 # Mandatory, list of dict, device advertising data, defined with :
                                        # - offset : mandatory, byte offset, i.e. data start position
                                        # - type   : mandatory, type of the data, cf. _ALLOWED_TYPES
                                        # - bits   : length of the data in bits, mandatory if type is not set
                                        # - mask   : bit mask to apply to the raw value
                                        # - shift  : bit offset, in case the data is not "byte aligned"
                                        # - scale  : scale to divide the value with
                                        # - bias   : bias to add to the value
                                        # - flags  : can be : REG_FLAG_BIG_ENDIAN, REG_FLAG_INVALID
                                        # - xlate  : custom method to be executed after data parsing
                                        # - inval  : if flag REG_FLAG_INVALID is set, value that invalidates the data
                                        # - roles  : list of role names concerned by the data. If not defined, all roles, if contains None, data is ignored.
            'settings': [],             # Optional,  list of dict, settings that could be set through UI
            'alarms': [],               # Optional,  list of dict, raisable alarms, defined with :
                                        # - name   : Name of the alarm
                                        # - update : method returning, depending on which alarm it is:
                                        #       - 0 : no alarm
                                        #       - 1 : alarm or warning
                                        #       - 2 : alarm
        }

    def configure(self, manufacturer_data: bytes):
        """
        Mandatory overload, use self.info.update() to add specific configuration.
        """
        raise NotImplementedError("Device class must be configured")

    def update_data(self, role_service: DbusRoleService, sensor_data: dict):
        """
        Optional overload. Executed after data parsing, before updating them on service Dbus.
        Can be used to add or modify data depending on settings or custom methods.
        """
        pass

# /!\/!\/!\/!\/!\/!\  Methods below should not be overridden  /!\/!\/!\/!\/!\/!\

    @staticmethod
    def load_classes(execution_path: str):
        device_classes_prefix = f"{os.path.splitext(os.path.basename(__file__))[0]}_"

        # Loading manufacturer specific classes
        for filename in os.listdir(os.path.dirname(execution_path)):
            if filename.startswith(device_classes_prefix) and filename.endswith('.py'):
                file_path = os.path.join(os.path.dirname(execution_path), filename)
                module_name = os.path.splitext(filename)[0]

                # Import the module from file
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Check and import
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ == module.__name__ and issubclass(obj, BleDevice) and obj is not BleDevice:
                        BleDevice.DEVICE_CLASSES[obj.MANUFACTURER_ID] = obj
                        break
        logging.info(f"Device classes: {BleDevice.DEVICE_CLASSES}")

    def _load_configuration(self):
        self.info['manufacturer_id'] = self.MANUFACTURER_ID
        self.info['dev_id'] = self.info['dev_prefix'] + '_' + self.info['dev_mac']
        self.info['DeviceName'] = self.info['DeviceName'] + ' ' + self.info['dev_mac'][-4:].upper()
        self._plog = f"{self.info['dev_mac']} - {self.info['DeviceName']}:"

    def _check_configuration(self):
        for key in ['manufacturer_id', 'product_id', 'product_name', 'DeviceName', 'dev_prefix', 'roles', 'regs', 'settings', 'alarms']:
            if key not in self.info:
                raise ValueError(f"{self._plog} configuration '{key}' is missing")
            if self.info[key] is None:
                raise ValueError(f"{self._plog} Configuration '{key}' can not be None")

        for number in ['manufacturer_id', 'product_id']:
            if not isinstance(self.info[number], int):
                raise ValueError(f"{self._plog} Configuration '{number}' must be an integer")

        for list_key in ['roles', 'regs', 'settings', 'alarms']:
            if not isinstance(self.info[list_key], list):
                raise ValueError(f"{self._plog} Configuration '{list_key}' must be a list")

        for list_mandatory in ['roles', 'regs']:
            if self.info[list_mandatory].__len__() < 1:
                raise ValueError(f"{self._plog} Configuration '{list_mandatory}' must have at least one element")

        for role in self.info['roles']:
            if role is not None and role not in BleRole._ROLE_INSTANCE:
                raise ValueError(f"{self._plog} Unknown role '{role}'")

        for index, reg in enumerate(self.info['regs']):
            if 'name' not in reg:
                raise ValueError(f"{self._plog} Missing 'name' in reg at index {index}")
            for key in ['type', 'offset']:
                if key not in reg:
                    raise ValueError(f"{self._plog} Missing key '{key}' in reg {reg['name']}")
            if (reg_type := reg['type']) not in BleDevice._ALLOWED_TYPES:
                raise ValueError(f"{self._plog} Data type {reg_type} in reg {reg['name']} is not allowed")
            if reg_type == dbus.types.String:
                if (bits := reg.get('bits', None)) is None:
                    raise ValueError(f"{self._plog} missing 'bits' in reg {reg['name']}")
                elif not isinstance(bits, int):
                    raise ValueError(f"{self._plog} 'bits' in reg {reg['name']} must be an integer")
                elif bits % 8 != 0:
                    raise ValueError(f"{self._plog} 'bits' in reg {reg['name']} must be a multiple of 8")
            if 'roles' in reg:
                for role in reg['roles']:
                    if role is not None and role not in BleRole._ROLE_INSTANCE:
                        raise ValueError(f"{self._plog} Unknown role '{role}' in reg {reg['name']}")

        for index, setting in enumerate(self.info['settings']):
            if 'name' not in setting:
                raise ValueError(f"{self._plog} Missing 'name' in setting at index {index}")
            if 'props' not in setting:
                raise ValueError(f"{self._plog} Missing 'props' definition in setting {setting['name']}")
            for key in ['def', 'min', 'max']:
                if key not in setting['props']:
                    raise ValueError(f"{self._plog} Missing key '{key}' in setting {setting['name']}")

        for index, alarm in enumerate(self.info['alarms']):
            if 'name' not in alarm:
                raise ValueError(f"{self._plog} Missing 'name' in alarm at index {index}")
            for key in ['name', 'update']:
                if key not in alarm:
                    raise ValueError(f"{self._plog} Missing key '{key}' in alarm {alarm['name']}")

    def _init_settings(self, role_service: DbusRoleService, instance):
        for setting in instance.info['settings']:
            callback = None
            if (onchange := setting.get('onchange', None)) is not None:
                callback = partial(onchange, role_service)
            role_service.add_setting(setting, callback)

    def _configure_role_service(self, role_service: DbusRoleService):
        role_service.init_custom_name()
        role_service.set_device_name()

        self._init_settings(role_service, role_service.ble_role)
        for alarm in role_service.ble_role.info['alarms']:
            role_service.add_alarm(alarm)

        role_service.ble_role.init(role_service)

        self._init_settings(role_service, self)
        for alarm in self.info['alarms']:
            role_service.add_alarm(alarm)

    def _on_enabled_changed(self, role_service: DbusRoleService, is_enabled: int):
        if is_enabled:
            role_service.connect()
        else:
            role_service.disconnect()

    def init(self):
        # Setting configuration
        self._load_configuration()
        self._check_configuration()

        logging.debug(f"{self._plog} initializing device ...")

        # Init role services
        for role_name in self.info['roles']:
            role_service = DbusRoleService(self, BleRole.get_instance(role_name))
            self._role_services[role_name] = role_service
            # Initializing Dbus service
            self._configure_role_service(role_service)
            # Creating entries in ble service to enable/disable options
            DbusBleService.get().register_role_service(role_service, partial(self._on_enabled_changed, role_service))
        logging.debug(f"{self._plog} initialized")

    def load_str(self, reg: dict, manufacturer_data: bytes) -> str:
        # Check there is enough data
        offset: int = reg['offset']
        size = (reg['bits'] + 7) >> 3
        if size > len(manufacturer_data) - offset:
            logging.error(
                f"{self._plog} can not parse {reg['name']}, field is longer than manufacturer data, ignoring it")
            return None

        return manufacturer_data[offset:offset + size].decode(encoding='utf-8')

    def load_int(self, reg: dict, manufacturer_data: bytes) -> any:
        offset: int = reg['offset']
        flags: list = reg.get('flags', [])
        shift: int = reg.get('shift', None)
        _type = reg['type']

        # Get data length
        if (bits := reg.get('bits', None)) is None:
            match _type:
                case dbus.types.Boolean | dbus.types.Byte:
                    bits = 8
                case dbus.types.Int16 | dbus.types.UInt16:
                    bits = 16
                case dbus.types.Int32 | dbus.types.UInt32:
                    bits = 32
                case dbus.types.Int64 | dbus.types.UInt64:
                    bits = 64
                case _:
                    return None

        # Check there is enough data
        size = (bits + (shift if shift is not None else 0) + 7) >> 3
        if size > len(manufacturer_data) - offset:
            logging.error(
                f"{self._plog} can not parse {reg['name']}, field is longer than manufacturer data, ignoring it")
            return None

        # Get raw value
        value = int.from_bytes(
            manufacturer_data[offset:offset + size],
            byteorder='big' if 'REG_FLAG_BIG_ENDIAN' in flags else 'little',
            signed=_type in BleDevice._SIGNED_TYPES
        )

        # Applying mask, if any
        if reg.get('mask', None) is not None:
            value = value & reg['mask']

        # Applying shift and triming on bits size
        if shift is not None:
            value = (value >> shift) & ((1 << bits) - 1)

        # Post actions
        if scale := reg.get('scale', None):
            value = value / scale
        if bias := reg.get('bias', None):
            value = value + bias
        if xlate := reg.get('xlate', None):
            value = xlate(value)
        if 'REG_FLAG_INVALID' in flags and value == reg.get('inval', None):
            value = None
        return value

    def _parse_manufacturer_data(self, manufacturer_data: bytes) -> dict:
        values = {}
        for role in self.info['roles']:
            values[role] = {}
        for reg in self.info['regs']:
            value = None
            match reg['type']:
                case dbus.types.Boolean:
                    value = bool(self.load_int(reg, manufacturer_data))
                case dbus.types.Byte | dbus.types.Int16 | dbus.types.UInt16 | dbus.types.Int32 | dbus.types.UInt32 | dbus.types.Int64 | dbus.types.UInt64 | dbus.types.Double:
                    value = self.load_int(reg, manufacturer_data)
                case dbus.types.String:
                    value = self.load_str(reg, manufacturer_data)
                case _:
                    pass

            if value is None:
                continue

            if (roles := reg.get('roles', None)) and None in roles:
                continue
            if roles is None:
                roles = self.info['roles']

            for role in roles:
                values[role][(reg['name'])] = value
        return values

    def _update_dbus_data(self, role_service: DbusRoleService, sensor_data: dict):
        for name, value in sensor_data.items():
            role_service[name] = value

    def handle_data(self, manufacturer_data: bytes):
        """
        Optional overload, check product id to adapt to various harware if any and/or implement specific parsing logic.
        Returns 0 if this class can manage the device, anything else if it can't.
        """
        if not DbusBleService.get().is_device_enabled(self.info):
            logging.debug(f"{self._plog} device not enabled, skipping")
            return

        # Parse data
        sensor_data: dict = self._parse_manufacturer_data(manufacturer_data)
        logging.debug(f"{self._plog} data '{manufacturer_data}' parsed: {sensor_data}")
        for role_service in self._role_services.values():
            # Filtering data
            role_data = sensor_data[role_service.ble_role.get_name()]

            # Update sensor data from update callbacks
            role_service.ble_role.update_data(role_service, role_data)
            self.update_data(role_service, role_data)

            # Update Dbus with new data
            self._update_dbus_data(role_service, role_data)

            # Update alarm states
            for alarm in role_service.ble_role.info['alarms']:
                role_service.update_alarm(alarm)
            for alarm in self.info['alarms']:
                role_service.update_alarm(alarm)

            # Start service if needed
            role_service.connect()

