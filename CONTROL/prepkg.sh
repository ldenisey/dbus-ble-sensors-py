#!/bin/bash
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

# Setting shell rights
chmod +x "$SCRIPT_DIR/postinst" "$SCRIPT_DIR/postrm" "$SCRIPT_DIR/../opt/victronenergy/service/dbus-ble-sensors-py/*.sh"
