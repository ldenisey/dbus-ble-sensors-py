import logging
from ble_role import BleRole


class BleRoleTemperature(BleRole):

    TEMPERATURE_TYPES = {
        0: 'Battery',
        1: 'Fridge',
        2: 'Generic',
        3: 'Room',
        4: 'Outdoor',
        5: 'WaterHeater',
        6: 'Freezer'
    }

    def __init__(self):
        super().__init__()

        self.info.update(
            {
                'name': 'temperature',
                'dev_instance': 20,
                # 'regs' must contains at least a 'Temperature' element
                'settings': [
                    {
                        'name': 'TemperatureType',
                        'props': {
                            'def': 2,
                            'min': 0,
                            'max': 6
                        }
                    },
                    {
                        'name': 'Offset',
                        'props': {
                            'def': 0,
                            'min': -100,
                            'max': 100
                        },
                        'onchange': '_offset_update_temp'
                    },
                ],
            },
        )
        self._raw_temp = 0

    def update(self, dbus_service, sensor_data: dict):
        # Keeping track of sensor latest value for multiple offset updates use case
        self._raw_temp = sensor_data['Temperature']

        # Apply offset to temperature value
        if (offset := dbus_service.get_value('Offset')):
            sensor_data['Temperature'] = self._raw_temp + offset

    # def _offset_update_temp(self, new_value):
    def _offset_update_temp(self, _dbus_service, new_value):
        logging.debug(f"{self._plog} Updating temp from offset: sensor temp:{self._raw_temp}, offset value:{new_value}")
        _dbus_service.set_value('Temperature', self._raw_temp + new_value)
