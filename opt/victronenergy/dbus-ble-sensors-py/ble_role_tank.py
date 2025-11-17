from ble_role import BleRole


class BleRoleTank(BleRole):
    """
    Tank level sensor role class.
    Device claiming this role must provide a 'Level' item.

    Methods to compute high and low level alarms are provided, but can be overloaded by device class.
    """

    def __init__(self):
        super().__init__()

        self.info.update(
            {
                'name': 'tank',
                'dev_instance': 20,
                'settings': [
                    {
                        'name': '/Alarms/High/Enable',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    },
                    {
                        'name': '/Alarms/High/Active',
                        'props': {
                            'def': 90,
                            'min': 0,
                            'max': 100
                        }
                    },
                    {
                        'name': '/Alarms/High/Restore',
                        'props': {
                            'def': 80,
                            'min': 0,
                            'max': 100
                        }
                    },
                    {
                        'name': '/Alarms/Low/Enable',
                        'props': {
                            'def': 0,
                            'min': 0,
                            'max': 1
                        }
                    },
                    {
                        'name': '/Alarms/Low/Active',
                        'props': {
                            'def': 10,
                            'min': 0,
                            'max': 100
                        }
                    },
                    {
                        'name': '/Alarms/Low/Restore',
                        'props': {
                            'def': 15,
                            'min': 0,
                            'max': 100
                        }
                    },
                ],
                'alarms': [
                    {
                        'name': '/Alarms/High/State',
                        'update': self.get_alarm_high_state  # Can be overloaded by device class
                    },
                    {
                        'name': '/Alarms/Low/State',
                        'update': self.get_alarm_low_state  # Can be overloaded by device class
                    },
                ]
            }
        )

    def get_alarm_high_state(self, role_service) -> int:
        """
        Default method to compute tank high level alarm. Can be overridden by overloading info['alarms'] entries in device class.
        """

        if role_service['/Alarms/High/Enable']:
            alarm_state = bool(role_service['/Alarms/High/State'])
            alarm_threshold = role_service[f"/Alarms/High/{"Restore" if alarm_state else "Active"}"]
            tank_level = float(role_service['Level'])
            return int(tank_level > alarm_threshold)
        else:
            return 0

    def get_alarm_low_state(self, role_service) -> int:
        """
        Default method to compute tank low level alarm. Can be overridden by overloading info['alarms'] entries in device class.
        """

        if role_service['/Alarms/Low/Enable']:
            alarm_state = bool(role_service['/Alarms/Low/State'])
            alarm_threshold = role_service[f"/Alarms/Low/{"Restore" if alarm_state else "Active"}"]
            tank_level = float(role_service['Level'])
            return int(tank_level < alarm_threshold)
        else:
            return 0
