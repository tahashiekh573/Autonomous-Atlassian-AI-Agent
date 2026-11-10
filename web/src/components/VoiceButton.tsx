import { useRef, useState } from "react";

interface Props {
  disabled?: boolean;
  onRecorded: (audio: Blob) => void;
  onError: (message: string) => void;
}

/** Push to start, push to stop. Records WebM/Opus with MediaRecorder. */
export function VoiceButton({ disabled, onRecorded, onError }: Props) {
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      onError("This browser cannot record audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size > 0) onRecorded(blob);
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
    } catch {
      onError("Microphone permission was denied.");
    }
  }

  function stop() {
    recorder.current?.stop();
    recorder.current = null;
    setRecording(false);
  }

  return (
    <button
      type="button"
      className={`mic ${recording ? "recording" : ""}`}
      disabled={disabled && !recording}
      onClick={recording ? stop : start}
      aria-pressed={recording}
      aria-label={recording ? "Stop recording and send" : "Record a voice command"}
      title={recording ? "Stop and send" : "Voice command (English, Urdu, Roman Urdu)"}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        {recording ? (
          <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
        ) : (
          <>
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </>
        )}
      </svg>
    </button>
  );
}
