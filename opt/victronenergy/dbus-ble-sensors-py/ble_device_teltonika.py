import dbus
import logging
from ble_device import BleDevice


class BleDeviceTeltonika(BleDevice):
    # Protocle specification: https://wiki.teltonika-gps.com/view/EYE_SENSOR_/_BTSMP1#Sensor_advertising
    # Data parsing: https://wiki.teltonika-gps.com/view/EYE_SENSOR_/_BTSMP1#EYE_Sensor_Bluetooth%C2%AE_frame_parsing_example

    MANUFACTURER_ID = 0x089A

    def configure(self, manufacturer_data: bytes):
        self.info.update({
            'manufacturer_id': BleDeviceTeltonika.MANUFACTURER_ID,
            'product_id': 0x3042,
            'product_name': 'TeltonikaEye',
            'dev_prefix': 'teltonika',
            'alarms': [
                {
                    'name': 'LowBattery',
                    'item': 'LowBattery',
                    'level': 0.9,
                    'flags': ['ALARM_FLAG_HIGH']
                }
            ]
        })
        self._compute_regs(manufacturer_data)
        logging.debug(f"{self._plog} computed regs: {self.info['regs']}")

    def _compute_regs(self, manufacturer_data: bytes):
        self.info['roles'] = []
        self.info['regs'] = [
            {
                'name': 'Version',
                'type': dbus.types.Byte,
                'offset': 0,
                'roles': [None],
            },
            {
                'name': 'EyeFlags',
                'type': dbus.types.Byte,
                'offset': 1,
                'roles': [None],
            },
            {
                'name': 'LowBattery',
                'type': dbus.types.Boolean,
                'offset': 1,
                'shift': 6,
                'bits': 1,
            }
        ]

        # Compute regs from flags
        offset = 2
        flag_mag = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 2,
            'bits': 1,
        }, manufacturer_data)
        if flag_mag:
            self.info['regs'].append({
                'name': 'InputState',  # Magnet presence
                'type': dbus.types.Boolean,
                'offset': 1,
                'shift': 3,
                'bits': 1,
                'roles': ['digitalinput'],
            })
            self.info['roles'].append('digitalinput')

        flag_temp = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 0,
            'bits': 1,
        }, manufacturer_data)
        if flag_temp:
            self.info['regs'].append({
                'name': 'Temperature',
                'type': dbus.types.Int16,
                'offset': offset,
                'scale': 100,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
                'roles': ['temperature'],
            })
            self.info['roles'].append('temperature')
            offset = offset + 2

        flag_humid = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 1,
            'bits': 1,
        }, manufacturer_data)
        if flag_humid:
            self.info['regs'].append({
                'name': 'Humidity',
                'type': dbus.types.Byte,
                'offset': offset,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
                'roles': ['temperature'],
            })
            self.info['roles'].append('temperature')
            offset = offset + 1

        flag_mov = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 4,
            'bits': 1,
        }, manufacturer_data)
        if flag_mov:
            self.info['regs'].append({
                'name': 'MovementState',
                'type': dbus.types.Boolean,
                'offset': offset,
                'shift': 7,
                'bits': 1,
                'roles': ['movement'],
            })
            self.info['regs'].append({
                'name': 'MovementCount',
                'type': dbus.types.UInt16,
                'offset': offset,
                'mask': 0x7FFF,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
                'roles': ['movement'],
            })
            self.info['roles'].append('movement')
            offset = offset + 2

        flag_angle = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 5,
            'bits': 1,
        }, manufacturer_data)
        if flag_angle:
            self.info['regs'].append({
                'name': 'Pitch',
                'type': dbus.types.Byte,
                'offset': offset,
                'xlate': 'byteToSignedInt',
                'roles': ['movement'],
            })
            offset = offset + 1
            self.info['regs'].append({
                'name': 'Roll',
                'type': dbus.types.Int16,
                'offset': 8,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
                'roles': ['movement'],
            })
            self.info['roles'].append('movement')
            offset = offset + 2

        flag_bat = self.load_int({
            'name': 'Flag',
            'type': dbus.types.Boolean,
            'offset': 1,
            'shift': 7,
            'bits': 1,
        }, manufacturer_data)
        if flag_bat:
            self.info['regs'].append({
                'name': 'BatteryVoltage',
                'type': dbus.types.Byte,
                'offset': offset,
                'scale': 1/10,
                'bias': 2000,
            })

        self.info['roles'] = list(set(self.info['roles']))
