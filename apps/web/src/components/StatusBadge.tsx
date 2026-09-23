import type { Run } from "../api/types";
import { runStatusLabel } from "../lib/format";

export function StatusBadge({ status }: { status: Run["status"] }) {
  return (
    <span className={`badge badge-${status}`} data-status={status}>
      {runStatusLabel(status)}
    </span>
  );
}
