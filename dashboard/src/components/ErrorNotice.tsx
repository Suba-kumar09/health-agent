import "./ErrorNotice.css";

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="error-notice">
      <span className="error-notice__dot" aria-hidden="true" />
      <p className="error-notice__text">{message}</p>
    </div>
  );
}
