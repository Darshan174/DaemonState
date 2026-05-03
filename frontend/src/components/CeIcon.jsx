export default function CeIcon({ size = 40, className = "" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <rect width="40" height="40" rx="9" fill="url(#ce-g)" />
      <line x1="20" y1="20" x2="20" y2="8" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <line x1="20" y1="20" x2="30.4" y2="14" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <line x1="20" y1="20" x2="30.4" y2="26" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <line x1="20" y1="20" x2="20" y2="32" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <line x1="20" y1="20" x2="9.6" y2="26" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <line x1="20" y1="20" x2="9.6" y2="14" stroke="white" strokeWidth="1.3" strokeOpacity="0.45" strokeLinecap="round" />
      <polygon points="20,8 30.4,14 30.4,26 20,32 9.6,26 9.6,14" fill="none" stroke="white" strokeWidth="0.75" strokeOpacity="0.22" />
      <circle cx="20" cy="8"  r="2.2" fill="white" fillOpacity="0.9" />
      <circle cx="30.4" cy="14" r="2.2" fill="white" fillOpacity="0.8" />
      <circle cx="30.4" cy="26" r="2.2" fill="white" fillOpacity="0.8" />
      <circle cx="20" cy="32" r="2.2" fill="white" fillOpacity="0.9" />
      <circle cx="9.6"  cy="26" r="2.2" fill="white" fillOpacity="0.8" />
      <circle cx="9.6"  cy="14" r="2.2" fill="white" fillOpacity="0.8" />
      <circle cx="20" cy="20" r="4" fill="white" />
      <defs>
        <linearGradient id="ce-g" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stopColor="#4338ca" />
          <stop offset="100%" stopColor="#7c3aed" />
        </linearGradient>
      </defs>
    </svg>
  );
}
