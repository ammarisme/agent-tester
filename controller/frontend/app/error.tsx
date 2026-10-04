"use client";

import { useEffect } from "react";

export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="empty">
      <h1>Something went wrong</h1>
      <p>This page hit an unexpected error. Your data is safe; try again, and if it keeps happening, please report it with the message below.</p>
      <pre className="code" style={{ maxWidth: 640, textAlign: "left" }}>
        {error.message}
        {error.digest && `\n\ndigest: ${error.digest}`}
      </pre>
      <button type="button" className="btn btn-primary" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
