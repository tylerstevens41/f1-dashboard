
from datetime import datetime
from collections import Counter

from livef1.adapters.realtime_client import RealF1Client


# ==========================================
# CONFIGURATION
# ==========================================

TOPICS = [
    "SessionInfo",
    "TimingData",
    "Position.z",
    "CarData.z",
]

print("Starting LiveF1 feed diagnostic...")
print("Monitoring raw feed topics and processed records...")
print("Press CTRL+C to stop.\n")


# ==========================================
# CREATE LIVEF1 CLIENT
# ==========================================

client = RealF1Client(topics=TOPICS)

message_counts = Counter()
sample_counts = Counter()
raw_counts = Counter()


# ==========================================
# RAW FEED MONITOR
# ==========================================

# Save the original dispatcher so we can
# continue processing messages normally.

original_dispatch = client._dispatch


async def debug_dispatch(frame):

    # Live feed messages
    if frame.get("target") == "feed":

        arguments = frame.get("arguments") or []

        if arguments:
            topic = arguments[0]
            raw_counts[topic] += 1

            # Avoid flooding the terminal with TimingData.
            if topic != "TimingData":
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"RAW FEED TOPIC: {topic}"
                )

    # Initial subscription snapshot
    elif frame.get("type") == 3:

        if frame.get("error"):
            print(
                "SUBSCRIPTION ERROR:",
                frame["error"]
            )

        result = frame.get("result")

        if isinstance(result, dict):
            print("\n========== INITIAL SNAPSHOT ==========")
            print("Topics returned by server:")

            for topic, data in result.items():
                print(
                    f"  {topic}: "
                    f"{type(data).__name__}"
                )

            print("======================================\n")

    # Pass the frame to LiveF1's normal processing.
    await original_dispatch(frame)


# Install raw feed monitor
client._dispatch = debug_dispatch


# ==========================================
# PROCESSED DATA CALLBACK
# ==========================================

@client.callback("feed_diagnostic")
async def handle_data(records):

    if not isinstance(records, dict):
        print(
            "Unexpected message format:",
            type(records).__name__
        )
        return

    for topic, payload in records.items():

        message_counts[topic] += 1

        if payload:

            sample_counts[topic] += 1

            # Print all telemetry updates.
            # Only print the first few timing updates.
            should_print = (
                topic != "TimingData"
                or sample_counts[topic] <= 3
            )

            if should_print:

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"PROCESSED: {topic}"
                )

                # Show fields for the first message.
                if sample_counts[topic] == 1:

                    if isinstance(payload, list):

                        print(
                            "  Records in first message:",
                            len(payload)
                        )

                        if payload and isinstance(payload[0], dict):
                            print(
                                "  Sample fields:",
                                list(payload[0].keys())[:20]
                            )

                    else:
                        print(
                            "  Data type:",
                            type(payload).__name__
                        )


# ==========================================
# START LIVE CONNECTION
# ==========================================

try:
    client.run()

except KeyboardInterrupt:
    print("\nDiagnostic stopped.")

finally:

    print("\n========== FEED SUMMARY ==========")

    for topic in TOPICS:

        print(
            f"{topic:15} "
            f"raw={raw_counts[topic]:5} "
            f"processed={message_counts[topic]:5} "
            f"non-empty={sample_counts[topic]:5}"
        )

    print("==================================")
