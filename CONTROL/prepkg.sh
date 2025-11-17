#!/bin/bash
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

# Setting shell rights
chmod +x "$SCRIPT_DIR/postinst" "$SCRIPT_DIR/postrm"
chmod +x "$SCRIPT_DIR/../opt/victronenergy/dbus-ble-sensors-py/start-dbus-ble-sensors-py.sh"
chmod +x "$SCRIPT_DIR/../opt/victronenergy/service/dbus-ble-sensors-py/run"
chmod +x "$SCRIPT_DIR/../opt/victronenergy/service/dbus-ble-sensors-py/log/run"
