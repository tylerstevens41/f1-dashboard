
import { useState } from "react";
import AustinReplay from "./AustinReplay";
import ReplayRace from "./ReplayRace";
import LiveSession from "./LiveSession";

export default function LiveRace() {
  const [mode, setMode] = useState("live");

  return (
    <>
      <div
        style={{
          display: "flex",
          gap: 10,
          padding: "14px 24px",
        }}
      >
        <button
          type="button"
          onClick={() => setMode("live")}
          aria-pressed={mode === "live"}
        >
          {mode === "live" ? "● LIVE" : "LIVE"}
        </button>

        {import.meta.env.DEV && <button
          type="button"
          onClick={() => setMode("replay")}
          aria-pressed={mode === "replay"}
        >
          {mode === "replay" ? "● LEGACY OPENF1" : "LEGACY OPENF1"}
        </button>}
        {import.meta.env.DEV && <button type="button" onClick={() => setMode("austin")} aria-pressed={mode === "austin"}>Legacy Austin Replay</button>}
      </div>

      {mode === "live" ? <LiveSession /> : mode === "austin" ? <AustinReplay /> : <ReplayRace />}
    </>
  );
}
