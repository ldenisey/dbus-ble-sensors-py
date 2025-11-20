from __future__ import annotations
import os
import inspect
import logging
import importlib.util
import dbus
from functools import partial
from dbus_ble_service import DbusBleService
from dbus_device_service import DbusDeviceService
from ble_role import BleRole


class BleDevice(object):

    _ALLOWED_TYPES = [dbus.types.Boolean, dbus.types.Byte, dbus.types.Int16, dbus.types.UInt16, dbus.types.Int32,
                      dbus.types.UInt32, dbus.types.Int64, dbus.types.UInt64, dbus.types.Double, dbus.types.String]

    _SIGNED_TYPES = [dbus.types.Int16, dbus.types.Int32, dbus.types.Int64]

    MANUFACTURER_ID = 0  # To be overloaded in children classes: int, ble manufacturer id

    # Dict of devices classes, key is manufacturer id
    DEVICE_CLASSES = {}

    def __init__(self, dev_mac: str, dev_name: str):
        self._dbus_services: dict = {}
        self._plog: str = None

        # Mandatory fields must be overloaded by subclasses, optional ones can be left as is.
        self.info = {
            'dev_mac': dev_mac,         # Internal
            'product_id': 0x0000,       # Mandatory, int, ble product id
            'product_name': None,       # Mandatory, str, product name without spaces or special chars
            'DeviceName': dev_name,     # Optional, str, human friendly device name, i.e. Ruuvi AABB
            'hardware_version': "1.0.0",  # Optional,  str, Device harware version
            'firmware_version': "1.0.0",  # Optional,  str, Device firmware version
            'dev_prefix': None,         # Mandatory, str, device prefix, used in dbus path, must be short, without spaces
            'roles': [],                # Mandatory, list of str in : temperature, tank, battery, digitalinput
            'regs': [],                 # Mandatory, list of dict, device advertising data, defined with :
                                        # - offset : mandatory, byte offset, i.e. data start position
                                        # - type   : mandatorytype of the data
                                        # - bits   : length of the data in bits, mandatory if type is not set
                                        # - mask   : bit mask to apply to the raw value
                                        # - shift  : bit offset, in case the data is not "byte aligned"
                                        # - scale  : scale to divide the value with
                                        # - bias   : bias to add to the value
                                        # - flags  : can be : REG_FLAG_BIG_ENDIAN, REG_FLAG_INVALID
                                        # - xlate  : name of a method to be executed after data parsing
                                        # - inval  : if flag REG_FLAG_INVALID is set, value that invalidate the data
                                        # - roles  : list of role names the data is relevant for. If contains None, will be ignored
            'settings': [],             # Optional,  list of dict, settings that could be set through UI
            'alarms': [],               # Optional,  list of dict, raisable alarms, defined with :
                                        # - name      : Name of the alarm
                                        # - item      : Type of alarm to raise
                                        # - flags     : list of :
                                        #    - "ALARM_FLAG_CONFIG" if the alarm targets a config
                                        #    - "ALARM_FLAG_HIGH" if the alarm should be triggered when data is higher than level
                                        # - level     : Float value defining the alarm level
                                        # - get_level : Name of a method to compute level if needed
                                        # - hyst      : Hysterisis value to add to level when the alarm is active
                                        # - active    : &high_active_props
                                        # - restore   : &high_restore_props
                                        #
                                        # - name	  : "High",
                                        # - item	  : "Level",
                                        # - flags	  : ALARM_FLAG_HIGH | ALARM_FLAG_CONFIG,
                                        # - active  : &high_active_props,
                                        # - restore : &high_restore_props,
                                        #
                                        # .name	= "LowBattery",
                                        # .item	= "BatteryVoltage",
                                        # .hyst	= 0.4,
                                        # .get_level = ruuvi_lowbat,
                                        #
                                        # .name	= "LowBattery",
                                        # .item	= "BatteryVoltage",
                                        # .level	= 3.2,
                                        # .hyst	= 0.4,
            'data': {},                 # Optional,  dict, custom dict passed to custom role and device methods
        }

    def configure(self, manufacturer_data: bytes):
        """
        Mandatory overload, update self.info with specific configuration
        """
        raise NotImplementedError("Device class must be configured")

    def init(self):
        # Setting configuration
        self.load_configuration()
        self.check_configuration()

        logging.debug(f"{self._plog} initializing device ...")

        # Setting ble service
        self.configure_dbus_ble_service()

        # Settings device services (one service per role)
        self.load_dbus_services()
        for dbus_service in self._dbus_services.values():
            self.init_device_dbus_service(dbus_service)
        logging.debug(f"{self._plog} initialized")

    def update_data(self, dbus_service: DbusDeviceService, sensor_data: dict):
        """
        Optional overload. Executed after the data parsing, before updating them on service Dbus.
        Can be used to add or modify data depending on settings or custom methods.
        """
        pass

    def handle_mfg(self, manufacturer_data: bytes):
        """
        Optional overload, check product id to adapt to various harware if any and/or implement specific parsing logic.
        Returns 0 if this class can manage the device, anything else if it can't.
        """
        if not self.is_enabled():
            logging.debug(f"{self._plog} device not enabled, skipping")
            return

        # Parse data
        sensor_data: dict = self.parse_manufacturer_data(manufacturer_data)
        logging.debug(f"{self._plog} data '{manufacturer_data}' parsed: {sensor_data}")
        for dbus_service in self._dbus_services.values():
            # Filtering data
            service_data = sensor_data[dbus_service.ble_role.get_name()]

            # Update sensor data from update callbacks
            dbus_service.ble_role.update_data(dbus_service, service_data)
            self.update_data(dbus_service, service_data)

            # Update Dbus with new data
            self.update_dbus_data(dbus_service, service_data)

            # Update alarm states
            for alarm in dbus_service.ble_role.info['alarms']:
                self.update_alarm(dbus_service, alarm, dbus_service.ble_role)
            for alarm in self.info['alarms']:
                self.update_alarm(dbus_service, alarm, self)

            # Start service if needed
            dbus_service.connect()


# /!\/!\/!\/!\/!\/!\  Methods below should not been overrided  /!\/!\/!\/!\/!\/!\

    @staticmethod
    def load_device_classes(execution_path: str):
        device_classes_prefix = f"{os.path.splitext(os.path.basename(__file__))[0]}_"

        # Loading manufacturer specific classes
        for filename in os.listdir(os.path.dirname(execution_path)):
            if filename.startswith(device_classes_prefix) and filename.endswith('.py'):
                module_name = os.path.splitext(filename)[0]

                # Import the module from file
                spec = importlib.util.spec_from_file_location(module_name, filename)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Check and import
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ == module.__name__ and issubclass(obj, BleDevice) and obj is not BleDevice:
                        BleDevice.DEVICE_CLASSES[obj.MANUFACTURER_ID] = obj
                        break
        logging.info(f"Device classes: {BleDevice.DEVICE_CLASSES}")

    @staticmethod
    def byteToSignedInt(byte: bytes) -> int:
        return byte if byte < 128 else byte - 256

    def load_configuration(self):
        self.info['manufacturer_id'] = self.MANUFACTURER_ID
        self.info['dev_id'] = self.info['dev_prefix'] + '_' + self.info['dev_mac']
        self.info['DeviceName'] = self.info['DeviceName'] + ' ' + self.info['dev_mac'][-4:].upper()
        self._plog = f"{self.info['dev_mac']} - {self.info['DeviceName']}:"

    def check_configuration(self):
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
            if (onchange := setting.get('onchange', None)):
                if not hasattr(self, onchange):
                    raise ValueError(f"{self._plog} Missing method '{onchange}' defined in setting {setting['name']}")

        for index, alarm in enumerate(self.info['alarms']):
            if 'name' not in alarm:
                raise ValueError(f"{self._plog} Missing 'name' in alarm at index {index}")
            for key in ['item']:
                if key not in alarm:
                    raise ValueError(f"{self._plog} Missing key '{key}' in alarm {alarm['name']}")
            for sig in ['active', 'restore']:
                if alarm.get(sig, None):
                    for key in ['def', 'min', 'max']:
                        if key not in alarm[sig]:
                            raise ValueError(
                                f"{self._plog} Missing key '{key}' in field {sig} of alarm {alarm['name']}")
            if (alarm.get('flags', None) and 'ALARM_FLAG_CONFIG' not in alarm['flags']) and alarm.get('level', None) is None and alarm.get('getlevel', None) is None:
                raise ValueError(
                    f"{self._plog} Alarm {alarm['name']}must define a level with a 'level' or a 'getlevel' fields or using dbus configuration with 'ALARM_FLAG_CONFIG' flag.")

    def on_enabled_changed(self, new_enabled_value: int):
        for dbus_service in self._dbus_services.value():
            if new_enabled_value:
                dbus_service.connect()
            else:
                dbus_service.disconnect()

    def configure_dbus_ble_service(self):
        # Set name
        DbusBleService.get().set_device_name(self.info)

        # Init Enabled setting
        DbusBleService.get().init_enabled_status(self.info, self.on_enabled_changed)

    def load_dbus_services(self):
        for role_name in self.info['roles']:
            self._dbus_services[role_name] = DbusDeviceService(self, BleRole.get_role_instance(role_name))

    def init_settings(self, dbus_service: DbusDeviceService, instance):
        for setting in instance.info['settings']:
            onchange_method = None
            if (onchange := setting.get('onchange', None)):
                onchange_method = partial(getattr(instance, onchange), dbus_service)
            dbus_service.add_setting(setting, onchange_method)

    def init_alarms(self, dbus_service: DbusDeviceService, alarms: list):
        for alarm in alarms:
            if alarm.get('flags', None) and 'ALARM_FLAG_CONFIG' in alarm['flags']:
                dbus_service.add_alarm(alarm)

    def init_device_dbus_service(self, dbus_service: DbusDeviceService):
        dbus_service.init_custom_name()
        dbus_service.set_device_name()

        self.init_settings(dbus_service, dbus_service.ble_role)
        self.init_alarms(dbus_service, dbus_service.ble_role.info['alarms'])

        dbus_service.ble_role.init(dbus_service)

        self.init_settings(dbus_service, self)
        self.init_alarms(dbus_service, self.info['alarms'])

    def is_enabled(self) -> bool:
        return DbusBleService.get().is_device_enabled(self.info)

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
            value = getattr(self, xlate)(value)
        if 'REG_FLAG_INVALID' in flags and value == reg.get('inval', None):
            value = None
        return value

    def parse_manufacturer_data(self, manufacturer_data: bytes) -> dict:
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

    def update_dbus_data(self, dbus_service: DbusDeviceService, sensor_data: dict):
        for name, value in sensor_data.items():
            dbus_service.set_value(name, value)

    def update_alarm(self, dbus_service: DbusDeviceService, alarm: dict, instance):
        # Is alarm enabled ?
        if not dbus_service.is_alarm_enabled(alarm):
            return

        # Is alarm active ?
        active = dbus_service.get_alarm_active_status(alarm)

        # Get alarm level (i.e. threshold)
        if alarm.get('flags', None) and 'ALARM_FLAG_CONFIG' in alarm['flags']:
            level = dbus_service.get_alarm_level(alarm, active)
        else:
            if alarm.get('get_level', None):
                level = getattr(instance, alarm['get_level'])(self.droot, alarm)
            else:
                level = alarm['level']
            if active:
                level += alarm.get('hyst', 0)

        # Compare level to latest sensor value
        sensor_value = float(dbus_service.get_value(alarm['item']))
        if alarm.get('flags', None) and 'ALARM_FLAG_HIGH' in alarm['flags']:
            active = sensor_value > level
        else:
            sensor_value < level
        dbus_service.set_alarm_active_status(alarm, active)
