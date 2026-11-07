function title(value) {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function dateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

export default function BankOverview({ dashboard, busy }) {
  if (!dashboard) {
    return (
      <section className="panel bank-empty" role="status">
        {busy
          ? "Loading bank overview…"
          : "Dashboard data is unavailable. Use Refresh to try again."}
      </section>
    );
  }

  const metrics = [
    [
      "Applications",
      dashboard.applications,
      `${dashboard.archived_applications} archived`,
    ],
    [
      "Active assignments",
      dashboard.active_assignments,
      "Currently assigned for review",
    ],
    [
      "Awaiting assignment",
      dashboard.awaiting_assignment,
      "Waiting for reviewer capacity",
    ],
    [
      "Available reviewers",
      dashboard.available_reviewers,
      `of ${dashboard.active_reviewers} active reviewers`,
    ],
  ];
  const statusCounts = Object.entries(dashboard.status_counts || {});

  return (
    <div className="bank-overview">
      <div className="bank-stats">
        {metrics.map(([label, value, detail]) => (
          <article className="bank-metric" key={label}>
            <small>{label}</small>
            <b>{value}</b>
            <span>{detail}</span>
          </article>
        ))}
      </div>
      <div className="bank-overview-grid">
        <section className="panel">
          <div className="bank-section-head">
            <div>
              <h2>Application pipeline</h2>
              <p>Current application statuses for your bank.</p>
            </div>
          </div>
          {statusCounts.length ? (
            <div className="bank-pipeline">
              {statusCounts.map(([status, count]) => (
                <div key={status}>
                  <span>{title(status)}</span>
                  <b>{count}</b>
                </div>
              ))}
            </div>
          ) : (
            <p className="bank-empty">
              No applications are currently in the pipeline.
            </p>
          )}
          {dashboard.escalated > 0 && (
            <div className="bank-alert critical">
              <b>
                {dashboard.escalated} escalated{" "}
                {dashboard.escalated === 1 ? "application" : "applications"}
              </b>
              <span>
                Review the application queue for items requiring attention.
              </span>
            </div>
          )}
          {dashboard.documents_requested > 0 && (
            <div className="bank-alert">
              <b>
                {dashboard.documents_requested} application(s) need documents
              </b>
              <span>
                Customers have been asked to provide additional information.
              </span>
            </div>
          )}
          <p className="bank-workflow-note">
            Assignments are handled automatically by the review workflow.
          </p>
        </section>
        <section className="panel">
          <div className="bank-section-head">
            <div>
              <h2>Reviewer workload</h2>
              <p>Active assignments and availability across your team.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>REVIEWER</th>
                  <th>ACTIVE / CAPACITY</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {(dashboard.reviewer_workload || []).map((reviewer) => (
                  <tr key={reviewer.id}>
                    <td>
                      {reviewer.full_name}
                      <small>{title(reviewer.specialisation)}</small>
                    </td>
                    <td>
                      {reviewer.active_assignments} /{" "}
                      {reviewer.max_active_assignments}
                    </td>
                    <td>
                      <span
                        className={`bank-state ${reviewer.available ? "status-good" : ""}`}
                      >
                        {reviewer.available
                          ? "Available"
                          : !reviewer.active
                            ? "Inactive"
                            : reviewer.active_assignments >=
                                reviewer.max_active_assignments
                              ? "At capacity"
                              : "Unavailable"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!(dashboard.reviewer_workload || []).length && (
                  <tr>
                    <td colSpan="3" className="bank-empty">
                      No reviewers are registered yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel">
          <div className="bank-section-head">
            <div>
              <h2>Recent assignment activity</h2>
              <p>Latest automatic assignment events.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>APPLICATION</th>
                  <th>EVENT</th>
                  <th>REVIEWER</th>
                  <th>WHEN</th>
                </tr>
              </thead>
              <tbody>
                {(dashboard.recent_assignment_activity || []).map((event) => (
                  <tr key={event.id}>
                    <td>
                      {event.reference || `Application ${event.application_id}`}
                    </td>
                    <td>{title(event.event_type)}</td>
                    <td>{event.reviewer_name || "Unassigned"}</td>
                    <td>
                      {dateTime(event.created_at)}
                      {event.reason && <small>{event.reason}</small>}
                    </td>
                  </tr>
                ))}
                {!(dashboard.recent_assignment_activity || []).length && (
                  <tr>
                    <td colSpan="4" className="bank-empty">
                      No assignment activity has been recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
