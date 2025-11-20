import logging
from ble_role import BleRole


class BleRoleDigitalInput(BleRole):

    MAXCOUNT = 2**31-1

    INPUT_TYPES = {
        0: 'Disabled',
        1: 'Pulse meter',
        2: 'Door alarm',
        3: 'Bilge pump',
        4: 'Bilge alarm',
        5: 'Burglar alarm',
        6: 'Smoke alarm',
        7: 'Fire alarm',
        8: 'CO2 alarm',
        9: 'Generator',
        10: 'Generic I/O',  # Is it ? Gui V2 says not used...
        11: 'Touch enable',
    }

    INPUT_STATE = {
        0: 'Low',
        1: 'High',
        2: 'Off',
        3: 'On',
        4: 'No',
        5: 'Yes',
        6: 'Open',
        7: 'Closed',
        8: 'OK',
        9: 'Alarm',
        10: 'Running',
        11: 'Stopped',
    }

    ALARM_STATE = {
        0: 'OK',
        1: 'Warning',
        2: 'Alarm'
    }

    def __init__(self):
        super().__init__()
        self._input_state = 0

        self.info.update(
            {
                'name': 'digitalinput',
                'dev_instance': 1,
                # Device 'regs' must contains at least an 'InputState' element
                'settings': [
                    {
                        'name': 'Count',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': self.MAXCOUNT
                        }
                    },
                    {
                        'name': 'Type',
                        'props': {
                            'def': 2,
                            'min': 0,
                            'max': 11
                        }
                    },
                    {
                        'name': 'Settings/AlarmSetting',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    },
                    {
                        'name': 'Settings/InvertAlarm',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    },
                    {
                        'name': 'Settings/InvertTranslation',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    },
                ],
            }
        )

    @staticmethod
    def _get_state_offset(_type: int) -> int:
        match _type:
            case 10:  # Low / High
                return 0
            case 3:  # Off / On
                return 2
            # case : # No / Yes
            #    return 4
            case 2:  # Open / Closed
                return 6
            case 4 | 5 | 6 | 7 | 8:  # Ok / Alarm
                return 8
            case 9:  # Running / Stopped
                return 10
            case _:  # types 0, 1, 11 do not generate digital input service
                return None
        return None

    def _get_alarm(self, dbus_service, input_state: bool) -> int:
        invert_alarm: bool = dbus_service.get_value('InvertAlarm')
        alarm_setting: bool = dbus_service.get_value('AlarmSetting')
        return 2 * bool((input_state ^ invert_alarm) and alarm_setting)

    def _get_state(self, dbus_service, input_state: bool) -> int:
        _type = dbus_service.get_value('Type')
        invert_translation: bool = dbus_service.get_value('InvertTranslation')
        return self._get_state_offset(_type) + (input_state ^ invert_translation)

    def _inc_count(self, dbus_service):
        count = (int(dbus_service.get_value('Count')) + 1) % self.MAXCOUNT
        dbus_service.set_value('Count', count)

    def update_data(self, dbus_service, sensor_data: dict):
        input_state = sensor_data['InputState']
        dbus_service.set_value('Alarm', self._get_alarm(dbus_service, input_state))
        dbus_service.set_value('State', self._get_state(dbus_service, input_state))
        if input_state != self._input_state:
            self._inc_count(dbus_service)
