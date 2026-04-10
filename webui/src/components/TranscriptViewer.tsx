import type { TranscriptSegment } from "../types";
import styles from "./TranscriptViewer.module.css";

interface TranscriptViewerProps {
  segments: TranscriptSegment[];
  className?: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function TranscriptViewer({ segments, className }: TranscriptViewerProps) {
  if (!segments?.length) {
    return (
      <div className={`${styles.wrapper} ${className ?? ""}`}>
        <p className={styles.empty}>No transcript available.</p>
      </div>
    );
  }

  return (
    <div className={`${styles.wrapper} ${className ?? ""}`}>
      <div className={styles.segments}>
        {segments.map((seg, i) => (
          <div key={i} className={styles.segment}>
            <div className={styles.segmentHeader}>
              <span className={styles.speaker}>{seg.speaker}</span>
              <span className={styles.timestamps}>
                {formatTime(seg.start)} – {formatTime(seg.end)}
              </span>
            </div>
            <p className={styles.text}>{seg.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
