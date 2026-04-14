"""Backend MQTT handler entry point.

Instantiates BrokerHandler and ModelDistributor, connects to the broker,
and provides an interactive CLI to manage edge devices.
"""

import json
import logging
import os
import signal
import sys
import threading

from .broker_handler import BrokerHandler
from .model_distributor import ModelDistributor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
Available commands:
  devices                          - List known edge devices
  admin <device_id> <json_command> - Send admin command to a device
  model <device_id> <file_path>    - Distribute a .pt model to a device
  help                             - Show this help
  quit / exit                      - Shut down
"""


def main():
    handler = BrokerHandler()
    distributor = ModelDistributor(mqtt_client=handler.client)
    handler.set_model_ack_callback(distributor.on_model_ack)

    logger.info("Backend MQTT handler starting...")

    try:
        handler.connect()
    except Exception:
        logger.exception("Failed to connect to broker")
        sys.exit(1)

    handler.loop_start()

    shutdown = False

    def handle_signal(sig, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if os.environ.get("MQTT_SERVICE_MODE"):
        # Non-interactive: block until signal instead of reading stdin.
        stop_event = threading.Event()

        def _stop(sig, _frame):
            nonlocal shutdown
            shutdown = True
            stop_event.set()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        logger.info("Running in service mode (MQTT_SERVICE_MODE)")
        stop_event.wait()
    else:
        print(HELP_TEXT)

        while not shutdown:
            try:
                user_input = input("backend> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            parts = user_input.split(None, 2)
            cmd = parts[0].lower()

            if cmd in ("quit", "exit"):
                break

            elif cmd == "help":
                print(HELP_TEXT)

            elif cmd == "devices":
                devices = handler.get_devices()
                if not devices:
                    print("  No devices seen yet.")
                else:
                    for dev_id, info in devices.items():
                        state = "ONLINE" if info.get("online") else "OFFLINE"
                        print(f"  {dev_id}: {state} (last_seen={info.get('last_seen', '?')})")

            elif cmd == "admin":
                if len(parts) < 3:
                    print("  Usage: admin <device_id> <json_command>")
                    continue
                device_id = parts[1]
                try:
                    command = json.loads(parts[2])
                except json.JSONDecodeError:
                    print("  Error: invalid JSON")
                    continue
                handler.send_admin(device_id, command)
                print(f"  Admin command sent to {device_id}")

            elif cmd == "model":
                if len(parts) < 3:
                    print("  Usage: model <device_id> <file_path>")
                    continue
                device_id = parts[1]
                file_path = parts[2]
                print(f"  Distributing model {file_path} to {device_id}...")
                success = distributor.distribute_model(device_id, file_path)
                if success:
                    print("  Model delivered successfully.")
                else:
                    print("  Model delivery failed. Check logs for details.")

            else:
                print(f"  Unknown command: {cmd}")
                print(HELP_TEXT)

    logger.info("Shutting down backend handler...")
    handler.disconnect()
    handler.loop_stop()


if __name__ == "__main__":
    main()
