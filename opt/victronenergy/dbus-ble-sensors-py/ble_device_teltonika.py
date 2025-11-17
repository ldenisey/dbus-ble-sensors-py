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
        logging.debug(f"{self._plog} flag magnet: {flag_mag}")
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
        logging.debug(f"{self._plog} flag temperature: {flag_temp}")
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
        logging.debug(f"{self._plog} flag humidity: {flag_humid}")
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
            })
            self.info['regs'].append({
                'name': 'MovementCount',
                'type': dbus.types.UInt16,
                'offset': offset,
                'mask': 0x7FFF,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
            })
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
                'name': 'AnglePitch',
                'type': dbus.types.Byte,
                'offset': offset,
                'xlate': 'byteToSignedInt',
            })
            offset = offset + 1
            self.info['regs'].append({
                'name': 'AngleRoll',
                'type': dbus.types.Int16,
                'offset': 8,
                'flags': ['REG_FLAG_BIG_ENDIAN'],
            })
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

    def test_parsing(self):
        self._plog = ''
        failed = 0
        for test in [self.test_spec_example, self.test_sensor_1, self.test_sensor_2, self.test_beacon]:
            try:
                test()
            except AssertionError:
                failed += 1
                logging.error('Test failed !')

        if failed:
            logging.error(f"{failed} failed test(s) !")
        else:
            logging.info('Tests successful !')

    def test_spec_example(self):
        # Cf. https://wiki.teltonika-gps.com/view/EYE_SENSOR_/_BTSMP1#EYE_Sensor_Bluetooth%C2%AE_frame_parsing_example
        logging.info('Starting test test_spec_example')
        raw_data = b'\x01\xb7\x08\xb4\x12\x0c\xcb\x0b\xff\xc7\x67'
        self.configure(raw_data)
        #   01: Protocole version
        #   B7: Flags: B7=(MSB)1011 0111(LSB) => Bat volt on, low bat False, Angles on, Counter on, Mag state False, Mag on, Humidity on, Temp on
        #   08
        #   B4: Temperature: 08B4 = 2228, 2228 / 100 = 22.28°C
        #   12: Humidity: 12 = 18%
        #   0C
        #   CB: Counter: 0CCB=(MSB)0000 1100 1100 1011(LSB) => 0@MSB=Moving False, 000 1100 1100 1011=3275 moves
        #   0B: Pitch: 0B=11°
        #   FF
        #   C7: Roll: FFC7=-57°
        #   67: Battery voltage: 67=103, 2000 + (103 * 10) = 3030mV
        expected_dict = {
            'temperature': {
                'LowBattery': False,
                'Temperature': 22.28,
                'Humidity': 18,
                'MovementState': False,
                'MovementCount': 3275,
                'AnglePitch': 11,
                'AngleRoll': -57,
                'BatteryVoltage': 3030.0
            },
            'digitalinput': {
                'InputState': False,
                'LowBattery': False,
                'MovementState': False,
                'MovementCount': 3275,
                'AnglePitch': 11,
                'AngleRoll': -57,
                'BatteryVoltage': 3030.0
            }
        }

        logging.info(f"Parsing: {raw_data}")
        logging.info(f"Expected data: {expected_dict}")
        parsed_dict = self.parse_manufacturer_data(raw_data)
        logging.info(f"Parsed data: {parsed_dict}")
        assert parsed_dict == expected_dict

    def test_sensor_1(self):
        logging.info('Starting test test_sensor_1')
        raw_data = b'\x01\xbf\x06\xe6:\xe5g\xf9\x00zM'
        self.configure(raw_data)
        #   01: Protocole version
        #   BF: Flags: BF=(MSB)1011 1111(LSB) => Bat volt on, low bat False, Angles on, Counter on, Mag state True, Mag on, Humidity on, Temp on
        #   06
        #   E6: Temperature: 06E6 = 1766, 1766 / 100 = 17.66°C
        # :=3A: Humidity: 3A = 58%
        #   E5
        # g=67: Counter: E567=(MSB)1110 0101  0110 0111(LSB) => 1@MSB=Moving True, 110 0101  0110 0111=25959 moves
        #   F9: Pitch: F9=-7°
        #   00
        # z=7A: Roll: 007A=122
        # M=4D: Battery voltage: 4D=77, 2000 + (77 * 10) = 2770mV
        expected_dict = {
            'temperature': {
                'LowBattery': False,
                'Temperature': 17.66,
                'Humidity': 58,
                'MovementState': True,
                'MovementCount': 25959,
                'AnglePitch': -7,
                'AngleRoll': 122,
                'BatteryVoltage': 2770.0
            },
            'digitalinput': {
                'InputState': True,
                'LowBattery': False,
                'MovementState': True,
                'MovementCount': 25959,
                'AnglePitch': -7,
                'AngleRoll': 122,
                'BatteryVoltage': 2770.0
            }
        }

        logging.info(f"Parsing: {raw_data}")
        logging.info(f"Expected data: {expected_dict}")
        parsed_dict = self.parse_manufacturer_data(raw_data)
        logging.info(f"Parsed data: {parsed_dict}")
        assert parsed_dict == expected_dict

    def test_sensor_2(self):
        logging.info('Starting test test_sensor_2')
        raw_data = b'\x01\xd3\x06\xe6:\x65gM'
        self.configure(raw_data)
        #   01: Protocole version
        #   D3: Flags: D3=(MSB)1101 0011(LSB) => Bat volt on, low bat True, Angles off, Counter on, Mag state False, Mag off, Humidity on, Temp on
        #   06
        #   E6: Temperature: 06E6 = 1766, 1766 / 100 = 17.66°C
        # :=3A: Humidity: 3A = 58%
        #   65
        # g=67: Counter: 6567=(MSB)0110 0101  0110 0111(LSB) => 0@MSB=Moving False, 110 0101  0110 0111=25959 moves
        # M=4D: Battery voltage: 4D=77, 2000 + (77 * 10) = 2770mV
        expected_dict = {
            'temperature': {
                'LowBattery': True,
                'Temperature': 17.66,
                'Humidity': 58,
                'MovementState': False,
                'MovementCount': 25959,
                'BatteryVoltage': 2770.0
            }
        }

        logging.info(f"Parsing: {raw_data}")
        logging.info(f"Expected data: {expected_dict}")
        parsed_dict = self.parse_manufacturer_data(raw_data)
        logging.info(f"Parsed data: {parsed_dict}")
        assert parsed_dict == expected_dict

    def test_sensor_3(self):
        logging.info('Starting test test_sensor_3')
        raw_data = b'\x01\x8C\x67'
        self.configure(raw_data)
        #   01: Protocole version
        #   8C: Flags: 8C=(MSB)1000 1100(LSB) => Bat volt on, low bat False, Angles off, Counter off, Mag state True, Mag on, Humidity off, Temp off
        #   67: Battery voltage: 67=103, 2000 + (103 * 10) = 3030mV
        expected_dict = {
            'digitalinput': {
                'InputState': True,
                'LowBattery': False,
                'BatteryVoltage': 3030
            }
        }

        logging.info(f"Parsing: {raw_data}")
        logging.info(f"Expected data: {expected_dict}")
        parsed_dict = self.parse_manufacturer_data(raw_data)
        logging.info(f"Parsed data: {parsed_dict}")
        assert parsed_dict == expected_dict

    def test_beacon(self):
        logging.info('Starting test test_beacon')
        raw_data = b'\x01\xC0\x4D'
        self.configure(raw_data)
        #   01: Protocole version
        #   C0: Flags: C0=(MSB)1100 0000(LSB) => Bat volt on, low bat True, Angles off, Counter off, Mag state False, Mag off, Humidity off, Temp off
        # M=4D: Battery voltage: 4D=77, 2000 + (77 * 10) = 2770mV
        expected_dict = {}  # No roles...

        logging.info(f"Parsing: {raw_data}")
        logging.info(f"Expected data: {expected_dict}")
        parsed_dict = self.parse_manufacturer_data(raw_data)
        logging.info(f"Parsed data: {parsed_dict}")
        assert parsed_dict == expected_dict


def main():
    logging.basicConfig(level=logging.DEBUG)
    device = BleDeviceTeltonika('7cd9f411427d', 'PITCH_ROLL')
    device.test_parsing()


if __name__ == '__main__':
    main()
