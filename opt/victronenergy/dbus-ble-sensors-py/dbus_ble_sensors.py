#!/usr/bin/env python3
import sys
import os
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))
import logging
import asyncio
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from argparse import ArgumentParser
from ble_device import BleDevice
from ble_role import BleRole
from dbus_ble_service import DbusBleService
from dbus_settings_service import DbusSettingsService
import bleak
import gbulb
from logger import setup_logging
from conf import SCAN_TIMEOUT, SCAN_SLEEP


class DbusBleSensors(object):
    """
    Main class for the D-bus BLE Sensors python service.
    Extends base C service 'dbus-ble-sensors' to allow community integration of any BLE sensors.
    # TODO Clarify device/sensor naming

    Cf.
    - https://github.com/victronenergy/dbus-ble-sensors/
    - https://github.com/victronenergy/node-red-contrib-victron/blob/master/src/nodes/victron-virtual.js
    - https://github.com/victronenergy/gui-v2/blob/main/data/mock/conf/services/tank-lpg.json
    - https://github.com/victronenergy/dbus-recorder/blob/master/demo2_water.csv
    - https://github.com/victronenergy/gui-v2/blob/main/data/mock/conf/services/ruuvi-salon.json
    """

    def __init__(self):
        # Get dbus, default is system
        self._dbus: dbus.Bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        # Accessor to dbus settings service (default : com.victronenergy.settings)
        self._dbus_settings_service = DbusSettingsService()
        # Accessor to dbus ble dedicated service (default : com.victronenergy.ble)
        self._dbus_ble_service = DbusBleService()

        # Initialze BT adapters search
        self._adapters = []
        self._list_adapters()

        # Knowned device lists
        self._known_mac = {}
        self._ignored_mac = []

        # Load definition classes
        BleRole.load_instances(os.path.abspath(__file__))
        BleDevice.load_classes(os.path.abspath(__file__))

    def _list_adapters(self):
        # Adding callback for futur connections/disconnections
        self._dbus.add_signal_receiver(
            self._on_interfaces_added,
            dbus_interface='org.freedesktop.DBus.ObjectManager',
            signal_name='InterfacesAdded'
        )
        self._dbus.add_signal_receiver(
            self._on_interfaces_removed,
            dbus_interface='org.freedesktop.DBus.ObjectManager',
            signal_name='InterfacesRemoved'
        )

        # Initial search for adapters
        object_manager = dbus.Interface(
            self._dbus.get_object('org.bluez', '/'),
            'org.freedesktop.DBus.ObjectManager'
        )
        objects = object_manager.GetManagedObjects()
        for path, ifaces in objects.items():
            self._on_interfaces_added(path, ifaces)

    def _on_interfaces_added(self, path, interfaces):
        if not str(path).startswith('/org/bluez'):
            return
        name = path.split('/')[-1]
        if 'org.bluez.Adapter1' in interfaces:
            adapter = self._dbus.get_object('org.bluez', path)
            props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')
            mac = props.Get('org.bluez.Adapter1', 'Address')
            logging.info(f"{name}: adding adapter, path='{path}', address='{mac}'")
            self._adapters.append(name)
            self._dbus_ble_service.add_ble_adapter(name, mac)

    def _on_interfaces_removed(self, path, interfaces):
        if not str(path).startswith('/org/bluez'):
            return
        name = path.split('/')[-1]
        if 'org.bluez.Adapter1' in interfaces:
            # Remove adapter
            self._dbus_ble_service.remove_ble_adapter(name)
            self._adapters.remove(name)
            logging.info(f"{name}: adapter removed")

    async def _scan(self, adapter: str):
        def _scan_callback(device, advertisement_data):
            dev_mac = "".join(device.address.split(':')).lower()
            if dev_mac in self._ignored_mac:
                # Ignoring devices already evaluated
                return

            dev_name = device.name
            plog = f"{dev_mac} - {dev_name}:"
            logging.debug(f"{plog} received advertisement '{advertisement_data}'")
            if advertisement_data.manufacturer_data is None or len(advertisement_data.manufacturer_data) < 1:
                logging.info(f"{plog} ignoring, device without manufacturer data")
                self._ignored_mac.append(dev_mac)
                return

            # First time device initialization
            # Loop through manufacturer data fields, even though most devices only use one
            for man_id, man_data in advertisement_data.manufacturer_data.items():
                if dev_mac not in self._known_mac.keys():
                    device_class = BleDevice.DEVICE_CLASSES.get(man_id, None)
                    if device_class is None:
                        logging.info(f"{plog} ignoring, no device configuration class for manufacturer '{man_id}'")
                        self._ignored_mac.append(dev_mac)
                        return

                    # Run device specific parsing
                    logging.info(f"{plog} initializing device with class {device_class}")
                    dev_instance = device_class(dev_mac, dev_name)
                    dev_instance.configure(man_data)
                    dev_instance.init()
                    self._known_mac[dev_mac] = dev_instance
                else:
                    dev_instance = self._known_mac[dev_mac]

                # Parsing data
                logging.info(f"{plog} received manufacturer data: {man_data}")
                dev_instance.handle_data(man_data)

        logging.debug(f"{adapter}: Scanning ...")
        try:
            await bleak.BleakScanner.discover(
                timeout=SCAN_TIMEOUT,
                adapter=adapter,
                return_adv=True,
                detection_callback=_scan_callback
            )
            logging.debug(f"{adapter}: Scan finished")
        except Exception:
            logging.exception(f"{adapter}: Scan error")

    async def scan_loop(self):
        while True:
            if len(self._adapters) < 1:
                logging.warn("Waiting for a bluetooth adapter...")
                await asyncio.sleep(5)
                continue
            scan_tasks = [asyncio.create_task(self._scan(adapter)) for adapter in self._adapters]
            await asyncio.gather(*scan_tasks)

            if self._dbus_ble_service.get_continuous_scan():
                logging.debug(f"{self._adapters}: continuous scan on, restarting scan immediately")
            else:
                logging.debug(f"{self._adapters}: continuous scan off, pausing for {SCAN_SLEEP} seconds")
                await asyncio.sleep(SCAN_SLEEP)


def main():
    parser = ArgumentParser(description=sys.argv[0])
    parser.add_argument('--debug', '-d', help='Turn on debug logging', default=False, action='store_true')
    args = parser.parse_args()
    setup_logging(args.debug)
    if args.debug:
        # Mute overly verbose libraries
        logging.getLogger("bleak").setLevel(logging.INFO)

    # Init gbulb, configure GLib and integrate asyncio in it
    gbulb.install()
    DBusGMainLoop(set_as_default=True)
    asyncio.set_event_loop_policy(gbulb.GLibEventLoopPolicy())

    pvac_output = DbusBleSensors()

    mainloop = asyncio.new_event_loop()
    asyncio.set_event_loop(mainloop)
    asyncio.get_event_loop().create_task(pvac_output.scan_loop())
    logging.info('Starting service')
    mainloop.run_forever()


if __name__ == "__main__":
    main()
