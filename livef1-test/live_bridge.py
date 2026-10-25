
import asyncio
import json
import threading
from datetime import datetime, timezone

from livef1.adapters.realtime_client import RealF1Client
from websockets.asyncio.server import serve

HOST = "127.0.0.1"
PORT = 8765

TOPICS = [
    "SessionInfo",
    "DriverList",
    "TimingData",
    "TimingAppData",
    "Position.z",
    "CarData.z",
]

clients = set()
latest = {}
server_loop = None
ready = threading.Event()

STATE_TOPICS = {
    "DriverList": "RacingNumber",
    "TimingData": "DriverNo",
    "TimingAppData": "DriverNo",
}


def serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def records_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def merge_state(topic, payload):
    id_field = STATE_TOPICS[topic]

    previous = {
        str(record[id_field]): record
        for record in latest.get(topic, [])
        if isinstance(record, dict)
        and record.get(id_field) is not None
    }

    for record in records_list(payload):
        if not isinstance(record, dict):
            continue

        number = record.get(id_field)

        if number is None:
            continue

        key = str(number)

        previous[key] = {
            **previous.get(key, {}),
            **record,
        }

    latest[topic] = list(previous.values())


async def handle_connection(websocket):
    clients.add(websocket)
    print(f"Browser connected ({len(clients)} clients)")

    try:
        for topic, payload in list(latest.items()):
            await websocket.send(
                json.dumps(
                    {
                        "topic": topic,
                        "records": payload,
                    },
                    default=serialize,
                )
            )

        async for _ in websocket:
            pass

    finally:
        clients.discard(websocket)
        print("Browser disconnected")


async def broadcast(message):
    if not clients:
        return

    data = json.dumps(message, default=serialize)
    recipients = tuple(clients)

    results = await asyncio.gather(
        *(ws.send(data) for ws in recipients),
        return_exceptions=True,
    )

    for ws, result in zip(recipients, results):
        if isinstance(result, Exception):
            clients.discard(ws)


async def start_server():
    global server_loop

    server_loop = asyncio.get_running_loop()

    async with serve(
        handle_connection,
        HOST,
        PORT,
        max_size=8 * 1024 * 1024,
    ):
        print(f"WebSocket server running at ws://{HOST}:{PORT}")
        ready.set()
        await asyncio.Future()


def run_server():
    asyncio.run(start_server())


threading.Thread(
    target=run_server,
    daemon=True,
).start()

if not ready.wait(timeout=10):
    raise RuntimeError("WebSocket server failed to start")


client = RealF1Client(topics=TOPICS)


@client.callback("dashboard_bridge")
async def forward(records):
    if not isinstance(records, dict):
        return

    for topic, payload in records.items():
        if not payload:
            continue

        if topic in STATE_TOPICS:
            merge_state(topic, payload)
        else:
            latest[topic] = payload

        count = (
            len(payload)
            if isinstance(payload, list)
            else 1
        )

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"{topic}: {count} records"
        )

        message = {
            "topic": topic,
            "records": payload,
            "receivedAt": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        server_loop.call_soon_threadsafe(
            lambda m=message: asyncio.create_task(
                broadcast(m)
            )
        )


print("Starting LiveF1 connection...")
print("Press CTRL+C to stop.\n")

try:
    client.run()
except KeyboardInterrupt:
    print("\nLiveF1 bridge stopped.")
