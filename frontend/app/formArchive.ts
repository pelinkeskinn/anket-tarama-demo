const STORAGE_KEY = "anketTarama.forms";

export type ArchivedForm = {
  id: number;
  createdAt: string;
  formConfidence: number;
  blankCount: number;
  manualCount: number;
  possibleDuplicate?: boolean;
  analysisId: string;
  templateCode: string;
  answers: unknown[];
};

export function readLocalForms(): ArchivedForm[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as ArchivedForm[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function upsertLocalForm(form: ArchivedForm) {
  const forms = readLocalForms().filter((item) => item.analysisId !== form.analysisId && item.id !== form.id);
  writeLocalForms([form, ...forms]);
}

export function removeLocalForm(id: number) {
  writeLocalForms(readLocalForms().filter((item) => item.id !== id));
}

export function getLocalForm(id: number): ArchivedForm | undefined {
  return readLocalForms().find((item) => item.id === id);
}

export function localSummaries() {
  const forms = readLocalForms();
  return {
    items: forms.map((form) => ({
      id: form.id,
      createdAt: form.createdAt,
      formConfidence: form.formConfidence,
      blankCount: form.blankCount,
      manualCount: form.manualCount,
      possibleDuplicate: form.possibleDuplicate
    })),
    total: forms.length
  };
}

function writeLocalForms(forms: ArchivedForm[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(forms));
  } catch {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(forms.slice(0, 200)));
    } catch {
      // Quota exceeded; keep whatever is already stored.
    }
  }
}
