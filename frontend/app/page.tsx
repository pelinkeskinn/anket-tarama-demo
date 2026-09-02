"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";

import { CAMERA_JPEG_QUALITY, captureScale, framesEqual, fullCameraFrame, guideCaptureRegion, type CaptureRegion } from "@/lib/camera";
import { getLocalForm, localSummaries, removeLocalForm, upsertLocalForm } from "@/lib/formArchive";
import { pushAppScreen, readPopStateScreen, replaceAppScreen, type AppScreen } from "@/lib/screenNavigation";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://anket-tarama-backend.onrender.com").replace(/\/$/, "");
const ADMIN_TOKEN = process.env.NEXT_PUBLIC_ADMIN_TOKEN ?? "";
const CAMERA_CHECK_INTERVAL_MS = 220;
const REQUIRED_STABLE_FRAMES = 2;
const FROZEN_FRAME_CHECKS = 10;
const ANALYZE_TIMEOUT_MS = 45000;
const HISTORY_PAGE_SIZE = 50;
const HISTORY_CACHE_KEY = "anketFormsCache";

type AnswerValue = "NEVER" | "SOMETIMES" | "OFTEN" | "ALWAYS" | "BLANK";
type AnswerStatus = "OK" | "BLANK" | "DOUBLE_MARK" | "UNCERTAIN" | "MARKED" | "MULTIPLE" | "INVALID" | "AMBIGUOUS";
type AnswerSource = "AUTO" | "MANUAL" | "UNRESOLVED";
type Screen = AppScreen;
type CameraState = "idle" | "ready" | "denied" | "unsupported" | "insecure" | "stalled";

type Answer = {
  questionNo: number;
  value: AnswerValue | null;
  confidence: number;
  source: AnswerSource;
  status: AnswerStatus;
  manualCorrection?: string | null;
  section?: number | null;
  selectedIndex?: number | null;
  selectedLabel?: string | null;
  optionLabels?: string[] | null;
  scores?: number[] | null;
};

type ProcessingStats = {
  totalMs: number;
  perspectiveMs: number;
  omrMs: number;
};

type Analysis = {
  analysisId: string;
  templateCode: string;
  status: "OK" | "REVIEW_REQUIRED" | "TOO_MANY_UNCERTAIN";
  formConfidence: number;
  blankCount: number;
  reviewRequiredCount: number;
  answers: Answer[];
  processing?: ProcessingStats;
};

type StoredSummary = {
  id: number;
  createdAt: string;
  formConfidence: number;
  blankCount: number;
  manualCount: number;
  possibleDuplicate?: boolean;
};

type StoredDetail = StoredSummary & {
  analysisId: string;
  templateCode: string;
  answers: Answer[];
};

const labels: Record<AnswerValue | AnswerStatus, string> = {
  NEVER: "Hiçbir zaman",
  SOMETIMES: "Bazen",
  OFTEN: "Sık sık",
  ALWAYS: "Her zaman",
  BLANK: "Boş",
  OK: "Okundu",
  MARKED: "Geçerli işaret",
  DOUBLE_MARK: "Çift işaret",
  MULTIPLE: "Birden fazla işaret",
  INVALID: "Geçersiz işaret",
  UNCERTAIN: "Belirsiz",
  AMBIGUOUS: "Kararsız"
};

type DatabaseStatus = "checking" | "connected" | "unavailable";

export default function Page() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const submittingRef = useRef(false);
  const autoCaptureRef = useRef(false);
  const previousFrameRef = useRef<Uint8ClampedArray | null>(null);
  const stableFramesRef = useRef(0);
  const frozenFramesRef = useRef(0);
  const restartingCameraRef = useRef(false);
  const screenRef = useRef<Screen>("scanner");
  const activeAnalyzeRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const analyzeSequenceRef = useRef(0);
  const [screen, setScreen] = useState<Screen>("scanner");
  const [cameraState, setCameraState] = useState<CameraState>("idle");
  const [quality, setQuality] = useState<"bad" | "warn" | "ready">("bad");
  const [guidance, setGuidance] = useState("Formu çerçevenin içine alın");
  const [processingText, setProcessingText] = useState("Fotoğraf alındı.\nKağıdı kaldırabilirsiniz.");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [finalAnalysis, setFinalAnalysis] = useState<Analysis | null>(null);
  const [manualSelections, setManualSelections] = useState<Record<number, AnswerValue>>({});
  const [scannedCount, setScannedCount] = useState(0);
  const [databaseStatus, setDatabaseStatus] = useState<DatabaseStatus>("checking");
  const [error, setError] = useState("");
  const [history, setHistory] = useState<StoredSummary[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [deletingHistory, setDeletingHistory] = useState(false);
  const [selectedHistoryIds, setSelectedHistoryIds] = useState<Set<number>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [detail, setDetail] = useState<StoredDetail | null>(null);
  const [pendingDuplicate, setPendingDuplicate] = useState<Analysis | null>(null);
  const [savedFormId, setSavedFormId] = useState<number | null>(null);

  screenRef.current = screen;

  function goToScreen(next: Screen, mode: "push" | "replace" | "silent" = "push") {
    setScreen(next);
    if (mode === "push") pushAppScreen(next);
    if (mode === "replace") replaceAppScreen(next);
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }

  useEffect(() => {
    const cache = readHistoryCache();
    const local = localSummaries();
    if (local.items.length > 0 && cache.items.length === 0) {
      writeHistoryCache(mergeHistorySummaries([], local.items), cache.total);
    }
    replaceAppScreen("scanner");
    void refreshDatabaseState();
    if (!window.isSecureContext) {
      setCameraState("insecure");
    }
    const onPopState = (event: PopStateEvent) => {
      const next = readPopStateScreen(event);
      if (!next) {
        return;
      }
      goToScreen(next, "silent");
    };
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
      stopCamera();
    };
  }, []);

  useEffect(() => {
    if (screen !== "scanner") {
      pauseCamera();
    }
  }, [screen]);

  useEffect(() => {
    if (screen === "scanner" && cameraState === "idle") {
      void requestCamera();
    }
  }, [screen, cameraState]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState !== "visible" || screenRef.current !== "scanner") {
        return;
      }
      setGuidance("Kamera yeniden başlatılıyor…");
      pauseCamera();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (cameraState === "ready" && screen === "scanner" && videoRef.current && streamRef.current) {
      const animationFrame = window.requestAnimationFrame(() => {
        void attachCameraStream();
      });
      return () => window.cancelAnimationFrame(animationFrame);
    }
  }, [cameraState, screen]);

  useEffect(() => {
    if (cameraState !== "ready" || screen !== "scanner") {
      return;
    }
    autoCaptureRef.current = false;
    previousFrameRef.current = null;
    stableFramesRef.current = 0;
    frozenFramesRef.current = 0;
    const timer = window.setInterval(() => {
      const video = videoRef.current;
      if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || submittingRef.current || autoCaptureRef.current) {
        return;
      }
      const check = inspectCameraFrame(video, frameRef.current, previousFrameRef.current);
      if (framesEqual(previousFrameRef.current, check.frame)) {
        frozenFramesRef.current += 1;
        if (frozenFramesRef.current >= FROZEN_FRAME_CHECKS && !restartingCameraRef.current) {
          frozenFramesRef.current = 0;
          setGuidance("Kamera yeniden başlatılıyor…");
          pauseCamera();
          return;
        }
      } else {
        frozenFramesRef.current = 0;
      }
      previousFrameRef.current = check.frame;
      if (check.brightness < 45) {
        stableFramesRef.current = 0;
        setQuality("bad");
        setGuidance("Ortam çok karanlık — ışığı artırın");
        return;
      }
      // The page may occupy less of the frame on a coloured desk or when a
      // second sheet is visible.  Backend page/marker detection makes the
      // final decision, so keep the live camera gate deliberately permissive.
      if (check.paperRatio < 0.16) {
        stableFramesRef.current = 0;
        setQuality("bad");
        setGuidance("Formun tamamını çerçevenin içine alın");
        return;
      }
      if (check.sharpness < 3.2) {
        stableFramesRef.current = 0;
        setQuality("warn");
        setGuidance("Görüntü net değil — kamerayı sabit tutun");
        return;
      }
      if (check.motion > 12) {
        stableFramesRef.current = 0;
        setQuality("warn");
        setGuidance("Telefonu sabit tutun");
        return;
      }
      stableFramesRef.current += 1;
      if (stableFramesRef.current < REQUIRED_STABLE_FRAMES) {
        setQuality("warn");
        setGuidance("Form bulundu — sabit tutun");
        return;
      }
      setQuality("ready");
      setGuidance("Form algılandı — otomatik taranıyor");
      autoCaptureRef.current = true;
      window.clearInterval(timer);
      void captureAndAnalyze(true);
    }, CAMERA_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [cameraState, screen]);

  const reviewAnswers = useMemo(
    () => analysis?.answers.filter((answer) => isReviewStatus(answer.status)) ?? [],
    [analysis]
  );

  const blankAnswers = useMemo(
    () => finalAnalysis?.answers.filter((answer) => answer.value === "BLANK" || answer.status === "BLANK") ?? [],
    [finalAnalysis]
  );

  async function requestCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraState("unsupported");
      return;
    }
    if (!window.isSecureContext) {
      setCameraState("insecure");
      return;
    }
    restartingCameraRef.current = true;
    stopCamera();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 2560 },
          height: { ideal: 1920 },
          aspectRatio: { ideal: 4 / 3 }
        },
        audio: false
      });
      streamRef.current = stream;
      setCameraState("ready");
      await attachCameraStream();
    } catch {
      setCameraState("denied");
    } finally {
      restartingCameraRef.current = false;
    }
  }

  async function attachCameraStream() {
    const video = videoRef.current;
    const stream = streamRef.current;
    if (!video || !stream) {
      return;
    }
    if (video.srcObject !== stream) {
      video.srcObject = stream;
    }
    if (video.readyState === 0) {
      return;
    }
    try {
      await video.play();
    } catch {
      await sleep(300);
      try {
        await video.play();
      } catch {
        setCameraState("stalled");
      }
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    const video = videoRef.current;
    if (video) {
      video.srcObject = null;
    }
  }

  function pauseCamera() {
    stopCamera();
    setCameraState((current) =>
      current === "denied" || current === "unsupported" || current === "insecure" ? current : "idle"
    );
  }

  async function captureAndAnalyze(automatic = false) {
    if (!videoRef.current || submittingRef.current) {
      return;
    }
    const video = videoRef.current;
    const capture = guideCaptureRegion(video, frameRef.current);
    const fullCapture = fullCameraFrame(video);
    const blob = await cameraFrameBlob(video, capture);
    const fallbackBlob =
      capture.width < fullCapture.width * 0.95 || capture.height < fullCapture.height * 0.95
        ? await cameraFrameBlob(video, fullCapture)
        : null;
    if (blob) {
      await analyzeBlob(blob, { templateHint: "HEALTHY_NUTRITION", guidedCapture: true, fallbackBlob });
    } else if (automatic) {
      autoCaptureRef.current = false;
    }
  }

  async function cameraFrameBlob(video: HTMLVideoElement, capture: CaptureRegion) {
    const scale = captureScale(capture.width, capture.height);
    const canvas = document.createElement("canvas");
    canvas.width = capture.width;
    canvas.height = capture.height;
    canvas.width = Math.max(1, Math.round(capture.width * scale));
    canvas.height = Math.max(1, Math.round(capture.height * scale));
    const context = canvas.getContext("2d");
    if (context) {
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
    }
    context?.drawImage(video, capture.x, capture.y, capture.width, capture.height, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", CAMERA_JPEG_QUALITY));
  }

  async function analyzeBlob(
    blob: Blob,
    options: { templateHint?: "HEALTHY_NUTRITION"; guidedCapture?: boolean; fallbackBlob?: Blob | null } = {}
  ) {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    const requestId = analyzeSequenceRef.current + 1;
    analyzeSequenceRef.current = requestId;
    const controller = new AbortController();
    activeAnalyzeRef.current = { id: requestId, controller };
    setError("");
    goToScreen("processing");
    setProcessingText("Fotoğraf alındı.\nKağıdı kaldırabilirsiniz.");
    let timedOut = false;
    const timeoutTimer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, ANALYZE_TIMEOUT_MS);
    const stageTimers = [
      window.setTimeout(() => {
        if (isCurrentAnalyzeRequest(requestId)) setProcessingText("Görüntü yükleniyor…");
      }, 400),
      window.setTimeout(() => {
        if (isCurrentAnalyzeRequest(requestId)) setProcessingText("Kenar/işaretçi tespiti…");
      }, 1600),
      window.setTimeout(() => {
        if (isCurrentAnalyzeRequest(requestId)) setProcessingText("Cevaplar okunuyor…");
      }, 3200)
    ];

    try {
      await warmBackend(controller.signal, (message) => {
        if (isCurrentAnalyzeRequest(requestId)) setProcessingText(message);
      });
      if (!isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      const postAnalysis = async (candidate: Blob, guidedCapture = false) => {
        const body = new FormData();
        body.append("image", candidate, candidate.type === "application/pdf" ? "scan.pdf" : "scan.jpg");
        body.append("clientRequestId", crypto.randomUUID());
        if (options.templateHint) body.append("templateHint", options.templateHint);
        if (guidedCapture) body.append("guidedCapture", "true");
        return await fetch(`${API_BASE}/api/omr/analyze`, { method: "POST", body, signal: controller.signal });
      };

      let response = await postAnalysis(blob, options.guidedCapture);
      // The guided crop is fast, but a partly covered/stacked sheet may extend
      // beyond it. Retry the full camera frame with page/marker detection.
      if (!response.ok && options.fallbackBlob) response = await postAnalysis(options.fallbackBlob, false);
      if (!isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      if (!response.ok) {
        throw new Error(await extractError(response));
      }
      let payload = (await response.json()) as Analysis;
      if (
        options.fallbackBlob &&
        (payload.status === "TOO_MANY_UNCERTAIN" || !payload.templateCode.startsWith("HEALTHY_NUTRITION_V"))
      ) {
        const fallbackResponse = await postAnalysis(options.fallbackBlob);
        if (fallbackResponse.ok) payload = (await fallbackResponse.json()) as Analysis;
      }
      if (!isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      handleAnalysis(payload);
    } catch (err) {
      if (!isCurrentAnalyzeRequest(requestId) && !timedOut) {
        return;
      }
      if (controller.signal.aborted && !timedOut) {
        return;
      }
      setError(timedOut || isTimeoutError(err) ? "Sunucu yanıt vermiyor, tekrar deneyin" : readClientError(err));
      goToScreen("fatal");
    } finally {
      window.clearTimeout(timeoutTimer);
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      if (activeAnalyzeRef.current?.id === requestId) {
        activeAnalyzeRef.current = null;
        submittingRef.current = false;
      }
    }
  }

  async function warmBackend(signal: AbortSignal, onStatus: (message: string) => void) {
    const deadline = Date.now() + 25000;
    let delay = 1000;
    let firstAttempt = true;
    while (Date.now() <= deadline) {
      if (signal.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      try {
        const response = await fetch(`${API_BASE}/healthz`, { cache: "no-store", signal });
        if (response.ok || ![502, 503, 504].includes(response.status)) {
          return;
        }
      } catch (err) {
        if (signal.aborted) {
          throw err;
        }
      }
      if (firstAttempt) {
        onStatus("Sunucu uyandırılıyor, birkaç saniye sürebilir…");
        firstAttempt = false;
      }
      await sleep(Math.min(delay, deadline - Date.now()), signal);
      delay = Math.min(delay * 2, 8000);
    }
    throw new Error("Sunucu yanıt vermiyor, tekrar deneyin");
  }

  function isCurrentAnalyzeRequest(requestId: number) {
    return activeAnalyzeRef.current?.id === requestId && !activeAnalyzeRef.current.controller.signal.aborted;
  }

  function cancelAnalyzeAndReturnToScanner() {
    activeAnalyzeRef.current?.controller.abort();
    activeAnalyzeRef.current = null;
    submittingRef.current = false;
    goToScreen("scanner", "replace");
  }

  function handleAnalysis(payload: Analysis) {
    setAnalysis(payload);
    setFinalAnalysis(null);
    setManualSelections({});
    if (payload.status === "TOO_MANY_UNCERTAIN") {
      setError("Bu formda çok fazla cevap güvenilir biçimde okunamadı.\nFormu yeniden taratın.");
      goToScreen("fatal");
      return;
    }
    if (payload.reviewRequiredCount > 0) {
      goToScreen("manual");
      return;
    }
    setFinalAnalysis(payload);
    if (payload.blankCount > 0) {
      goToScreen("blankConfirm");
      return;
    }
    void completeOrWarnDuplicate(payload);
  }

  function chooseManual(questionNo: number, value: AnswerValue) {
    setManualSelections((current) => ({ ...current, [questionNo]: value }));
  }

  function continueManual() {
    if (!analysis || reviewAnswers.some((answer) => !manualSelections[answer.questionNo])) {
      return;
    }
    const updated: Analysis = {
      ...analysis,
      reviewRequiredCount: 0,
      status: "OK",
      answers: analysis.answers.map((answer) => {
        const value = manualSelections[answer.questionNo];
        if (!value) {
          return answer;
        }
        return {
          ...answer,
          value,
          status: value === "BLANK" ? "BLANK" : analysis.templateCode.startsWith("HEALTHY_NUTRITION_V") ? "MARKED" : "OK",
          source: "MANUAL",
          confidence: 1,
          manualCorrection: answerOptionLabelForAnswer(analysis.templateCode, answer, value)
        };
      })
    };
    updated.blankCount = updated.answers.filter((answer) => answer.value === "BLANK").length;
    setFinalAnalysis(updated);
    if (updated.blankCount > 0) {
      goToScreen("blankConfirm");
      return;
    }
    void completeOrWarnDuplicate(updated);
  }

  async function completeOrWarnDuplicate(payload: Analysis) {
    if (looksDuplicate(payload)) {
      setPendingDuplicate(payload);
      goToScreen("duplicate");
      return;
    }
    await saveAndShowSuccess(payload);
  }

  async function saveAndShowSuccess(payload: Analysis) {
    const response = await fetch(`${API_BASE}/api/forms`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({
        analysisId: payload.analysisId,
        templateCode: payload.templateCode,
        formConfidence: payload.formConfidence,
        answers: payload.answers
      })
    });
    if (!response.ok) {
      setError("Cevaplar veritabanına kaydedilemedi.");
      goToScreen("fatal");
      return;
    }
    rememberSequence(payload);
    const saved = (await response.json()) as StoredDetail;
    setSavedFormId(saved.id);
    setFinalAnalysis(payload);
    rememberCachedForm(saved);
    upsertLocalForm(saved);
    goToScreen("success");
    void refreshDatabaseState();
  }

  function retryFromReview() {
    setAnalysis(null);
    setFinalAnalysis(null);
    setManualSelections({});
    goToScreen("scanner", "replace");
  }

  async function discardSavedAndRescan() {
    if (savedFormId != null) {
      await fetch(`${API_BASE}/api/forms/${savedFormId}`, { method: "DELETE", headers: adminHeaders() });
    }
    setSavedFormId(null);
    setAnalysis(null);
    setFinalAnalysis(null);
    setPendingDuplicate(null);
    setManualSelections({});
    goToScreen("scanner", "replace");
    void refreshDatabaseState();
  }

  function nextForm() {
    setAnalysis(null);
    setFinalAnalysis(null);
    setPendingDuplicate(null);
    setSavedFormId(null);
    setManualSelections({});
    setQuality("bad");
    setGuidance("Taranan formu kaldırın");
    goToScreen("scanner", "replace");
    window.setTimeout(() => setGuidance("Yeni formu yerleştirin"), 1800);
    void refreshDatabaseState();
  }

  async function refreshDatabaseState() {
    try {
      const response = await fetch(`${API_BASE}/readyz`, { cache: "no-store" });
      const payload = (await response.json()) as { status?: string; database?: string };
      // Older deployed backends return only { status: "ready" }. That endpoint
      // still runs SELECT 1, so it is a valid database-connection confirmation.
      if (!response.ok || payload.status !== "ready" || (payload.database != null && payload.database !== "connected")) {
        setDatabaseStatus("unavailable");
        return;
      }
      setDatabaseStatus("connected");
      await refreshRecordCount();
    } catch {
      setDatabaseStatus("unavailable");
    }
  }

  async function refreshRecordCount() {
    try {
      const response = await fetch(`${API_BASE}/api/forms?limit=1&offset=0`, { headers: adminHeaders() });
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as { total?: number };
      if (typeof payload.total === "number") {
        const cache = readHistoryCache();
        const local = localSummaries();
        const mergedItems = mergeHistorySummaries(cache.items, local.items);
        const total = payload.total;
        setScannedCount(total);
        localStorage.setItem("demoScannedCount", String(total));
        writeHistoryCache(mergedItems, total);
      }
    } catch {
      setDatabaseStatus("unavailable");
    }
  }

  async function loadHistory(reset = true) {
    setHistoryLoading(true);
    const offset = reset ? 0 : history.length;
    try {
      const response = await fetch(`${API_BASE}/api/forms?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`, {
        headers: adminHeaders()
      });
      if (!response.ok) {
        if (reset) {
          const cache = readHistoryCache();
          setHistory(cache.items);
          setHistoryTotal(cache.total);
          goToScreen("history");
        }
        setHistoryLoading(false);
        return;
      }
      const payload = (await response.json()) as StoredSummary[] | { items: StoredSummary[]; total: number };
      const serverItems = Array.isArray(payload) ? payload : payload.items ?? [];
      const serverTotal = Array.isArray(payload) ? payload.length : payload.total ?? serverItems.length;
      const nextItems = reset
        ? serverItems
        : mergeHistorySummaries([...history, ...serverItems], []);
      const total = serverTotal;
      setHistory(nextItems);
      setHistoryTotal(total);
      setScannedCount(total);
      setSelectedHistoryIds((current) => new Set([...current].filter((id) => nextItems.some((item) => item.id === id))));
      writeHistoryCache(nextItems, total);
      if (screenRef.current === "history") {
        goToScreen("history", "silent");
      } else {
        goToScreen("history");
      }
    } catch {
      if (reset) {
        const cache = readHistoryCache();
        setHistory(cache.items);
        setHistoryTotal(cache.total);
        goToScreen("history");
      }
    }
    setHistoryLoading(false);
  }

  async function openDetail(id: number) {
    try {
      const response = await fetch(`${API_BASE}/api/forms/${id}`, { headers: adminHeaders() });
      if (response.ok) {
        const saved = (await response.json()) as StoredDetail;
        upsertLocalForm(saved);
        setDetail(saved);
        goToScreen("detail");
        return;
      }
    } catch {
      // Fall back to the local archive when the server is unavailable.
    }
    const local = getLocalForm(id);
    if (local) {
      setDetail(local as StoredDetail);
      goToScreen("detail");
    }
  }

  async function deleteDetail(id: number) {
    await fetch(`${API_BASE}/api/forms/${id}`, { method: "DELETE", headers: adminHeaders() });
    removeLocalForm(id);
    const cache = readHistoryCache();
    const nextItems = cache.items.filter((item) => item.id !== id);
    writeHistoryCache(nextItems, Math.max(0, cache.total - (cache.items.some((item) => item.id === id) ? 1 : 0)));
    setDetail(null);
    await loadHistory(true);
  }

  async function deleteHistoryRecords(ids: number[]) {
    if (ids.length === 0 || deletingHistory) return;

    setDeletingHistory(true);
    try {
      const results = await Promise.all(
        ids.map(async (id) => ({
          id,
          response: await fetch(`${API_BASE}/api/forms/${id}`, { method: "DELETE", headers: adminHeaders() })
        }))
      );
      const deletedIds = results.filter(({ response }) => response.ok).map(({ id }) => id);
      if (deletedIds.length === 0) throw new Error("No records were deleted");

      for (const id of deletedIds) removeLocalForm(id);
      const cache = readHistoryCache();
      const nextItems = cache.items.filter((item) => !deletedIds.includes(item.id));
      writeHistoryCache(nextItems, Math.max(0, cache.total - deletedIds.length));
      setSelectedHistoryIds(new Set());
      if (deletedIds.length !== ids.length) setError("Bazı kayıtlar silinemedi.");
      await loadHistory(true);
    } catch {
      setError("Seçilen kayıtlar silinemedi.");
    } finally {
      setDeletingHistory(false);
    }
  }

  async function exportExcel(format: "numeric" | "text" = "numeric") {
    setExporting(true);
    try {
      const response = await fetch(`${API_BASE}/api/forms/export.xlsx?format=${format}`, { headers: adminHeaders() });
      if (!response.ok) {
        throw new Error("Excel hazırlanamadı.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = format === "text" ? "anket-kayitlari-metin.xlsx" : "anket-kayitlari.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Excel hazırlanamadı.");
    } finally {
      setExporting(false);
    }
  }

  if (screen === "history") {
    return (
      <HistoryScreen
        scannedCount={scannedCount}
        databaseStatus={databaseStatus}
        forms={history}
        total={historyTotal}
        loading={historyLoading}
        exporting={exporting}
        onBack={() => goToScreen("scanner", "replace")}
        onOpen={openDetail}
        onExport={exportExcel}
        onLoadMore={() => void loadHistory(false)}
        selectedIds={selectedHistoryIds}
        deleting={deletingHistory}
        onToggleSelection={(id) =>
          setSelectedHistoryIds((current) => {
            const next = new Set(current);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
          })
        }
        onToggleAll={() =>
          setSelectedHistoryIds((current) =>
            current.size === history.length ? new Set() : new Set(history.map((form) => form.id))
          )
        }
        onDeleteSelected={() => void deleteHistoryRecords([...selectedHistoryIds])}
      />
    );
  }

  if (screen === "detail" && detail) {
    return <DetailScreen scannedCount={scannedCount} databaseStatus={databaseStatus} detail={detail} onBack={() => void loadHistory(true)} onDelete={deleteDetail} />;
  }

  return (
    <main className="app">
      <Header scannedCount={scannedCount} databaseStatus={databaseStatus} onHistory={() => void loadHistory(true)} />
      {screen === "scanner" && (
        <section className="scan">
          <div className="scan-intro">
            <strong>Anket tarama</strong>
            <span>Formu çerçevenin içine yerleştirin; görüntü netleştiğinde tarama otomatik başlar.</span>
          </div>
          <div className={`camera-shell ${cameraState === "ready" ? "camera-active" : ""}`}>
            {cameraState === "ready" ? (
              <video ref={videoRef} autoPlay playsInline muted onLoadedMetadata={() => void attachCameraStream()} />
            ) : (
              <CameraFallback state={cameraState} onRequest={requestCamera} />
            )}
            {cameraState === "ready" && (
              <>
                <div ref={frameRef} className={`frame ${quality}`} aria-label="A4 hizalama çerçevesi">
                  <span className="corner tl" />
                  <span className="corner tr" />
                  <span className="corner br" />
                  <span className="corner bl" />
                </div>
                <div className="guidance">{guidance}</div>
              </>
            )}
          </div>

          <div className="actions">
            {cameraState === "ready" && (
              <button className="scan-button" onClick={() => void captureAndAnalyze()} disabled={submittingRef.current}>
                TARAT
              </button>
            )}
          </div>
        </section>
      )}

      {screen === "processing" && (
        <StatusScreen title={processingText} button="İptal Et" onClick={cancelAnalyzeAndReturnToScanner} />
      )}

      {screen === "manual" && analysis && (
        <ManualReview
          templateCode={analysis.templateCode}
          answers={reviewAnswers}
          selections={manualSelections}
          onSelect={chooseManual}
          onContinue={continueManual}
          onRetry={retryFromReview}
        />
      )}

      {screen === "blankConfirm" && finalAnalysis && (
        <BlankConfirm blanks={blankAnswers} onRetry={() => goToScreen("scanner", "replace")} onContinue={() => void completeOrWarnDuplicate(finalAnalysis)} />
      )}

      {screen === "duplicate" && pendingDuplicate && (
        <DuplicateWarning
          onSkip={nextForm}
          onContinue={() => void saveAndShowSuccess(pendingDuplicate)}
          onRetry={() => goToScreen("scanner", "replace")}
        />
      )}

      {screen === "success" && finalAnalysis && (
        <SuccessScreen analysis={finalAnalysis} onNext={nextForm} onDiscard={() => void discardSavedAndRescan()} />
      )}

      {screen === "fatal" && <StatusScreen title={error} button="TEKRAR TARAT" onClick={() => goToScreen("scanner", "replace")} />}
    </main>
  );
}

function Header({
  scannedCount,
  databaseStatus = "checking",
  onHistory
}: {
  scannedCount: number;
  databaseStatus?: DatabaseStatus;
  onHistory: () => void;
}) {
  const databaseLabel =
    databaseStatus === "connected" ? "Veritabanı: Bağlı" : databaseStatus === "unavailable" ? "Veritabanı: Bağlantı yok" : "Veritabanı: Kontrol ediliyor…";
  return (
    <header className="topbar">
      <div>
        <div className="title">anket-tarama</div>
        <div className="counter">Taranan: {scannedCount}</div>
        <div className={`database-status ${databaseStatus}`}>{databaseLabel}</div>
      </div>
      <button className="ghost-button" onClick={onHistory}>
        Geçmiş Taramalar
      </button>
    </header>
  );
}

function CameraFallback({
  state,
  onRequest
}: {
  state: CameraState;
  onRequest: () => void;
}) {
  let title = "Kamera kapalı";
  let message = "Taramaya başlamak için kamerayı açın.";
  if (state === "denied") {
    title = "Kamera izni gerekli";
    message = "Form tarayabilmek için kamera izni vermeniz gerekiyor.";
  }
  if (state === "idle" || state === "stalled") {
    title = state === "stalled" ? "Kamera durdu" : "Kamera kapalı";
    message = state === "stalled" ? "Yeniden başlatmak için aşağıdaki düğmeyi kullanın." : "Formu kadraja aldıktan sonra taramayı siz başlatacaksınız.";
  }
  if (state === "unsupported") {
    title = "Kamera desteklenmiyor";
    message = "Bu tarayıcı kamera ile taramayı desteklemiyor.";
  }
  if (state === "insecure") {
    title = "Güvenli bağlantı gerekli";
    message = "Kamera için güvenli bağlantı gerekiyor. Telefonu HTTPS tüneli ya da localhost üzerinden açın.";
  }
  return (
    <div className="camera-placeholder">
      <div className="camera-placeholder-card">
        <span className="camera-icon" aria-hidden="true">▣</span>
        <strong>{title}</strong>
        <p>{message}</p>
        {(state === "denied" || state === "idle" || state === "insecure" || state === "stalled") && (
          <button className="primary-button" onClick={onRequest}>
            Kamerayı Başlat
          </button>
        )}
      </div>
    </div>
  );
}

function StatusScreen({ title, button, onClick }: { title: string; button?: string; onClick?: () => void }) {
  return (
    <section className="screen">
      <div className="panel stack">
        {title.split("\n").map((line) => (
          <div className="status-title" key={line}>
            {line}
          </div>
        ))}
      </div>
      {button && (
        <div className="action-bar">
          <button className="primary-button" onClick={onClick}>
            {button}
          </button>
        </div>
      )}
    </section>
  );
}

const ReviewQuestion = memo(function ReviewQuestion({
  templateCode,
  answer,
  selected,
  onSelect
}: {
  templateCode: string;
  answer: Answer;
  selected?: AnswerValue;
  onSelect: (questionNo: number, value: AnswerValue) => void;
}) {
  const selectableValues =
    answer.optionLabels?.length === 3
      ? (["NEVER", "SOMETIMES", "ALWAYS", "BLANK"] as const)
      : (["NEVER", "SOMETIMES", "OFTEN", "ALWAYS", "BLANK"] as const);
  return (
    <div className="panel stack">
      <strong>Soru {answer.questionNo}</strong>
      <span className="muted">{labels[answer.status]}</span>
      <div className="review-options">
        {selectableValues.map((value) => (
          <button
            key={value}
            className={`option-button ${selected === value ? "selected" : ""}`}
            onClick={() => onSelect(answer.questionNo, value)}
          >
            {value === "BLANK" ? "Boş bırak" : answerOptionLabelForAnswer(templateCode, answer, value)}
          </button>
        ))}
      </div>
    </div>
  );
});

function ManualReview({
  templateCode,
  answers,
  selections,
  onSelect,
  onContinue,
  onRetry
}: {
  templateCode: string;
  answers: Answer[];
  selections: Record<number, AnswerValue>;
  onSelect: (questionNo: number, value: AnswerValue) => void;
  onContinue: () => void;
  onRetry: () => void;
}) {
  const complete = answers.every((answer) => selections[answer.questionNo]);
  return (
    <section className="screen">
      <div className="status-title">Manuel kontrol</div>
      {answers.map((answer) => (
        <ReviewQuestion
          key={answer.questionNo}
          templateCode={templateCode}
          answer={answer}
          selected={selections[answer.questionNo]}
          onSelect={onSelect}
        />
      ))}
      <div className="action-bar">
        <button className="secondary-button" onClick={onRetry}>
          VAZGEÇ, YENİDEN TARA
        </button>
        <button className="primary-button" disabled={!complete} onClick={onContinue}>
          DEVAM ET
        </button>
      </div>
    </section>
  );
}

function BlankConfirm({ blanks, onRetry, onContinue }: { blanks: Answer[]; onRetry: () => void; onContinue: () => void }) {
  return (
    <section className="screen">
      <div className="panel stack">
        <div className="status-title">Bu formda {blanks.length} soru boş veya çok zayıf işaretli görünüyor.</div>
        {blanks.map((answer) => (
          <strong key={answer.questionNo}>Soru {answer.questionNo}</strong>
        ))}
      </div>
      <div className="action-bar">
        <button className="secondary-button" onClick={onRetry}>
          TEKRAR TARAT
        </button>
        <button className="primary-button" onClick={onContinue}>
          DEVAM ET
        </button>
      </div>
    </section>
  );
}

function DuplicateWarning({ onSkip, onContinue, onRetry }: { onSkip: () => void; onContinue: () => void; onRetry: () => void }) {
  return (
    <section className="screen">
      <div className="panel stack">
        <div className="status-title">Bu form daha önce taranmış bir forma benziyor.</div>
      </div>
      <div className="action-bar">
        <button className="danger-button" onClick={onSkip}>
          AYNI FORM — KAYDETME
        </button>
        <button className="primary-button" onClick={onContinue}>
          FARKLI FORM — DEVAM ET
        </button>
        <button className="secondary-button" onClick={onRetry}>
          TEKRAR TARAT
        </button>
      </div>
    </section>
  );
}

function SuccessScreen({ analysis, onNext, onDiscard }: { analysis: Analysis; onNext: () => void; onDiscard: () => void }) {
  const manualCount = analysis.answers.filter((answer) => answer.source === "MANUAL").length;
  const autoCount = analysis.answers.filter((answer) => answer.source === "AUTO").length;
  const blankCount = analysis.answers.filter((answer) => answer.value === "BLANK").length;
  const elapsed = analysis.processing ? (analysis.processing.totalMs / 1000).toFixed(1) : null;
  return (
    <section className="screen">
      <div className="panel success stack">
        <div className="status-title">Form başarıyla okundu</div>
        <div>Form güven puanı: %{Math.round(analysis.formConfidence * 100)}</div>
        <div>Otomatik okunan soru sayısı: {autoCount}</div>
        <div>Manuel düzeltilen soru sayısı: {manualCount}</div>
        <div>Boş cevap sayısı: {blankCount}</div>
        {elapsed && <div>{elapsed} sn'de tamamlandı</div>}
      </div>
      <AnswerList templateCode={analysis.templateCode} answers={analysis.answers} />
      <div className="action-bar">
        <button className="scan-button" onClick={onNext}>
          SONRAKİ FORMA GEÇ
        </button>
        <button className="danger-button" onClick={onDiscard}>
          Bu kaydı sil ve yeniden tara
        </button>
      </div>
    </section>
  );
}

function HistoryScreen({
  scannedCount,
  databaseStatus,
  forms,
  total,
  loading,
  exporting,
  onBack,
  onOpen,
  onExport,
  onLoadMore,
  selectedIds,
  deleting,
  onToggleSelection,
  onToggleAll,
  onDeleteSelected
}: {
  scannedCount: number;
  databaseStatus: DatabaseStatus;
  forms: StoredSummary[];
  total: number;
  loading: boolean;
  exporting: boolean;
  onBack: () => void;
  onOpen: (id: number) => void;
  onExport: (format: "numeric" | "text") => void;
  onLoadMore: () => void;
  selectedIds: Set<number>;
  deleting: boolean;
  onToggleSelection: (id: number) => void;
  onToggleAll: () => void;
  onDeleteSelected: () => void;
}) {
  const allSelected = forms.length > 0 && selectedIds.size === forms.length;
  return (
    <main className="app">
      <Header scannedCount={scannedCount} databaseStatus={databaseStatus} onHistory={onBack} />
      <section className="screen">
        <div className="status-title">Geçmiş Taramalar</div>
        {exporting && <div className="panel">Excel hazırlanıyor…</div>}
        <div className="export-actions">
          <button className="primary-button" onClick={() => onExport("numeric")} disabled={forms.length === 0 || exporting}>
            EXCEL'E AKTAR (sayısal)
          </button>
          <button className="secondary-button" onClick={() => onExport("text")} disabled={forms.length === 0 || exporting}>
            EXCEL'E AKTAR (metin)
          </button>
        </div>
        {forms.length > 0 && (
          <button className="danger-button" onClick={onDeleteSelected} disabled={selectedIds.size === 0 || deleting}>
            {deleting ? "Kayıtlar siliniyor…" : `Seçilenleri sil (${selectedIds.size})`}
          </button>
        )}
        {forms.length === 0 && <div className="panel">Kayıt bulunamadı.</div>}
        {forms.length > 0 && (
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th className="history-select-cell">
                    <input aria-label="Tüm kayıtları seç" type="checkbox" checked={allSelected} onChange={onToggleAll} />
                  </th>
                  <th>Kayıt</th>
                  <th>Tarih</th>
                  <th>Boş</th>
                  <th>Manuel</th>
                </tr>
              </thead>
              <tbody>
                {forms.map((form) => (
                  <tr key={form.id} onClick={() => onOpen(form.id)} tabIndex={0}>
                    <td className="history-select-cell" onClick={(event) => event.stopPropagation()}>
                      <input
                        aria-label={`Kayıt #${form.id} seç`}
                        type="checkbox"
                        checked={selectedIds.has(form.id)}
                        onChange={() => onToggleSelection(form.id)}
                      />
                    </td>
                    <td>
                      #{form.id}
                      {form.possibleDuplicate ? " *" : ""}
                    </td>
                    <td>{new Date(form.createdAt).toLocaleString("tr-TR")}</td>
                    <td>{form.blankCount}</td>
                    <td>{form.manualCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {forms.length < total && (
          <button className="secondary-button" onClick={onLoadMore} disabled={loading}>
            {loading ? "Yükleniyor…" : "Daha fazla yükle"}
          </button>
        )}
        <button className="secondary-button" onClick={onBack}>
          GERİ
        </button>
      </section>
    </main>
  );
}

function DetailScreen({
  scannedCount,
  databaseStatus,
  detail,
  onBack,
  onDelete
}: {
  scannedCount: number;
  databaseStatus: DatabaseStatus;
  detail: StoredDetail;
  onBack: () => void;
  onDelete: (id: number) => void;
}) {
  return (
    <main className="app">
      <Header scannedCount={scannedCount} databaseStatus={databaseStatus} onHistory={onBack} />
      <section className="screen">
        <div className="panel stack">
          <div className="status-title">Form #{detail.id}</div>
          <span>{new Date(detail.createdAt).toLocaleString("tr-TR")}</span>
          <span>Form güven puanı: %{Math.round(detail.formConfidence * 100)}</span>
          <span>Boş cevap: {detail.blankCount}</span>
          <span>Manuel düzeltme: {detail.manualCount}</span>
        </div>
        <AnswerList templateCode={detail.templateCode} answers={detail.answers} showConfidence />
        <button className="danger-button" onClick={() => onDelete(detail.id)}>
          KAYDI SİL
        </button>
        <button className="secondary-button" onClick={onBack}>
          GERİ
        </button>
      </section>
    </main>
  );
}

function AnswerList({ templateCode, answers, showConfidence = false }: { templateCode: string; answers: Answer[]; showConfidence?: boolean }) {
  return (
    <div className="answer-list">
      {answers.map((answer) => (
        <div className="answer-row" key={answer.questionNo}>
          <strong>{answer.questionNo}.</strong>
          <span>{answer.value ? answerOptionLabelForAnswer(templateCode, answer, answer.value) : labels[answer.status]}</span>
          <span className="badge">{answer.source === "MANUAL" ? "Manuel seçildi" : answer.source}</span>
          {showConfidence && <span className="muted">Güven: %{Math.round(answer.confidence * 100)}</span>}
          {answer.manualCorrection && <span className="muted">Düzeltme: {answer.manualCorrection}</span>}
        </div>
      ))}
    </div>
  );
}

function adminHeaders(): HeadersInit {
  return ADMIN_TOKEN ? { "X-Admin-Token": ADMIN_TOKEN } : {};
}

function mergeHistorySummaries(serverItems: StoredSummary[], localItems: StoredSummary[]): StoredSummary[] {
  const byId = new Map<number, StoredSummary>();
  for (const item of localItems) {
    byId.set(item.id, item);
  }
  for (const item of serverItems) {
    byId.set(item.id, item);
  }
  return [...byId.values()].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
}

function readHistoryCache(): { items: StoredSummary[]; total: number } {
  try {
    const raw = localStorage.getItem(HISTORY_CACHE_KEY);
    if (!raw) {
      return { items: [], total: Number(localStorage.getItem("demoScannedCount") ?? "0") };
    }
    const parsed = JSON.parse(raw) as { items?: StoredSummary[]; total?: number };
    return { items: parsed.items ?? [], total: parsed.total ?? parsed.items?.length ?? 0 };
  } catch {
    return { items: [], total: 0 };
  }
}

function writeHistoryCache(items: StoredSummary[], total: number) {
  localStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify({ items: items.slice(0, 200), total }));
  localStorage.setItem("demoScannedCount", String(total));
}

function rememberCachedForm(form: StoredDetail) {
  const cache = readHistoryCache();
  const summary: StoredSummary = {
    id: form.id,
    createdAt: form.createdAt,
    formConfidence: form.formConfidence,
    blankCount: form.blankCount,
    manualCount: form.manualCount,
    possibleDuplicate: form.possibleDuplicate
  };
  const isNew = cache.items.every((item) => item.id !== form.id);
  const items = [summary, ...cache.items.filter((item) => item.id !== form.id)];
  writeHistoryCache(items, isNew ? cache.total + 1 : cache.total);
}

function isTimeoutError(err: unknown): boolean {
  return err instanceof Error && (err.name === "AbortError" || err.message.includes("yanıt vermiyor"));
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

async function extractError(response: Response): Promise<string> {
  if ([502, 503, 504].includes(response.status)) {
    return "Sunucuya ulaşılamadı. Backend'in çalıştığından ve API adresinin doğru olduğundan emin olun.";
  }
  try {
    const payload = (await response.json()) as { detail?: { error?: { message?: string } } };
    return payload.detail?.error?.message ?? "İşlem başarısız oldu.";
  } catch {
    return "İşlem başarısız oldu.";
  }
}

function readClientError(err: unknown): string {
  if (err instanceof TypeError && err.message.toLowerCase().includes("fetch")) {
    return "Sunucuya ulaşılamadı. Backend'in çalıştığından ve API adresinin doğru olduğundan emin olun.";
  }
  return err instanceof Error ? err.message : "Form işlenemedi.";
}

function looksDuplicate(payload: Analysis): boolean {
  const current = sequence(payload);
  const previous = JSON.parse(localStorage.getItem("demoAnswerSequences") ?? "[]") as string[];
  return previous.some((item) => distance(item, current) <= 1);
}

function rememberSequence(payload: Analysis) {
  const current = sequence(payload);
  const previous = JSON.parse(localStorage.getItem("demoAnswerSequences") ?? "[]") as string[];
  localStorage.setItem("demoAnswerSequences", JSON.stringify([current, ...previous].slice(0, 20)));
}

function answerOptionLabel(templateCode: string, questionNo: number, value: AnswerValue): string {
  if (value === "BLANK") return labels.BLANK;
  if (templateCode === "HEALTHY_NUTRITION_V3") {
    return ({ NEVER: "Hiçbir zaman", SOMETIMES: "Bazen", OFTEN: "Sık sık", ALWAYS: "Her zaman" } as const)[value];
  }
  if (templateCode.startsWith("HEALTHY_NUTRITION_V") && questionNo >= 12) {
    return ({ NEVER: "Hiçbir zaman", SOMETIMES: "1-2 kez/hafta", OFTEN: "3-4 kez/hafta", ALWAYS: "5+ kez/hafta" } as const)[value];
  }
  if (!templateCode.startsWith("HEALTHY_NUTRITION_V")) return labels[value];
  return ({ NEVER: "Hiçbir zaman", SOMETIMES: "Ara sıra", OFTEN: "Sık sık", ALWAYS: "Her zaman" } as const)[value];
}

function answerOptionLabelForAnswer(templateCode: string, answer: Answer, value: AnswerValue): string {
  if (value === "BLANK") return labels.BLANK;
  const index = (["NEVER", "SOMETIMES", "OFTEN", "ALWAYS"] as const).indexOf(value);
  return answer.optionLabels?.[index] ?? answerOptionLabel(templateCode, answer.questionNo, value);
}

function isReviewStatus(status: AnswerStatus): boolean {
  return status === "DOUBLE_MARK" || status === "UNCERTAIN" || status === "MULTIPLE" || status === "INVALID" || status === "AMBIGUOUS";
}

function inspectCameraFrame(
  video: HTMLVideoElement,
  guide: HTMLElement | null,
  previous: Uint8ClampedArray | null
) {
  const width = 160;
  const height = 120;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    return { brightness: 0, paperRatio: 0, sharpness: 0, motion: 100, frame: new Uint8ClampedArray() };
  }
  const capture = guideCaptureRegion(video, guide);
  context.drawImage(video, capture.x, capture.y, capture.width, capture.height, 0, 0, width, height);
  const rgba = context.getImageData(0, 0, width, height).data;
  const frame = new Uint8ClampedArray(width * height);
  let brightnessTotal = 0;
  let paperPixels = 0;
  let edgeTotal = 0;
  let edgeSamples = 0;
  let motionTotal = 0;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = y * width + x;
      const rgbaIndex = index * 4;
      const gray = Math.round(rgba[rgbaIndex] * 0.299 + rgba[rgbaIndex + 1] * 0.587 + rgba[rgbaIndex + 2] * 0.114);
      frame[index] = gray;
      brightnessTotal += gray;
      if (gray >= 175) paperPixels += 1;
      if (x > 0) {
        edgeTotal += Math.abs(gray - frame[index - 1]);
        edgeSamples += 1;
      }
      if (y > 0) {
        edgeTotal += Math.abs(gray - frame[index - width]);
        edgeSamples += 1;
      }
      if (previous?.length === frame.length) motionTotal += Math.abs(gray - previous[index]);
    }
  }

  return {
    brightness: brightnessTotal / frame.length,
    paperRatio: paperPixels / frame.length,
    sharpness: edgeTotal / Math.max(edgeSamples, 1),
    motion: previous?.length === frame.length ? motionTotal / frame.length : 100,
    frame
  };
}

function sequence(payload: Analysis): string {
  return payload.answers.map((answer) => answer.value ?? answer.status).join("|");
}

function distance(left: string, right: string): number {
  const a = left.split("|");
  const b = right.split("|");
  const length = Math.max(a.length, b.length);
  let diff = 0;
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) {
      diff += 1;
    }
  }
  return diff;
}
