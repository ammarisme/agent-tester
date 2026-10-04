import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p>The page you&apos;re looking for doesn&apos;t exist or was deleted.</p>
      <Link href="/" className="btn btn-primary">
        Back to overview
      </Link>
    </div>
  );
}
