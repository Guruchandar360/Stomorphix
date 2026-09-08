import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import ChevronDown from "lucide-react/dist/esm/icons/chevron-down.js";
import Download from "lucide-react/dist/esm/icons/download.js";
import Folder from "lucide-react/dist/esm/icons/folder.js";
import History from "lucide-react/dist/esm/icons/history.js";
import Loader2 from "lucide-react/dist/esm/icons/loader-2.js";
import LogIn from "lucide-react/dist/esm/icons/log-in.js";
import Menu from "lucide-react/dist/esm/icons/menu.js";
import MessageSquarePlus from "lucide-react/dist/esm/icons/message-square-plus.js";
import MoreHorizontal from "lucide-react/dist/esm/icons/more-horizontal.js";
import Search from "lucide-react/dist/esm/icons/search.js";
import Send from "lucide-react/dist/esm/icons/send.js";
import Settings from "lucide-react/dist/esm/icons/settings.js";
import SlidersHorizontal from "lucide-react/dist/esm/icons/sliders-horizontal.js";
import UserRound from "lucide-react/dist/esm/icons/user-round.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import X from "lucide-react/dist/esm/icons/x.js";
import FolderOpen from "lucide-react/dist/esm/icons/folder-open.js";
import ImageIcon from "lucide-react/dist/esm/icons/image.js";
import Images from "lucide-react/dist/esm/icons/images.js";
import "./styles.css";
import BatchResult from "./BatchResult.jsx";
import {
  auth,
  googleProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  getAuthToken
} from "./firebase.js";

const configuredApiBase = (
  window.env?.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE_URL || ""
).replace(/\/$/, "");
const API_BASE = configuredApiBase || (
  window.location.origin.includes("127.0.0.1") || window.location.origin.includes("localhost")
    ? "http://127.0.0.1:8000"
    : window.location.origin
);

const confidenceOptions = [
  { label: "Conf: 0.30 (Very Sensitive)", value: "0.30" },
  { label: "Conf: 0.40 (Sensitive)", value: "0.40" },
  { label: "Conf: 0.50 (Balanced)", value: "0.50" },
  { label: "Conf: 0.60 (Stricter)", value: "0.60" },
  { label: "Conf: 0.70 (High Precision)", value: "0.70" },
];

const iouOptions = [
  { label: "IoU: 0.30 (Strict NMS)", value: "0.30" },
  { label: "IoU: 0.50 (Balanced)", value: "0.50" },
  { label: "IoU: 0.70 (Relaxed)", value: "0.70" },
];

const magnificationOptions = [
  { label: "4x", value: "4" },
  { label: "5x", value: "5" },
  { label: "10x", value: "10" },
  { label: "20x", value: "20" },
  { label: "40x", value: "40" },
  { label: "100x", value: "100" },
];

async function authenticatedHeaders(headers = {}) {
  const token = await getAuthToken();
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers;
}

function normalizeCountResult(value) {
  if (!value) return null;
  const source = Array.isArray(value.detections)
    ? value.detections
    : Array.isArray(value.measurements)
      ? value.measurements
      : [];
  const detections = source
    .filter((item) => Array.isArray(item.contour) && item.contour.length >= 3)
    .map((item, index) => ({ stoma_id: index + 1, contour: item.contour }));
  const stomataCount = detections.length || Number(value.stomata_count) || 0;
  const fallbackExplanation = `I detected ${stomataCount} ${stomataCount === 1 ? "stoma" : "stomata"}. Review the outlined detections and correct any errors before using the count.`;
  return {
    image_id: value.image_id,
    original_name: value.original_name,
    stomata_count: stomataCount,
    confidence: value.confidence,
    iou: value.iou,
    magnification: value.magnification || 40,
    explanation: Array.isArray(value.detections) ? value.explanation : fallbackExplanation,
    summary: { stomata_count: stomataCount },
    detections,
    annotated_image_url: value.annotated_image_url,
    raw_image_url: value.raw_image_url,
    count_report_url: value.count_report_url,
  };
}

function normalizeBatchJob(value) {
  if (!value) return null;
  const results = (value.results || []).map((item) => ({
    index: item.index,
    original_name: item.original_name,
    stomata_count: item.stomata_count,
    annotated_image_url: item.annotated_image_url,
    raw_image_url: item.raw_image_url,
    count_report_url: item.count_report_url,
  }));
  const completedImages = Number(value.summary?.completed_images) || results.length;
  const totalStomata = Number(value.summary?.total_stomata)
    || results.reduce((total, item) => total + Number(item.stomata_count || 0), 0);
  const summary = value.summary ? {
    completed_images: completedImages,
    failed_images: Number(value.summary.failed_images) || 0,
    total_stomata: totalStomata,
    avg_stomata_per_image: completedImages ? Number((totalStomata / completedImages).toFixed(2)) : 0,
  } : null;
  const fallbackExplanation = summary
    ? `I analyzed ${summary.completed_images} images and detected ${summary.total_stomata} stomata in total, averaging ${summary.avg_stomata_per_image} per image.`
    : "";
  return {
    id: value.id,
    status: value.status,
    expected_files: value.expected_files,
    uploaded_files: value.uploaded_files,
    processed_files: value.processed_files,
    failed_files: value.failed_files,
    current_file: value.current_file,
    results,
    errors: value.errors || [],
    summary,
    explanation: results.some((item) => item.count_report_url) ? value.explanation : fallbackExplanation,
    confidence: value.confidence,
    iou: value.iou,
    magnification: value.magnification || 40,
    created_at: value.created_at,
    updated_at: value.updated_at,
  };
}

function getCountCSVDownloadUrl(result) {
  if (!result) return "#";
  const filename = String(result.original_name || result.image_id || "image").replaceAll('"', '""');
  const content = `filename,stomata_count\n"${filename}",${result.stomata_count}\n`;
  return `data:text/csv;charset=utf-8,${encodeURIComponent(content)}`;
}

function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [serverStatus, setServerStatus] = useState("checking");
  const [authRequired, setAuthRequired] = useState(false);
  const [file, setFile] = useState(null);
  const [filePreviewUrl, setFilePreviewUrl] = useState(null);
  const [batchFiles, setBatchFiles] = useState([]);
  const [batchJob, setBatchJob] = useState(null);
  const [batchToken, setBatchToken] = useState("");
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [confidence, setConfidence] = useState("0.50");
  const [iou, setIou] = useState("0.30");
  const [magnification, setMagnification] = useState("40");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [originalResult, setOriginalResult] = useState(null);
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [viewMode, setViewMode] = useState("annotated"); // "annotated", "raw", or "edit"
  const [theme, setTheme] = useState("dark");
  const [historySession, setHistorySession] = useState("new");
  const [analyzedFile, setAnalyzedFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [editTool, setEditTool] = useState("inspect"); // "inspect" or "draw"
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawingPoints, setDrawingPoints] = useState([]);
  const [tempDrawnPoints, setTempDrawnPoints] = useState([]);
  const inputRef = useRef(null);
  const imagePickerRef = useRef(null);
  const folderPickerRef = useRef(null);
  const imageRef = useRef(null);

  useEffect(() => {
    setImageLoaded(false);
    setIsDrawing(false);
    setDrawingPoints([]);
    setTempDrawnPoints([]);
  }, [viewMode, result]);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitAnalysis(e);
    }
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }

  function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX;
    const y = e.clientY;
    if (x < rect.left || x >= rect.right || y < rect.top || y >= rect.bottom) {
      setIsDragging(false);
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files || []);
    if (droppedFiles.length > 0) selectAttachments(droppedFiles);
  }

  // Load history from localStorage
  const [history, setHistory] = useState([]);

  // Use refs to track the user ID for history synchronization to prevent race conditions and stale closures
  const userIdRef = useRef("anonymous");

  // Keep userIdRef updated whenever user state changes
  useEffect(() => {
    userIdRef.current = user ? user.uid : "anonymous";
  }, [user]);

  // Sync history to user-scoped localStorage whenever history state changes
  useEffect(() => {
    const storageKey = `stomata_history_${userIdRef.current}`;
    localStorage.setItem(storageKey, JSON.stringify(history));
  }, [history]);

  // Listen for authentication state changes on mount and load the correct history
  useEffect(() => {
    setAuthLoading(true);
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      setUser(firebaseUser);
      setAuthLoading(false);

      const userId = firebaseUser ? firebaseUser.uid : "anonymous";
      userIdRef.current = userId;
      const storageKey = `stomata_history_${userId}`;
      try {
        const data = localStorage.getItem(storageKey);
        setHistory(data ? JSON.parse(data) : []);
      } catch (e) {
        setHistory([]);
      }
    });
    return () => unsubscribe();
  }, []);

  async function handleLogin() {
    setAuthLoading(true);
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (err) {
      console.error("Auth login failed:", err);
      alert(err.message || "Google Sign-in failed.");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleLogout() {
    try {
      await signOut(auth);
      setUser(null);
      userIdRef.current = "anonymous";
      const storageKey = "stomata_history_anonymous";
      try {
        const data = localStorage.getItem(storageKey);
        setHistory(data ? JSON.parse(data) : []);
      } catch (e) {
        setHistory([]);
      }
    } catch (err) {
      console.error("Auth logout failed:", err);
    }
  }

  // Check API server connection status
  useEffect(() => {
    let active = true;
    async function checkHealth() {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "ok") {
            if (active) {
              setServerStatus("online");
              setAuthRequired(Boolean(data.authentication_required));
            }
            return;
          }
        }
        if (active) setServerStatus("offline");
      } catch (e) {
        if (active) setServerStatus("offline");
      }
    }

    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  // Apply theme to document body
  useEffect(() => {
    document.body.className = theme === "light" ? "light-theme" : "";
  }, [theme]);

  // Clean up object URLs to prevent leaks
  useEffect(() => {
    return () => {
      if (filePreviewUrl && !filePreviewUrl.startsWith("http")) {
        URL.revokeObjectURL(filePreviewUrl);
      }
    };
  }, [filePreviewUrl]);

  // Reset states for a new analysis
  function handleNewAnalysis() {
    releaseAttachmentUrls();
    setFile(null);
    setFilePreviewUrl(null);
    setBatchFiles([]);
    setBatchJob(null);
    setBatchToken("");
    setResult(null);
    setOriginalResult(null);
    setError("");
    setPrompt("");
    setHistorySession("new");
    setViewMode("annotated");
    setAnalyzedFile(null);
  }

  // Handle file select and create preview
  function handleFileChange(event) {
    const selectedFiles = Array.from(event.target.files || []);
    event.target.value = "";
    if (selectedFiles.length) selectAttachments(selectedFiles);
  }

  function releaseAttachmentUrls() {
    if (filePreviewUrl && !filePreviewUrl.startsWith("http")) {
      URL.revokeObjectURL(filePreviewUrl);
    }
    batchFiles.forEach((item) => URL.revokeObjectURL(item.previewUrl));
  }

  function selectAttachments(selectedFiles) {
    const validFiles = selectedFiles.filter((selected) => {
      const suffix = selected.name.split(".").pop()?.toLowerCase();
      return selected.type.startsWith("image/") || ["jpg", "jpeg", "png", "bmp", "tif", "tiff"].includes(suffix);
    });

    if (!validFiles.length) {
      setError("Please select supported microscopy images.");
      return;
    }
    if (validFiles.length > 30) {
      setError("A batch can contain at most 30 images.");
      return;
    }

    releaseAttachmentUrls();
    setResult(null);
    setBatchJob(null);
    setBatchToken("");
    setError(validFiles.length !== selectedFiles.length ? "Unsupported files were excluded from the selection." : "");

    if (validFiles.length === 1) {
      const selectedFile = validFiles[0];
      setFile(selectedFile);
      setFilePreviewUrl(URL.createObjectURL(selectedFile));
      setBatchFiles([]);
    } else {
      setFile(null);
      setFilePreviewUrl(null);
      setBatchFiles(validFiles.map((selectedFile) => ({
        file: selectedFile,
        relativePath: selectedFile.webkitRelativePath || selectedFile.name,
        previewUrl: URL.createObjectURL(selectedFile),
      })));
    }
    setAttachmentMenuOpen(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  function removeBatchAttachment(index) {
    const removed = batchFiles[index];
    if (removed) URL.revokeObjectURL(removed.previewUrl);
    const remaining = batchFiles.filter((_, itemIndex) => itemIndex !== index);
    if (remaining.length === 1) {
      setFile(remaining[0].file);
      setFilePreviewUrl(remaining[0].previewUrl);
      setBatchFiles([]);
    } else {
      setBatchFiles(remaining);
    }
  }

  // Load a historical analysis session from the sidebar
  function handleLoadSession(session) {
    releaseAttachmentUrls();
    setFile(null);
    setFilePreviewUrl(null);
    setBatchFiles([]);
    setConfidence(session.confidence);
    setIou(session.iou || "0.30");
    setMagnification(String(session.magnification || 40));
    if (session.type === "batch") {
      setResult(null);
      setOriginalResult(null);
      setBatchJob(normalizeBatchJob(session.batchJob));
      setBatchToken(session.batchToken || "");
    } else {
      const countResult = normalizeCountResult(session.result);
      setResult(countResult);
      setOriginalResult(countResult);
      setBatchJob(null);
      setBatchToken("");
    }
    setHistorySession(session.id);
    setViewMode("annotated");
    setAnalyzedFile({
      name: session.file_name,
      count: session.type === "batch" ? session.batchJob?.expected_files : null,
      type: session.type || "single",
      confidence: session.confidence,
      iou: session.iou || "0.30",
      magnification: session.magnification || 40,
      prompt: session.prompt || ""
    });
  }

  function submitAnalysis(event) {
    if (authRequired && !user) {
      if (event) event.preventDefault();
      setError("Sign in before starting an analysis.");
      return;
    }
    if (batchFiles.length > 1) {
      analyzeBatch(event);
    } else {
      analyzeImage(event);
    }
  }

  // Execute FastAPI segmentation and counting API
  async function analyzeImage(event) {
    if (event) event.preventDefault();
    if (!file) {
      setError("Please attach a leaf imprint image first.");
      return;
    }

    const activeFile = file;
    const activeConf = confidence;
    const activeIou = iou;
    const activeMagnification = magnification;

    setAnalyzedFile({
      name: activeFile.name,
      confidence: activeConf,
      iou: activeIou,
      magnification: activeMagnification,
      prompt: prompt
    });

    // Clear input composer state immediately
    setFile(null);
    setFilePreviewUrl(null);
    setPrompt("");

    setLoading(true);
    setError("");
    setResult(null);
    setViewMode("annotated");

    const formData = new FormData();
    formData.append("image", activeFile);
    formData.append("confidence", activeConf);
    formData.append("iou", activeIou);
    formData.append("magnification", activeMagnification);
    if (prompt) {
      formData.append("prompt", prompt);
    }

    try {
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        headers: await authenticatedHeaders(),
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Stomata analysis pipeline error.");
      }
      const countResult = normalizeCountResult(data);
      setResult(countResult);
      setOriginalResult(countResult);

      // Create a persistent history session log entry
      const newSession = {
        id: Date.now().toString(),
        title: `${activeFile.name.slice(0, 16)} (${data.stomata_count} stomata)`,
        file_name: activeFile.name,
        result: countResult,
        confidence: activeConf,
        iou: activeIou,
        magnification: activeMagnification,
        prompt: prompt,
        raw_image_url: `${API_BASE}${data.raw_image_url}`,
        annotated_image_url: `${API_BASE}${data.annotated_image_url}`
      };

      setHistory((prev) => [newSession, ...prev]);
      setHistorySession(newSession.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function analyzeBatch(event) {
    if (event) event.preventDefault();
    if (batchFiles.length < 2) {
      setError("Please attach at least two images for a batch analysis.");
      return;
    }

    const activeFiles = [...batchFiles];
    const activePrompt = prompt;
    const activeConf = confidence;
    const activeIou = iou;
    const activeMagnification = magnification;
    const folderName = activeFiles[0].relativePath.includes("/")
      ? activeFiles[0].relativePath.split("/")[0]
      : `${activeFiles.length} selected images`;

    setAnalyzedFile({
      name: folderName,
      count: activeFiles.length,
      confidence: activeConf,
      iou: activeIou,
      magnification: activeMagnification,
      prompt: activePrompt,
      type: "batch",
    });
    setBatchFiles([]);
    setPrompt("");
    setLoading(true);
    setError("");
    setResult(null);
    setOriginalResult(null);
    setBatchJob({
      status: "creating",
      expected_files: activeFiles.length,
      uploaded_files: 0,
      processed_files: 0,
      failed_files: 0,
      results: [],
    });

    let jobId = "";
    let accessToken = "";
    try {
      const createResponse = await fetch(`${API_BASE}/api/batches`, {
        method: "POST",
        headers: await authenticatedHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          expected_files: activeFiles.length,
          confidence: Number(activeConf),
          iou: Number(activeIou),
          magnification: Number(activeMagnification),
          prompt: activePrompt || null,
        }),
      });
      const created = await createResponse.json();
      if (!createResponse.ok) throw new Error(created.detail || "Unable to create the batch.");
      jobId = created.job.id;
      accessToken = created.access_token;
      setBatchToken(accessToken);
      setBatchJob(created.job);

      for (let start = 0; start < activeFiles.length; start += 5) {
        const chunk = activeFiles.slice(start, start + 5);
        const uploadData = new FormData();
        chunk.forEach((item) => uploadData.append("images", item.file, item.file.name));
        uploadData.append("relative_paths", JSON.stringify(chunk.map((item) => item.relativePath)));
        const uploadResponse = await fetch(`${API_BASE}/api/batches/${jobId}/uploads`, {
          method: "POST",
          headers: { "X-Batch-Token": accessToken },
          body: uploadData,
        });
        const uploadState = await uploadResponse.json();
        if (!uploadResponse.ok) throw new Error(uploadState.detail || "A batch upload chunk failed.");
        setBatchJob(uploadState);
      }

      const startResponse = await fetch(`${API_BASE}/api/batches/${jobId}/start`, {
        method: "POST",
        headers: { "X-Batch-Token": accessToken },
      });
      let jobState = await startResponse.json();
      if (!startResponse.ok) throw new Error(jobState.detail || "Unable to start batch inference.");
      setBatchJob(jobState);

      const terminalStatuses = new Set(["completed", "partial", "failed"]);
      while (!terminalStatuses.has(jobState.status)) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const statusResponse = await fetch(`${API_BASE}/api/batches/${jobId}`, {
          headers: { "X-Batch-Token": accessToken },
        });
        jobState = await statusResponse.json();
        if (!statusResponse.ok) throw new Error(jobState.detail || "Unable to read batch progress.");
        setBatchJob(jobState);
      }

      const newSession = {
        id: Date.now().toString(),
        type: "batch",
        title: `${folderName.slice(0, 18)} (${activeFiles.length} images)`,
        file_name: folderName,
        result: null,
        batchJob: jobState,
        batchToken: accessToken,
        confidence: activeConf,
        iou: activeIou,
        magnification: activeMagnification,
        prompt: activePrompt,
      };
      setHistory((previous) => [newSession, ...previous]);
      setHistorySession(newSession.id);
    } catch (err) {
      setError(err.message);
    } finally {
      activeFiles.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setLoading(false);
    }
  }

  // Delete a history session
  function handleDeleteSession(sessionId) {
    setHistory((prev) => prev.filter((session) => session.id !== sessionId));
    if (historySession === sessionId) {
      handleNewAnalysis();
    }
  }

  // Rename a history session
  function handleRenameSession(sessionId, newTitle) {
    if (newTitle && newTitle.trim()) {
      setHistory((prev) =>
        prev.map((session) =>
          session.id === sessionId ? { ...session, title: newTitle.trim() } : session
        )
      );
    }
  }

  function updateActiveSessionDetections(newDetections) {
    if (!result) return;
    const count = newDetections.length;

    const updatedResult = {
      ...result,
      stomata_count: count,
      summary: { stomata_count: count },
      detections: newDetections,
      explanation: `After manual correction, the image contains ${count} ${count === 1 ? "stoma" : "stomata"}. The displayed contours include your edits.`
    };

    setResult(updatedResult);

    if (historySession !== "new") {
      setHistory((prev) =>
        prev.map((session) =>
          session.id === historySession ? { ...session, result: updatedResult } : session
        )
      );
    }
  }

  function handleResetEdits() {
    if (originalResult) {
      setResult(JSON.parse(JSON.stringify(originalResult)));
      if (historySession !== "new") {
        setHistory((prev) =>
          prev.map((session) =>
            session.id === historySession ? { ...session, result: originalResult } : session
          )
        );
      }
    }
  }

  function handleDeleteDetection(stomaId, e) {
    if (e) e.stopPropagation();
    if (!result) return;
    const remaining = result.detections.filter((detection) => detection.stoma_id !== stomaId);
    const reindexed = remaining.map((detection, index) => ({
      ...detection,
      stoma_id: index + 1
    }));
    updateActiveSessionDetections(reindexed);
  }

  function getEventCoords(e) {
    if (!imageRef.current) return null;
    const rect = imageRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    return { x, y };
  }

  function convertScreenToOriginal(points) {
    if (!imageRef.current) return [];
    const rect = imageRef.current.getBoundingClientRect();
    const scaleX = imageRef.current.naturalWidth / rect.width;
    const scaleY = imageRef.current.naturalHeight / rect.height;
    return points.map(p => ({
      x: Math.round(p.x * scaleX),
      y: Math.round(p.y * scaleY)
    }));
  }

  function handleCanvasMouseDown(e) {
    if (viewMode !== "edit" || editTool !== "draw" || tempDrawnPoints.length > 0) return;
    e.preventDefault();
    const coords = getEventCoords(e);
    if (!coords) return;
    setIsDrawing(true);
    setDrawingPoints([coords]);
  }

  function handleCanvasMouseMove(e) {
    if (!isDrawing || viewMode !== "edit" || editTool !== "draw") return;
    e.preventDefault();
    const coords = getEventCoords(e);
    if (!coords) return;
    setDrawingPoints((prev) => [...prev, coords]);
  }

  async function handleCanvasMouseUp(e) {
    if (!isDrawing) return;
    setIsDrawing(false);
    
    if (drawingPoints.length < 5) {
      setDrawingPoints([]);
      return;
    }
    
    setTempDrawnPoints(drawingPoints);
    setDrawingPoints([]);
  }

  async function handleConfirmDrawing(e) {
    if (e) e.stopPropagation();
    if (tempDrawnPoints.length === 0 || !result) return;

    const originalPoints = convertScreenToOriginal(tempDrawnPoints);
    setTempDrawnPoints([]);

    try {
      const response = await fetch(`${API_BASE}/api/detections/validate`, {
        method: "POST",
        headers: await authenticatedHeaders({
          "Content-Type": "application/json"
        }),
        body: JSON.stringify({ points: originalPoints })
      });
      
      const newDetection = await response.json();
      if (!response.ok) {
        throw new Error(newDetection.detail || "Unable to add this detection.");
      }
      
      const newDetections = [
        ...result.detections,
        {
          ...newDetection,
          stoma_id: result.detections.length + 1
        }
      ];
      updateActiveSessionDetections(newDetections);
    } catch (err) {
      alert(err.message);
    }
  }

  function handleCancelDrawing(e) {
    if (e) e.stopPropagation();
    setTempDrawnPoints([]);
  }

  let bubbleCoords = null;
  if (tempDrawnPoints.length > 0 && imageRef.current) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    tempDrawnPoints.forEach(p => {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    });
    const clientWidth = imageRef.current.clientWidth || 1;
    const clientHeight = imageRef.current.clientHeight || 1;
    bubbleCoords = {
      x: ((minX + maxX) / 2 / clientWidth) * 100,
      y: ((minY + maxY) / 2 / clientHeight) * 100
    };
  }

  const activeImageSrc =
    viewMode === "annotated"
      ? (result?.annotated_image_url
          ? (result.annotated_image_url.startsWith("http") ? result.annotated_image_url : `${API_BASE}${result.annotated_image_url}`)
          : null)
      : (result
          ? (result.raw_image_url.startsWith("http") ? result.raw_image_url : `${API_BASE}${result.raw_image_url}`)
          : filePreviewUrl);

  return (
    <main className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <Sidebar
        sidebarOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(false)}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        onNewAnalysis={handleNewAnalysis}
        history={history}
        onLoadSession={handleLoadSession}
        currentSession={historySession}
        onDeleteSession={handleDeleteSession}
        onRenameSession={handleRenameSession}
        user={user}
        authLoading={authLoading}
        onLogin={handleLogin}
        onLogout={handleLogout}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      <section
        className={`chat-panel ${result || batchJob || loading || error ? "has-thread" : ""}`}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDragging && (
          <div className="drag-overlay">
            <div className="drag-overlay-message">
              <Plus size={48} style={{ color: theme === "light" ? "#2b6e49" : "#8fbfa3" }} />
              <p>Drop up to 30 stomata images here</p>
            </div>
          </div>
        )}
        <button
          className="sidebar-toggle floating-toggle"
          type="button"
          onClick={() => setSidebarOpen((open) => !open)}
          aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
          title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
        >
          <Menu size={16} />
        </button>

        <div className="chat-center">
          {!result && !batchJob && !loading && !error ? (
            <div className="welcome-container">
              <section className="hero">
                <p className="eyebrow">STOMASPOT</p>
                <h1>What should we analyze today?</h1>
              </section>
              <div className="message assistant intro">
                <div className="bubble">
                  Upload one image for an editable stomata count, or attach multiple images or a folder for batch counting.
                </div>
              </div>
            </div>
          ) : (
            <div className="messages">
              {analyzedFile && (
              <div className="message user">
                <div className="bubble compact">
                  {analyzedFile.prompt && (
                    <p style={{ margin: "0 0 10px 0", fontSize: "16px", fontWeight: "400", whiteSpace: "pre-wrap" }}>
                      {analyzedFile.prompt}
                    </p>
                  )}
                  <strong>
                    {analyzedFile.type === "batch" ? <Images size={14} /> : <Folder size={14} />}
                    {analyzedFile.name}{analyzedFile.count ? ` · ${analyzedFile.count} images` : ""}
                  </strong>
                  <span>
                    Parameters: Conf={Number(analyzedFile.confidence).toFixed(2)} · IoU={Number(analyzedFile.iou).toFixed(2)} · Magnification={analyzedFile.magnification || 40}x
                  </span>
                </div>
              </div>
            )}

            {loading && !batchJob && (
              <div className="message assistant">
                <div className="bubble status">
                  <Loader2 className="spin" size={14} />
                  Running YOLO11-seg inference and counting stomata...
                </div>
              </div>
            )}

            {error && (
              <div className="message assistant">
                <div className="bubble error">
                  <strong>Analysis Error:</strong> {error}
                </div>
              </div>
            )}

            {batchJob && (
              <div className="message assistant">
                <BatchResult job={batchJob} token={batchToken} apiBase={API_BASE} />
              </div>
            )}

            {result && (
              <div className="message assistant">
                <div className="bubble result">
                  <p>{result.explanation}</p>

                  {/* Comparative Image Viewer */}
                  <div className="image-viewer-container">
                    <div className="viewer-tabs">
                      <button
                        type="button"
                        className={viewMode === "annotated" ? "active" : ""}
                        onClick={() => setViewMode("annotated")}
                      >
                        👁️ Model Annotations
                      </button>
                      <button
                        type="button"
                        className={viewMode === "raw" ? "active" : ""}
                        onClick={() => setViewMode("raw")}
                      >
                        📸 Raw Imprint
                      </button>
                      <button
                        type="button"
                        className={viewMode === "edit" ? "active" : ""}
                        onClick={() => setViewMode("edit")}
                      >
                        ✏️ Edit Detections
                      </button>
                    </div>
                    <div className="viewer-display">
                      {activeImageSrc ? (
                        <div 
                          className="viewer-canvas-container"
                          onMouseDown={handleCanvasMouseDown}
                          onMouseMove={handleCanvasMouseMove}
                          onMouseUp={handleCanvasMouseUp}
                        >
                          <img
                            ref={imageRef}
                            src={viewMode === "edit" ? (result ? (result.raw_image_url.startsWith("http") ? result.raw_image_url : `${API_BASE}${result.raw_image_url}`) : filePreviewUrl) : activeImageSrc}
                            alt="Stomata overlay"
                            className="viewer-image"
                            draggable={false}
                            onLoad={() => setImageLoaded(true)}
                          />
                          {viewMode === "edit" && result && imageRef.current && (
                            <div className="hitl-overlay-layer">
                              {/* Draw SVG contours for existing stomata using percentage coordinate system matching scaled image */}
                              <svg 
                                className="hitl-contour-svg"
                                viewBox="0 0 100 100"
                                preserveAspectRatio="none"
                              >
                                {result.detections.map((detection) => {
                                  if (!detection.contour || detection.contour.length === 0) return null;
                                  const naturalWidth = imageRef.current.naturalWidth || 1;
                                  const naturalHeight = imageRef.current.naturalHeight || 1;
                                  const pointsStr = detection.contour
                                    .map(pt => `${(pt[0] / naturalWidth) * 100},${(pt[1] / naturalHeight) * 100}`)
                                    .join(" ");
                                  return (
                                    <polygon
                                      key={detection.stoma_id}
                                      points={pointsStr}
                                      className={`hitl-contour-polygon ${editTool === "inspect" ? "clickable" : ""}`}
                                      onClick={editTool === "inspect" ? (event) => handleDeleteDetection(detection.stoma_id, event) : undefined}
                                    />
                                  );
                                })}
                                {/* Draw currently active freehand drawing line */}
                                {isDrawing && drawingPoints.length > 1 && (
                                  <polyline
                                    points={drawingPoints.map(p => `${(p.x / imageRef.current.clientWidth) * 100},${(p.y / imageRef.current.clientHeight) * 100}`).join(" ")}
                                    className="hitl-active-polyline"
                                  />
                                )}
                                {/* Draw unconfirmed pending stoma polygon */}
                                {tempDrawnPoints.length > 1 && (
                                  <polygon
                                    points={tempDrawnPoints.map(p => `${(p.x / imageRef.current.clientWidth) * 100},${(p.y / imageRef.current.clientHeight) * 100}`).join(" ")}
                                    className="hitl-temp-polygon"
                                  />
                                )}
                              </svg>

                              {/* Floating Confirmation Bubble */}
                              {bubbleCoords && (
                                <div 
                                  className="drawing-confirmation-bubble"
                                  style={{
                                    left: `${bubbleCoords.x}%`,
                                    top: `${bubbleCoords.y}%`
                                  }}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <button 
                                    type="button" 
                                    className="confirm-tick-btn" 
                                    onClick={handleConfirmDrawing}
                                    title="Confirm drawing"
                                  >
                                    ✔️
                                  </button>
                                  <button 
                                    type="button" 
                                    className="cancel-cross-btn" 
                                    onClick={handleCancelDrawing}
                                    title="Cancel drawing"
                                  >
                                    ✕
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="viewer-placeholder">No image preview available</div>
                      )}
                    </div>
                  </div>

                  {viewMode === "edit" && result && (
                    <div className="edit-mode-banner">
                      <div className="edit-mode-tools">
                        <button
                          type="button"
                          className={`tool-btn ${editTool === "inspect" ? "active" : ""}`}
                          onClick={() => setEditTool("inspect")}
                          title="Select & Delete"
                        >
                          🖐️ Inspect
                        </button>
                        <button
                          type="button"
                          className={`tool-btn ${editTool === "draw" ? "active" : ""}`}
                          onClick={() => setEditTool("draw")}
                          title="Draw Contour Line"
                        >
                          ✏️ Draw
                        </button>
                      </div>
                      <span className="edit-mode-instructions">
                        {editTool === "inspect" ? (
                          <>Click a green detection outline to <strong>delete</strong> it.</>
                        ) : (
                          <>Click and drag to trace a polygon around a missed stoma.</>
                        )}
                      </span>
                      <button className="reset-edits-btn" type="button" onClick={handleResetEdits}>Reset Predictions</button>
                    </div>
                  )}

                  <div className="summary-grid count-summary-grid">
                    <Metric label="Stomata Count" value={result.stomata_count} />
                  </div>

                  <div className="artifact-row">
                    <a href={activeImageSrc} target="_blank" rel="noopener noreferrer">
                      Open full resolution image
                    </a>
                    <a
                      href={getCountCSVDownloadUrl(result)}
                      download={`${result.image_id || "stomata"}_count.csv`}
                    >
                      <Download size={13} />
                      Download count report
                    </a>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

          <form className="composer" onSubmit={(e) => { e.preventDefault(); submitAnalysis(e); }}>
            
            
            {/* Inline Attachment Preview (Matches Claude/ChatGPT layout) */}
            {filePreviewUrl && (
              <div className="composer-attachments">
                <div className="attachment-preview">
                  <img src={filePreviewUrl} alt="Thumbnail preview" />
                  <button
                    type="button"
                    className="remove-attachment-btn"
                    onClick={() => { setFile(null); setFilePreviewUrl(null); }}
                    title="Remove image"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}

            {batchFiles.length > 1 && (
              <div className="composer-attachments batch-attachments">
                <div className="batch-attachment-heading">
                  <span><Images size={15} /> {batchFiles.length} images ready</span>
                  <span>Maximum 30</span>
                </div>
                <div className="batch-attachment-list">
                  {batchFiles.map((item, index) => (
                    <div className="attachment-preview" key={`${item.relativePath}-${index}`} title={item.relativePath}>
                      <img src={item.previewUrl} alt="" />
                      <button
                        type="button"
                        className="remove-attachment-btn"
                        onClick={() => removeBatchAttachment(index)}
                        title={`Remove ${item.file.name}`}
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            <div className="prompt-row">
              {/* Plus (+) Button for Upload Inside Input Bar */}
              <div className="upload-menu-wrap">
                <button
                  type="button"
                  className="upload-picker-btn"
                  title="Attach images"
                  aria-label="Attach images"
                  aria-expanded={attachmentMenuOpen}
                  onClick={() => setAttachmentMenuOpen((open) => !open)}
                >
                  <Plus size={16} />
                </button>
                {attachmentMenuOpen && (
                  <div className="upload-menu">
                    <button type="button" onClick={() => imagePickerRef.current?.click()}>
                      <ImageIcon size={16} />
                      <span><strong>Select images</strong><small>One image or up to 30</small></span>
                    </button>
                    <button type="button" onClick={() => folderPickerRef.current?.click()}>
                      <FolderOpen size={16} />
                      <span><strong>Select folder</strong><small>Images inside one folder</small></span>
                    </button>
                  </div>
                )}
                <input
                  ref={imagePickerRef}
                  className="hidden-file-input"
                  type="file"
                  accept="image/*,.tif,.tiff,.bmp"
                  multiple
                  onChange={handleFileChange}
                />
                <input
                  ref={folderPickerRef}
                  className="hidden-file-input"
                  type="file"
                  accept="image/*,.tif,.tiff,.bmp"
                  multiple
                  webkitdirectory=""
                  directory=""
                  onChange={handleFileChange}
                />
              </div>

              <input
                ref={inputRef}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about stomata or type instructions for analysis..."
                title="Enter analysis instruction or chat message"
              />
              <button
                className="send"
                type="submit"
                disabled={loading || (!file && batchFiles.length < 2) || (authRequired && !user)}
                title={authRequired && !user ? "Sign in to run analysis" : "Run analysis"}
              >
                {loading ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              </button>
            </div>

            <div className="tool-row">
              {/* Confidence Select */}
              <div className="select-pill" title="YOLO Confidence Threshold">
                <SlidersHorizontal size={12} />
                <span>{confidenceOptions.find((opt) => opt.value === confidence)?.label}</span>
                <ChevronDown size={12} />
                <select value={confidence} onChange={(event) => setConfidence(event.target.value)}>
                  {confidenceOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="select-pill" title="NMS overlap threshold (IoU)">
                <span>{iouOptions.find((option) => option.value === iou)?.label}</span>
                <ChevronDown size={12} />
                <select value={iou} onChange={(event) => setIou(event.target.value)}>
                  {iouOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="select-pill" title="Image acquisition magnification">
                <span>{magnificationOptions.find((option) => option.value === magnification)?.label}</span>
                <ChevronDown size={12} />
                <select value={magnification} onChange={(event) => setMagnification(event.target.value)}>
                  {magnificationOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

            </div>
          </form>
        </div>
      </section>

      {isSettingsOpen && (
        <div className="settings-modal-backdrop" onClick={() => setIsSettingsOpen(false)}>
          <div className="settings-modal" onClick={e => e.stopPropagation()}>
            <div className="settings-header">
              <span>Settings</span>
              <button className="settings-close-btn" onClick={() => setIsSettingsOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="settings-section">
              <div className="settings-status-row">
                <span className={`status-dot ${serverStatus}`} />
                <span>
                  {serverStatus === "online"
                    ? "API Server Online"
                    : serverStatus === "checking"
                    ? "Checking API connection..."
                    : "API Server Offline"}
                </span>
              </div>
            </div>
            <hr className="settings-divider" />
            <p className="settings-placeholder">More settings coming soon...</p>
          </div>
        </div>
      )}
    </main>
  );
}

function Sidebar({
  sidebarOpen,
  onToggle,
  theme,
  onToggleTheme,
  onNewAnalysis,
  history,
  onLoadSession,
  currentSession,
  onDeleteSession,
  onRenameSession,
  user,
  authLoading,
  onLogin,
  onLogout,
  onOpenSettings
}) {
  const [searchActive, setSearchActive] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeMenuSessionId, setActiveMenuSessionId] = useState(null);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editingValue, setEditingValue] = useState("");
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);

  // Close menus on document click
  useEffect(() => {
    function handleDocumentClick() {
      setActiveMenuSessionId(null);
      setUserDropdownOpen(false);
    }
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, []);

  function toggleMenu(sessionId, e) {
    e.stopPropagation();
    setActiveMenuSessionId(activeMenuSessionId === sessionId ? null : sessionId);
  }

  function handleSaveRename(sessionId) {
    if (editingValue && editingValue.trim()) {
      onRenameSession(sessionId, editingValue.trim());
    }
    setEditingSessionId(null);
  }

  function handleRenameKeyDown(e, sessionId) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSaveRename(sessionId);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setEditingSessionId(null);
    }
  }

  const filteredHistory = history.filter((session) =>
    session.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (session.file_name && session.file_name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <aside className="sidebar" aria-hidden={!sidebarOpen} inert={!sidebarOpen}>
      <div className="sidebar-header">
        <button
          className="sidebar-toggle"
          type="button"
          onClick={onToggle}
          aria-label="Close sidebar"
          title="Close sidebar"
        >
          <Menu size={16} />
        </button>
      </div>

      <div className="sidebar-top">
        <button className="nav-action primary-action" onClick={onNewAnalysis} title="Start new analysis">
          <MessageSquarePlus size={16} />
          New analysis
        </button>
        {searchActive ? (
          <div className="search-box">
            <Search size={16} />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search recents..."
              autoFocus
              onBlur={() => { if (!searchQuery) setSearchActive(false); }}
            />
          </div>
        ) : (
          <button className="nav-action" onClick={() => setSearchActive(true)}>
            <Search size={16} />
            Search
          </button>
        )}
      </div>

      <div className="sidebar-section">
        <span className="section-label">recents</span>
        {filteredHistory.length === 0 ? (
          <div className="empty-history">
            {searchQuery ? "No matching runs." : "No runs recorded yet."}
          </div>
        ) : (
          filteredHistory.map((session) => {
            const isEditing = editingSessionId === session.id;
            return (
              <div
                key={session.id}
                className={`conversation-container ${currentSession === session.id ? "active" : ""} ${isEditing ? "editing" : ""}`}
              >
                {isEditing ? (
                  <input
                    className="rename-input"
                    value={editingValue}
                    onChange={(e) => setEditingValue(e.target.value)}
                    onBlur={() => handleSaveRename(session.id)}
                    onKeyDown={(e) => handleRenameKeyDown(e, session.id)}
                    autoFocus
                    onFocus={(e) => e.target.select()}
                  />
                ) : (
                  <>
                    <button
                      className="conversation-btn"
                      onClick={() => onLoadSession(session)}
                      title={session.title}
                    >
                      <span className="session-title-text">{session.title}</span>
                    </button>
                    <div className="options-wrapper">
                      <button
                        className="options-trigger-btn"
                        type="button"
                        onClick={(e) => toggleMenu(session.id, e)}
                        title="Session options"
                      >
                        <MoreHorizontal size={16} />
                      </button>
                      {activeMenuSessionId === session.id && (
                        <div className="options-dropdown-menu">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingSessionId(session.id);
                              setEditingValue(session.title);
                              setActiveMenuSessionId(null);
                            }}
                          >
                            Rename
                          </button>
                          <button
                            className="delete-option"
                            type="button"
                            onClick={() => onDeleteSession(session.id)}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="sidebar-bottom">
        {/* Theme Switcher */}
        <button className="nav-action" onClick={onToggleTheme} title="Switch Dark/Light Theme">
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
        <button className="nav-action" onClick={onOpenSettings} title="Open Settings">
          <Settings size={16} />
          Settings
        </button>

        {authLoading ? (
          <div className="login-spinner-container">
            <span className="login-spinner"></span>
            <span>Connecting...</span>
          </div>
        ) : user ? (
          <div className="user-profile-container">
            <div className="user-profile-trigger" onClick={(e) => { e.stopPropagation(); setUserDropdownOpen(!userDropdownOpen); }} title="Account Settings">
              <img src={user.photoURL || "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y"} alt={user.displayName} className="avatar" />
              <span className="username-text" title={user.displayName}>{user.displayName}</span>
            </div>
            <div className={`user-dropdown ${userDropdownOpen ? "open" : ""}`} onClick={(e) => e.stopPropagation()}>
              <button type="button" className="dropdown-logout-btn" onClick={onLogout}>
                Sign Out
              </button>
            </div>
          </div>
        ) : (
          <button className="login-button" onClick={onLogin}>
            <LogIn size={16} />
            Login
          </button>
        )}
      </div>
    </aside>
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

const rootElement = document.getElementById("root");
const reactRoot = window.__stomataReactRoot || createRoot(rootElement);
window.__stomataReactRoot = reactRoot;
reactRoot.render(<App />);
