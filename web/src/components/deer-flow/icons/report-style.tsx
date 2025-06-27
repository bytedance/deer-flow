export function ReportStyle({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      version="1.1"
      width="800px"
      height="800px"
      viewBox="0 0 24 24"
      fill="none"
    >
      <g fill="currentcolor">
        <path
          d="M4 4C4 3.44772 4.44772 3 5 3H19C19.5523 3 20 3.44772 20 4V20C20 20.5523 19.5523 21 19 21H5C4.44772 21 4 20.5523 4 20V4Z"
          stroke="currentColor"
          strokeWidth="2"
          fill="none"
        />
        <path
          d="M8 7H16"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <path
          d="M8 11H16"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <path
          d="M8 15H12"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle
          cx="16"
          cy="15"
          r="2"
          fill="currentColor"
        />
      </g>
    </svg>
  );
}
