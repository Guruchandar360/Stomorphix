import React, { useState } from "react";
import AlertCircle from "lucide-react/dist/esm/icons/alert-circle.js";
import CheckCircle2 from "lucide-react/dist/esm/icons/check-circle-2.js";
import Download from "lucide-react/dist/esm/icons/download.js";
import FileArchive from "lucide-react/dist/esm/icons/file-archive.js";
import Loader2 from "lucide-react/dist/esm/icons/loader-2.js";
import X from "lucide-react/dist/esm/icons/x.js";


const TERMINAL = new Set(["completed", "partial", "failed"]);

function isCalibrated(value) {
  return Boolean(value?.is_calibrated);
}

function metricKey(value, metric) {
  return `${metric}_${isCalibrated(value) ? "um" : "px"}${metric === "area" ? "2" : ""}`;
}

function unit(value, metric) {
  if (metric === "area") return isCalibrated(value) ? "µm²" : "px²";
  return isCalibrated(value) ? "µm" : "px";
}

function absoluteUrl(apiBase, value) {
  if (!value) return "#";
  return value.startsWith("http") ? value : `${apiBase}${value}`;
}

function statusText(job) {
  if (job.status === "creating") return "Preparing batch upload";
  if (job.status === "receiving") return `Uploading ${job.uploaded_files} of ${job.expected_files} images`;
  if (job.status === "queued") return "Batch queued for YOLO11 Small inference";
  if (job.status === "processing") {
    return `Analyzing ${Math.min(job.processed_files + 1, job.expected_files)} of ${job.expected_files}`;
  }
  if (job.status === "finalizing") return "Preparing summaries and download folders";
  if (job.status === "partial") return "Batch completed with some file errors";
  if (job.status === "failed") return "Batch analysis failed";
  return "Batch analysis complete";
}

export default function BatchResult({ job, token, apiBase }) {
  const [selectedResult, setSelectedResult] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const completed = TERMINAL.has(job.status);
  const progressValue = job.status === "receiving"
    ? job.uploaded_files
    : job.processed_files;
  const percent = Math.round((progressValue / Math.max(job.expected_files, 1)) * 100);

  async function openResult(index) {
    setDetailLoading(true);
    setDetailError("");
    try {
      const response = await fetch(`${apiBase}/api/batches/${job.id}/results/${index}`, {
        headers: { "X-Batch-Token": token },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load this result.");
      setSelectedResult(data);
    } catch (error) {
      setDetailError(error.message);
    } finally {
      setDetailLoading(false);
    }
  }

  const downloadUrl = (kind) =>
    `${apiBase}/api/batches/${job.id}/downloads/${kind}?token=${encodeURIComponent(token)}`;

  return (
    <div className="bubble result batch-result">
      <div className="batch-status-header">
        <div>
          <span className={`batch-status-icon ${completed ? "done" : "active"}`}>
            {completed ? <CheckCircle2 size={17} /> : <Loader2 className="spin" size={17} />}
          </span>
          <div>
            <strong>{statusText(job)}</strong>
            {job.current_file && <span>{job.current_file}</span>}
          </div>
        </div>
        <span className="batch-percent">{completed ? "100%" : `${Math.min(percent, 99)}%`}</span>
      </div>

      <div className="batch-progress-track" aria-label={`${percent}% complete`}>
        <span style={{ width: `${completed ? 100 : Math.min(percent, 99)}%` }} />
      </div>

      <div className="batch-counters">
        <span><strong>{job.processed_files}</strong> processed</span>
        <span><strong>{job.results?.length || 0}</strong> successful</span>
        <span><strong>{job.failed_files}</strong> failed</span>
      </div>

      {completed && job.summary && (
        <>
          {job.explanation && <p className="batch-explanation">{job.explanation}</p>}
          <div className="summary-grid batch-summary-grid">
            <Metric label="Images" value={job.summary.completed_images} />
            <Metric label="Total Stomata" value={job.summary.total_stomata} />
            <Metric label="Mean / Image" value={job.summary.avg_stomata_per_image} />
            <Metric label="Avg Area" value={`${job.summary[`avg_${metricKey(job, "area")}`]} ${unit(job, "area")}`} />
          </div>

          <div className="artifact-row batch-downloads">
            <a href={downloadUrl("annotated")} download>
              <Download size={14} /> Annotated images
            </a>
            <a href={downloadUrl("csv")} download>
              <Download size={14} /> CSV folder
            </a>
            <a href={downloadUrl("complete")} download>
              <FileArchive size={14} /> Complete batch
            </a>
          </div>
        </>
      )}

      {job.results?.length > 0 && (
        <div className="batch-gallery" aria-label="Completed image results">
          {job.results.map((item) => (
            <button
              type="button"
              className="batch-gallery-item"
              key={`${item.index}-${item.original_name}`}
              onClick={() => openResult(item.index)}
              title={`Open ${item.original_name}`}
            >
              <img src={absoluteUrl(apiBase, item.annotated_image_url)} alt="" />
              <span>{item.original_name.split("/").pop()}</span>
              <strong>{item.stomata_count} stomata</strong>
            </button>
          ))}
        </div>
      )}

      {job.errors?.length > 0 && (
        <div className="batch-errors">
          <div><AlertCircle size={15} /> Files requiring attention</div>
          {job.errors.map((item) => (
            <span key={item.filename}><strong>{item.filename}</strong>: {item.error}</span>
          ))}
        </div>
      )}

      {detailLoading && <div className="batch-detail-loading"><Loader2 className="spin" size={16} /> Loading image result</div>}
      {detailError && <div className="batch-detail-error">{detailError}</div>}

      {selectedResult && (
        <div className="batch-detail">
          <div className="batch-detail-header">
            <div>
              <strong>{selectedResult.original_name}</strong>
              <span>{selectedResult.stomata_count} stomata detected</span>
            </div>
            <button type="button" onClick={() => setSelectedResult(null)} title="Close image result">
              <X size={16} />
            </button>
          </div>
          <img
            className="batch-detail-image"
            src={absoluteUrl(apiBase, selectedResult.annotated_image_url)}
            alt={`Annotated ${selectedResult.original_name}`}
          />
          <div className="summary-grid batch-detail-metrics">
            <Metric label="Count" value={selectedResult.stomata_count} />
            <Metric label="Avg Length" value={`${selectedResult.summary[`avg_${metricKey(selectedResult, "length")}`]} ${unit(selectedResult, "length")}`} />
            <Metric label="Avg Width" value={`${selectedResult.summary[`avg_${metricKey(selectedResult, "width")}`]} ${unit(selectedResult, "width")}`} />
            <Metric label="Avg Area" value={`${selectedResult.summary[`avg_${metricKey(selectedResult, "area")}`]} ${unit(selectedResult, "area")}`} />
          </div>
          <div className="artifact-row">
            <a href={absoluteUrl(apiBase, selectedResult.annotated_image_url)} target="_blank" rel="noreferrer">
              Open full resolution
            </a>
            <a href={absoluteUrl(apiBase, selectedResult.csv_url)} download>
              <Download size={13} /> Download this CSV
            </a>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Index</th><th>Length ({unit(selectedResult, "length")})</th><th>Width ({unit(selectedResult, "width")})</th><th>Area ({unit(selectedResult, "area")})</th><th>Aspect Ratio</th>
                </tr>
              </thead>
              <tbody>
                {selectedResult.measurements.slice(0, 15).map((row) => (
                  <tr key={row.stoma_id}>
                    <td>#{row.stoma_id}</td>
                    <td>{row[metricKey(selectedResult, "length")]}</td>
                    <td>{row[metricKey(selectedResult, "width")]}</td>
                    <td>{row[metricKey(selectedResult, "area")]}</td>
                    <td>{row.aspect_ratio}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
