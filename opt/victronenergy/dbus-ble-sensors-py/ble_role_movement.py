from ble_role import BleRole


class BleRoleDigitalInput(BleRole):

    ALARM_STATE = {
        0: 'OK',
        1: 'Warning',
        2: 'Alarm'
    }

    def __init__(self):
        super().__init__()
        self._count = -1

        self.info.update(
            {
                'name': 'movement',
                'dev_instance': 1,
                # Device 'regs' must contains at least a 'MovementState' or a 'MovementCount' element
                'settings': [
                    {
                        'name': 'Settings/AlarmSetting',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    }
                ],
            }
        )

    def _get_alarm(self, dbus_service, sensor_data: dict) -> int:
        if dbus_service.get_value('AlarmSetting') is False:
            return 0
        if (movement_state := sensor_data['MovementState']) is None:
            if self._count != -1:
                return 2 * (self._count != sensor_data['MovementCount'])
        else:
            return 2 * movement_state
        return 0

    def update(self, dbus_service, sensor_data: dict):
        dbus_service.set_value('Alarm', self._get_alarm(dbus_service, sensor_data))
        self._count = sensor_data['MovementCount']
