import styles from "./RecordingDownloadIconButton.module.css";

interface RecordingDownloadIconButtonProps {
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}

const DEFAULT_TITLE = "Download original recording";

export function RecordingDownloadIconButton({
  onClick,
  disabled,
  title = DEFAULT_TITLE,
}: RecordingDownloadIconButtonProps) {
  return (
    <button
      type="button"
      className={styles.btn}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
    >
      <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm7-3c0 3.53-2.61 6.44-6 6.93V21h-2v-3.07c-3.39-.49-6-3.4-6-6.93h2c0 2.76 2.24 5 5 5s5-2.24 5-5h2z"
        />
      </svg>
    </button>
  );
}
