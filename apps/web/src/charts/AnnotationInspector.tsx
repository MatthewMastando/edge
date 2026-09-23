import { formatInstant } from "../lib/format";
import type { AnnotationView } from "./annotations";

export function AnnotationInspector({ annotation }: { annotation: AnnotationView | null }) {
  if (!annotation) {
    return (
      <aside className="inspector" aria-live="polite">
        <h3>Annotation</h3>
        <p className="hint">Select an annotation to see the calculation and the confirmation time.</p>
      </aside>
    );
  }
  return (
    <aside className="inspector" aria-live="polite" data-testid="inspector">
      <h3>{annotation.label}</h3>
      <dl className="meta-grid">
        <div>
          <dt>Detector</dt>
          <dd>{annotation.detector}</dd>
        </div>
        <div>
          <dt>Confirmation</dt>
          <dd>{annotation.confirmationTime ? formatInstant(annotation.confirmationTime) : "Pending — not confirmed"}</dd>
        </div>
      </dl>
      <p className="calculation">{annotation.calculation}</p>
      {annotation.parameters.length > 0 ? (
        <ul className="param-list">
          {annotation.parameters.map((parameter) => (
            <li key={parameter.name}>
              <span>{parameter.name}</span>
              <span className="num">{parameter.value}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </aside>
  );
}
