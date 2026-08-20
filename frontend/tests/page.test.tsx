import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import Page from "../app/page";

const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;

function cleanAnalysis(overrides: Partial<Record<string, unknown>> = {}) {
  const answers = Array.from({ length: 25 }, (_, index) => ({
    questionNo: index + 1,
    value: (["NEVER", "SOMETIMES", "ALWAYS"] as const)[index % 3],
    confidence: 0.99,
    source: "AUTO",
    status: "OK"
  }));
  return {
    analysisId: "demo-test",
    templateCode: "DEMO_FORM_V1",
    status: "OK",
    formConfidence: 0.96,
    blankCount: 0,
    reviewRequiredCount: 0,
    answers,
    ...overrides
  };
}

function mockFetchAnalysis(payload: unknown) {
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/healthz") || url.includes("/readyz")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/api/omr/analyze")) {
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/api/forms")) {
      return new Response(JSON.stringify({ id: 1, createdAt: new Date().toISOString(), ...payload }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    return new Response(new Blob(["image"], { type: "image/png" }), { status: 200 });
  }) as unknown as typeof fetch;
}

async function uploadImage() {
  const input = screen.getByLabelText("Test Görseli Yükle");
  await userEvent.upload(input, new File(["image"], "form.png", { type: "image/png" }));
}

async function makeScannerReady() {
  await act(async () => {
    await Promise.resolve();
  });
  act(() => {
    vi.advanceTimersByTime(3800);
  });
}

beforeEach(() => {
  vi.useRealTimers();
  localStorage.clear();
  global.crypto.randomUUID = vi.fn(() => "request-id");
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => stream) }
  });
  global.fetch = vi.fn();
});

describe("scanner page", () => {
  test("shows camera permission message", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => Promise.reject(new Error("denied"))) }
    });
    render(<Page />);
    expect(await screen.findByText("Form tarayabilmek için kamera izni vermeniz gerekiyor.")).toBeInTheDocument();
    expect(screen.getByText("Kamerayı Başlat")).toBeInTheDocument();
  });

  test("scan button moves from inactive to active", async () => {
    vi.useFakeTimers();
    render(<Page />);
    const button = screen.getByText("TARAT");
    expect(button).toBeDisabled();
    await makeScannerReady();
    expect(button).toBeEnabled();
  });

  test("shows processing state", async () => {
    global.fetch = vi.fn(
      () =>
        new Promise<Response>(() => {
          return undefined;
        })
    ) as unknown as typeof fetch;
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Fotoğraf alındı.")).toBeInTheDocument();
  });

  test("retry ignores stale analyze results", async () => {
    vi.useFakeTimers();
    let resolveAnalyze: (response: Response) => void = () => undefined;
    global.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/omr/analyze")) {
        return new Promise<Response>((resolve) => {
          resolveAnalyze = resolve;
        });
      }
      return Promise.resolve(
        new Response(JSON.stringify({ id: 1, createdAt: new Date().toISOString(), ...cleanAnalysis() }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      );
    }) as unknown as typeof fetch;

    render(<Page />);
    fireEvent.change(screen.getByLabelText("Test Görseli Yükle"), {
      target: { files: [new File(["image"], "form.png", { type: "image/png" })] }
    });
    expect(screen.getByText("Fotoğraf alındı.")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(9200);
    });
    fireEvent.click(screen.getByText("Tekrar Dene"));
    expect(screen.getByText("TARAT")).toBeInTheDocument();

    await act(async () => {
      resolveAnalyze(new Response(JSON.stringify(cleanAnalysis()), { status: 200, headers: { "Content-Type": "application/json" } }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText("Form başarıyla okundu")).not.toBeInTheDocument();
    expect(screen.getByText("TARAT")).toBeInTheDocument();
  });

  test("shows manual review screen", async () => {
    const payload = cleanAnalysis({
      status: "REVIEW_REQUIRED",
      reviewRequiredCount: 1,
      answers: cleanAnalysis().answers.map((answer) =>
        answer.questionNo === 7
          ? {
              ...answer,
              value: null,
              source: "UNRESOLVED",
              status: "DOUBLE_MARK",
              confidence: 0.55,
              optionLabels: ["Form seçeneği 1", "Form seçeneği 2", "Form seçeneği 3", "Form seçeneği 4"]
            }
          : answer
      )
    });
    mockFetchAnalysis(payload);
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Manuel kontrol")).toBeInTheDocument();
    expect(screen.getByText("Soru 7")).toBeInTheDocument();
    expect(screen.getByText("Form seçeneği 2")).toBeInTheDocument();
  });

  test("keeps a healthy form with many uncertain answers editable", async () => {
    const answers = cleanAnalysis().answers.map((answer, index) =>
      index < 6 ? { ...answer, value: null, source: "UNRESOLVED", status: "AMBIGUOUS", confidence: 0.5 } : answer
    );
    mockFetchAnalysis(
      cleanAnalysis({
        templateCode: "HEALTHY_NUTRITION_V2",
        status: "REVIEW_REQUIRED",
        reviewRequiredCount: 6,
        answers
      })
    );
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Manuel kontrol")).toBeInTheDocument();
    expect(screen.getByText("Soru 1")).toBeInTheDocument();
    expect(screen.getByText("Soru 6")).toBeInTheDocument();
  });

  test.skip("shows blank confirmation", async () => {
    const answers = cleanAnalysis().answers.map((answer) =>
      answer.questionNo === 4 ? { ...answer, value: "BLANK", status: "BLANK" } : answer
    );
    mockFetchAnalysis(cleanAnalysis({ blankCount: 1, answers }));
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Bu formda 1 soru boş bırakılmıştır.")).toBeInTheDocument();
  });

  test("shows success screen", async () => {
    mockFetchAnalysis(cleanAnalysis());
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Form başarıyla okundu")).toBeInTheDocument();
  });

  test("next form returns to scanner and increments counter", async () => {
    mockFetchAnalysis(cleanAnalysis());
    render(<Page />);
    await uploadImage();
    fireEvent.click(await screen.findByText("SONRAKİ FORMA GEÇ"));
    expect(screen.getByText("Taranan: 1")).toBeInTheDocument();
    expect(screen.getByText("TARAT")).toBeInTheDocument();
  });

  test("shows backend error message", async () => {
    global.fetch = vi.fn(async () => {
      return new Response(JSON.stringify({ detail: { error: { message: "Formun dört referans işareti bulunamadı." } } }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    }) as unknown as typeof fetch;
    render(<Page />);
    await uploadImage();
    expect(await screen.findByText("Formun dört referans işareti bulunamadı.")).toBeInTheDocument();
  });

  test("double click does not create two analyze requests", async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn(
      () =>
        new Promise<Response>(() => {
          return undefined;
        })
    ) as unknown as typeof fetch;
    render(<Page />);
    await makeScannerReady();
    const button = screen.getByText("TARAT");
    fireEvent.click(button);
    fireEvent.click(button);
    await act(async () => {
      await Promise.resolve();
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test("demo image loading triggers analysis", async () => {
    mockFetchAnalysis(cleanAnalysis());
    render(<Page />);
    fireEvent.click(screen.getByText("Demo Görseller"));
    fireEvent.click(screen.getByText("Demo Görselini Tara"));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/demo/sample-forms/filled-clean-v2.png")));
  });
});
