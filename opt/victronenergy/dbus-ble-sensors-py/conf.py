import os


# Project variables
PROCESS_NAME = os.path.basename(os.path.dirname(__file__))
PROCESS_VERSION = '1.0.0'

# Timeouts
DBUS_ROLE_SERVICES_TIMEOUT = 1800  # 30 min
SCAN_TIMEOUT = 15
SCAN_INTERVAL_STANDARD = 20  # 90
SCAN_SLEEP = SCAN_INTERVAL_STANDARD - SCAN_TIMEOUT
