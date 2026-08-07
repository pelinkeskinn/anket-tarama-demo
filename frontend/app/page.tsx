"use client";

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = "";
const MAX_MANUAL_REVIEW_QUESTIONS = 4;
const MAX_CAPTURE_SIDE = 2200;
const CAMERA_JPEG_QUALITY = 0.86;

type AnswerValue = "NEVER" | "SOMETIMES" | "ALWAYS" | "BLANK";
type AnswerStatus = "OK" | "BLANK" | "DOUBLE_MARK" | "UNCERTAIN";
type AnswerSource = "AUTO" | "MANUAL" | "UNRESOLVED";
type Screen = "scanner" | "processing" | "manual" | "blankConfirm" | "success" | "duplicate" | "fatal" | "history" | "detail";

type Answer = {
  questionNo: number;
  value: AnswerValue | null;
  confidence: number;
  source: AnswerSource;
  status: AnswerStatus;
  manualCorrection?: string | null;
};

type Analysis = {
  analysisId: string;
  templateCode: string;
  status: "OK" | "REVIEW_REQUIRED" | "TOO_MANY_UNCERTAIN";
  formConfidence: number;
  blankCount: number;
  reviewRequiredCount: number;
  answers: Answer[];
};

type StoredSummary = {
  id: number;
  createdAt: string;
  formConfidence: number;
  blankCount: number;
  manualCount: number;
};

type StoredDetail = StoredSummary & {
  analysisId: string;
  templateCode: string;
  answers: Answer[];
};

const labels: Record<AnswerValue | AnswerStatus, string> = {
  NEVER: "Hiçbir zaman",
  SOMETIMES: "Bazen",
  ALWAYS: "Her zaman",
  BLANK: "Boş",
  OK: "Okundu",
  DOUBLE_MARK: "Çift işaret",
  UNCERTAIN: "Belirsiz"
};

const demoForms = [
  ["filled-clean-v2.png", "V2 profesyonel form"],
  ["filled-faint-v2.png", "V2 soluk işaretli form"],
  ["filled-clean.png", "Temiz form"],
  ["filled-with-blanks.png", "Boş cevaplı form"],
  ["filled-double-mark.png", "Çift işaretli form"],
  ["filled-faint-marks.png", "Soluk işaretli form"],
  ["filled-erased-mark.png", "Silgi izli form"],
  ["filled-perspective.png", "Perspektifli form"],
  ["filled-shadow.png", "Gölgeli form"],
  ["filled-blurry.png", "Bulanık form"]
] as const;

export default function Page() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const submittingRef = useRef(false);
  const activeAnalyzeRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const analyzeSequenceRef = useRef(0);
  const [screen, setScreen] = useState<Screen>("scanner");
  const [cameraState, setCameraState] = useState<"idle" | "ready" | "denied" | "unsupported" | "insecure">("idle");
  const [quality, setQuality] = useState<"bad" | "warn" | "ready">("bad");
  const [guidance, setGuidance] = useState("Formu çerçevenin içine alın");
  const [processingText, setProcessingText] = useState("Fotoğraf alındı.\nKağıdı kaldırabilirsiniz.");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [finalAnalysis, setFinalAnalysis] = useState<Analysis | null>(null);
  const [manualSelections, setManualSelections] = useState<Record<number, AnswerValue>>({});
  const [scannedCount, setScannedCount] = useState(0);
  const [error, setError] = useState("");
  const [demoName, setDemoName] = useState<string>(demoForms[0][0]);
  const [history, setHistory] = useState<StoredSummary[]>([]);
  const [detail, setDetail] = useState<StoredDetail | null>(null);
  const [pendingDuplicate, setPendingDuplicate] = useState<Analysis | null>(null);

  useEffect(() => {
    setScannedCount(Number(localStorage.getItem("demoScannedCount") ?? "0"));
    if (!window.isSecureContext) {
      setCameraState("insecure");
    } else {
      void requestCamera();
    }
    return () => stopCamera();
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
    let step = 0;
    const messages = [
      ["bad", "Formu çerçevenin içine alın"],
      ["warn", "Telefonu sabit tutun"],
      ["warn", "Dört referans işareti görünmüyor"],
      ["ready", "Taratmaya hazır"]
    ] as const;
    const timer = window.setInterval(() => {
      const [nextQuality, nextMessage] = messages[Math.min(step, messages.length - 1)];
      setQuality(nextQuality);
      setGuidance(nextMessage);
      step += 1;
    }, 900);
    return () => window.clearInterval(timer);
  }, [cameraState, screen]);

  const reviewAnswers = useMemo(
    () => analysis?.answers.filter((answer) => answer.status === "DOUBLE_MARK" || answer.status === "UNCERTAIN") ?? [],
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
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false
      });
      streamRef.current = stream;
      setCameraState("ready");
      await attachCameraStream();
    } catch {
      setCameraState("denied");
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
      // Some mobile browsers only allow playback after the element finishes loading metadata.
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function captureAndAnalyze() {
    if (!videoRef.current || submittingRef.current || quality !== "ready") {
      return;
    }
    const video = videoRef.current;
    const capture = fullCameraFrame(video);
    const scale = Math.min(1, MAX_CAPTURE_SIDE / Math.max(capture.width, capture.height));
    const canvas = document.createElement("canvas");
    canvas.width = capture.width;
    canvas.height = capture.height;
    canvas.width = Math.max(1, Math.round(capture.width * scale));
    canvas.height = Math.max(1, Math.round(capture.height * scale));
    const context = canvas.getContext("2d");
    context?.drawImage(video, capture.x, capture.y, capture.width, capture.height, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", CAMERA_JPEG_QUALITY));
    if (blob) {
      await analyzeBlob(blob);
    }
  }

  async function analyzeBlob(blob: Blob) {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    const requestId = analyzeSequenceRef.current + 1;
    analyzeSequenceRef.current = requestId;
    const controller = new AbortController();
    activeAnalyzeRef.current = { id: requestId, controller };
    setError("");
    setScreen("processing");
    setProcessingText("Fotoğraf alındı.\nKağıdı kaldırabilirsiniz.");
    const slowTimer = window.setTimeout(() => setProcessingText("İşlem beklenenden uzun sürüyor."), 9000);
    const processingTimer = window.setTimeout(() => setProcessingText("Form işleniyor..."), 700);

    try {
      await warmBackend();
      const body = new FormData();
      body.append("image", blob, "scan.jpg");
      body.append("clientRequestId", crypto.randomUUID());
      const response = await fetch(`${API_BASE}/api/omr/analyze`, { method: "POST", body, signal: controller.signal });
      if (!isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      if (!response.ok) {
        throw new Error(await extractError(response));
      }
      const payload = (await response.json()) as Analysis;
      if (!isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      handleAnalysis(payload);
    } catch (err) {
      if (controller.signal.aborted || !isCurrentAnalyzeRequest(requestId)) {
        return;
      }
      setError(readClientError(err));
      setScreen("fatal");
    } finally {
      window.clearTimeout(slowTimer);
      window.clearTimeout(processingTimer);
      if (activeAnalyzeRef.current?.id === requestId) {
        activeAnalyzeRef.current = null;
        submittingRef.current = false;
      }
    }
  }

  async function warmBackend() {
    try {
      await fetch(`${API_BASE}/healthz`, { cache: "no-store" });
    } catch {
      // The analyze request below will show the real error if the backend is still unreachable.
    }
  }

  function isCurrentAnalyzeRequest(requestId: number) {
    return activeAnalyzeRef.current?.id === requestId && !activeAnalyzeRef.current.controller.signal.aborted;
  }

  function cancelAnalyzeAndReturnToScanner() {
    activeAnalyzeRef.current?.controller.abort();
    activeAnalyzeRef.current = null;
    submittingRef.current = false;
    setScreen("scanner");
  }

  function handleAnalysis(payload: Analysis) {
    setAnalysis(payload);
    setFinalAnalysis(null);
    setManualSelections({});
    if (payload.status === "TOO_MANY_UNCERTAIN" || payload.reviewRequiredCount > MAX_MANUAL_REVIEW_QUESTIONS) {
      setError("Bu formda çok fazla cevap güvenilir biçimde okunamadı.\nFormu yeniden taratın.");
      setScreen("fatal");
      return;
    }
    if (payload.reviewRequiredCount > 0) {
      setScreen("manual");
      return;
    }
    setFinalAnalysis(payload);
    if (payload.blankCount > 0) {
      setScreen("blankConfirm");
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
          status: value === "BLANK" ? "BLANK" : "OK",
          source: "MANUAL",
          confidence: 1,
          manualCorrection: labels[value]
        };
      })
    };
    updated.blankCount = updated.answers.filter((answer) => answer.value === "BLANK").length;
    setFinalAnalysis(updated);
    if (updated.blankCount > 0) {
      setScreen("blankConfirm");
      return;
    }
    void completeOrWarnDuplicate(updated);
  }

  async function completeOrWarnDuplicate(payload: Analysis) {
    if (looksDuplicate(payload)) {
      setPendingDuplicate(payload);
      setScreen("duplicate");
      return;
    }
    await saveAndShowSuccess(payload);
  }

  async function saveAndShowSuccess(payload: Analysis) {
    const response = await fetch(`${API_BASE}/api/demo/forms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysisId: payload.analysisId,
        templateCode: payload.templateCode,
        formConfidence: payload.formConfidence,
        answers: payload.answers
      })
    });
    if (!response.ok) {
      setError("Cevaplar SQLite veritabanına kaydedilemedi.");
      setScreen("fatal");
      return;
    }
    rememberSequence(payload);
    setFinalAnalysis(payload);
    setScreen("success");
  }

  function nextForm() {
    const nextCount = scannedCount + 1;
    localStorage.setItem("demoScannedCount", String(nextCount));
    setScannedCount(nextCount);
    setAnalysis(null);
    setFinalAnalysis(null);
    setPendingDuplicate(null);
    setQuality("bad");
    setGuidance("Taranan formu kaldırın");
    setScreen("scanner");
    window.setTimeout(() => setGuidance("Yeni formu yerleştirin"), 1800);
  }

  async function scanDemoImage() {
    const response = await fetch(`${API_BASE}/api/demo/sample-forms/${demoName}`);
    if (!response.ok) {
      setError("Demo görsel yüklenemedi.");
      setScreen("fatal");
      return;
    }
    await analyzeBlob(await response.blob());
  }

  async function uploadTestImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      await analyzeBlob(file);
      event.target.value = "";
    }
  }

  async function loadHistory() {
    const response = await fetch(`${API_BASE}/api/demo/forms`);
    setHistory(response.ok ? ((await response.json()) as StoredSummary[]) : []);
    setScreen("history");
  }

  async function openDetail(id: number) {
    const response = await fetch(`${API_BASE}/api/demo/forms/${id}`);
    if (response.ok) {
      setDetail((await response.json()) as StoredDetail);
      setScreen("detail");
    }
  }

  async function deleteDetail(id: number) {
    await fetch(`${API_BASE}/api/demo/forms/${id}`, { method: "DELETE" });
    setDetail(null);
    await loadHistory();
  }

  if (screen === "history") {
    return <HistoryScreen scannedCount={scannedCount} forms={history} onBack={() => setScreen("scanner")} onOpen={openDetail} />;
  }

  if (screen === "detail" && detail) {
    return <DetailScreen scannedCount={scannedCount} detail={detail} onBack={loadHistory} onDelete={deleteDetail} />;
  }

  return (
    <main className="app">
      <Header scannedCount={scannedCount} onHistory={loadHistory} />
      {screen === "scanner" && (
        <section className="scan">
          <div className="camera-shell">
            {cameraState === "ready" ? (
              <video ref={videoRef} autoPlay playsInline muted onLoadedMetadata={() => void attachCameraStream()} />
            ) : (
              <CameraFallback state={cameraState} onRequest={requestCamera} />
            )}
            <div className={`frame ${quality}`} aria-label="A4 hizalama çerçevesi">
              <span className="corner tl" />
              <span className="corner tr" />
              <span className="corner br" />
              <span className="corner bl" />
            </div>
            <div className="guidance">{cameraState === "ready" ? guidance : "Forma dokunarak odaklayın"}</div>
          </div>

          <div className="actions">
            <button className="scan-button" onClick={captureAndAnalyze} disabled={cameraState !== "ready" || quality !== "ready" || submittingRef.current}>
              TARAT
            </button>
            <label className="upload-card">
              <input className="upload-input" type="file" accept="image/*" onChange={uploadTestImage} aria-label="Test Görseli Yükle" />
              <span className="upload-title">Anket fotoğrafı yükle</span>
              <span className="upload-copy">Bilgisayarındaki veya telefonundaki form fotoğrafını seçip doğrudan analiz et.</span>
              <span className="upload-action">Fotoğraf Seç</span>
            </label>
            <details className="demo-tools">
              <summary>Demo Görseller</summary>
              <div className="demo-grid">
                <select value={demoName} onChange={(event) => setDemoName(event.target.value)}>
                  {demoForms.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <button className="secondary-button" onClick={scanDemoImage}>
                  Demo Görselini Tara
                </button>
              </div>
            </details>
          </div>
        </section>
      )}

      {screen === "processing" && <StatusScreen title={processingText} button={processingText.includes("uzun") ? "Tekrar Dene" : undefined} onClick={cancelAnalyzeAndReturnToScanner} />}

      {screen === "manual" && analysis && (
        <ManualReview answers={reviewAnswers} selections={manualSelections} onSelect={chooseManual} onContinue={continueManual} />
      )}

      {screen === "blankConfirm" && finalAnalysis && (
        <BlankConfirm blanks={blankAnswers} onRetry={() => setScreen("scanner")} onContinue={() => void completeOrWarnDuplicate(finalAnalysis)} />
      )}

      {screen === "duplicate" && pendingDuplicate && (
        <DuplicateWarning
          onSkip={nextForm}
          onContinue={() => void saveAndShowSuccess(pendingDuplicate)}
          onRetry={() => setScreen("scanner")}
        />
      )}

      {screen === "success" && finalAnalysis && <SuccessScreen analysis={finalAnalysis} onNext={nextForm} />}

      {screen === "fatal" && <StatusScreen title={error} button="TEKRAR TARAT" onClick={() => setScreen("scanner")} />}
    </main>
  );
}

function Header({ scannedCount, onHistory }: { scannedCount: number; onHistory: () => void }) {
  return (
    <header className="topbar">
      <div>
        <div className="title">Demo Tarama</div>
        <div className="counter">Taranan: {scannedCount}</div>
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
  state: "idle" | "ready" | "denied" | "unsupported" | "insecure";
  onRequest: () => void;
}) {
  let message = "Kamera hazırlanıyor...";
  if (state === "denied") {
    message = "Form tarayabilmek için kamera izni vermeniz gerekiyor.";
  }
  if (state === "idle") {
    message = "Kamerayı başlatmak için butona dokunun.";
  }
  if (state === "unsupported") {
    message = "Bu tarayıcı kamera ile taramayı desteklemiyor.";
  }
  if (state === "insecure") {
    message = "Kamera için güvenli bağlantı gerekiyor. Telefonu HTTPS tüneli ya da localhost üzerinden açın.";
  }
  return (
    <div className="camera-placeholder">
      <div className="stack">
        <strong>{message}</strong>
        {(state === "denied" || state === "idle" || state === "insecure") && (
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
        {button && (
          <button className="primary-button" onClick={onClick}>
            {button}
          </button>
        )}
      </div>
    </section>
  );
}

function ManualReview({
  answers,
  selections,
  onSelect,
  onContinue
}: {
  answers: Answer[];
  selections: Record<number, AnswerValue>;
  onSelect: (questionNo: number, value: AnswerValue) => void;
  onContinue: () => void;
}) {
  const complete = answers.every((answer) => selections[answer.questionNo]);
  return (
    <section className="screen">
      <div className="status-title">Manuel kontrol</div>
      {answers.map((answer) => (
        <div className="panel stack" key={answer.questionNo}>
          <strong>Soru {answer.questionNo}</strong>
          <span className="muted">{labels[answer.status]}</span>
          <div className="review-options">
            {(["NEVER", "SOMETIMES", "ALWAYS", "BLANK"] as const).map((value) => (
              <button
                key={value}
                className={`option-button ${selections[answer.questionNo] === value ? "selected" : ""}`}
                onClick={() => onSelect(answer.questionNo, value)}
              >
                {value === "BLANK" ? "Boş bırak" : labels[value]}
              </button>
            ))}
          </div>
        </div>
      ))}
      <button className="primary-button" disabled={!complete} onClick={onContinue}>
        DEVAM ET
      </button>
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
      <button className="secondary-button" onClick={onRetry}>
        TEKRAR TARAT
      </button>
      <button className="primary-button" onClick={onContinue}>
        DEVAM ET
      </button>
    </section>
  );
}

function DuplicateWarning({ onSkip, onContinue, onRetry }: { onSkip: () => void; onContinue: () => void; onRetry: () => void }) {
  return (
    <section className="screen">
      <div className="panel stack">
        <div className="status-title">Bu form daha önce taranmış bir forma benziyor.</div>
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

function SuccessScreen({ analysis, onNext }: { analysis: Analysis; onNext: () => void }) {
  const manualCount = analysis.answers.filter((answer) => answer.source === "MANUAL").length;
  const autoCount = analysis.answers.filter((answer) => answer.source === "AUTO").length;
  const blankCount = analysis.answers.filter((answer) => answer.value === "BLANK").length;
  return (
    <section className="screen">
      <div className="panel success stack">
        <div className="status-title">Form başarıyla okundu</div>
        <div>Form güven puanı: %{Math.round(analysis.formConfidence * 100)}</div>
        <div>Otomatik okunan soru sayısı: {autoCount}</div>
        <div>Manuel düzeltilen soru sayısı: {manualCount}</div>
        <div>Boş cevap sayısı: {blankCount}</div>
      </div>
      <AnswerList answers={analysis.answers} />
      <button className="scan-button" onClick={onNext}>
        SONRAKİ FORMA GEÇ
      </button>
    </section>
  );
}

function HistoryScreen({ scannedCount, forms, onBack, onOpen }: { scannedCount: number; forms: StoredSummary[]; onBack: () => void; onOpen: (id: number) => void }) {
  return (
    <main className="app">
      <Header scannedCount={scannedCount} onHistory={onBack} />
      <section className="screen">
        <div className="status-title">Geçmiş Taramalar</div>
        {forms.length === 0 && <div className="panel">Kayıt bulunamadı.</div>}
        {forms.map((form) => (
          <button className="history-row" key={form.id} onClick={() => onOpen(form.id)}>
            <strong>#{form.id}</strong>
            <span>{new Date(form.createdAt).toLocaleString("tr-TR")}</span>
            <span>%{Math.round(form.formConfidence * 100)}</span>
            <span>Boş: {form.blankCount}</span>
            <span>Manuel: {form.manualCount}</span>
          </button>
        ))}
        <button className="secondary-button" onClick={onBack}>
          GERİ
        </button>
      </section>
    </main>
  );
}

function DetailScreen({ scannedCount, detail, onBack, onDelete }: { scannedCount: number; detail: StoredDetail; onBack: () => void; onDelete: (id: number) => void }) {
  return (
    <main className="app">
      <Header scannedCount={scannedCount} onHistory={onBack} />
      <section className="screen">
        <div className="panel stack">
          <div className="status-title">Form #{detail.id}</div>
          <span>{new Date(detail.createdAt).toLocaleString("tr-TR")}</span>
          <span>Form güven puanı: %{Math.round(detail.formConfidence * 100)}</span>
          <span>Boş cevap: {detail.blankCount}</span>
          <span>Manuel düzeltme: {detail.manualCount}</span>
        </div>
        <AnswerList answers={detail.answers} showConfidence />
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

function AnswerList({ answers, showConfidence = false }: { answers: Answer[]; showConfidence?: boolean }) {
  return (
    <div className="answer-list">
      {answers.map((answer) => (
        <div className="answer-row" key={answer.questionNo}>
          <strong>{answer.questionNo}.</strong>
          <span>{answer.value ? labels[answer.value] : labels[answer.status]}</span>
          <span className="badge">{answer.source === "MANUAL" ? "Manuel seçildi" : answer.source}</span>
          {showConfidence && <span className="muted">Güven: %{Math.round(answer.confidence * 100)}</span>}
          {answer.manualCorrection && <span className="muted">Düzeltme: {answer.manualCorrection}</span>}
        </div>
      ))}
    </div>
  );
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

function fullCameraFrame(video: HTMLVideoElement) {
  const videoWidth = video.videoWidth || 1920;
  const videoHeight = video.videoHeight || 1080;
  return { x: 0, y: 0, width: videoWidth, height: videoHeight };
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
