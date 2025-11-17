#!/bin/sh
#
# Start script for dbus-ble-sensors-py
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

get_setting() {
  dbus-send --print-reply=literal --system --type=method_call \
  --dest=com.victronenergy.settings $1 com.victronenergy.BusItem.GetValue |
  awk '/int32/ { print $3 }'
}

if [ -z "$(ls /sys/class/bluetooth)" ]; then
  echo "Error: No bluetooth device detected, cancelling service launch"
  svc -d .
  exit 1
fi

if [ "$(get_setting /Settings/Services/BleSensors)" != 1 ]; then
  echo "Error: Bluetooth service deactivated by configuraion, cancelling service launch"
  svc -d .
  exit 1
fi

exec python3 "$SCRIPT_DIR/dbus_ble_sensors.py"
