import axios from "axios";
import { notifyError } from "./notify";

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return typeof item === "string" ? item : null;
      })
      .filter((x): x is string => Boolean(x));
    if (parts.length) return parts.join("; ");
  }
  return null;
}

async function detailFromResponseData(data: unknown): Promise<string | null> {
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const j = JSON.parse(text) as { detail?: unknown };
      return formatDetail(j.detail);
    } catch {
      return null;
    }
  }
  if (data && typeof data === "object" && "detail" in data) {
    return formatDetail((data as { detail: unknown }).detail);
  }
  return null;
}

/**
 * Показать пользователю причину неудачного скачивания (в т.ч. 404 и тело ответа FastAPI).
 */
export async function notifyAxiosDownloadError(
  err: unknown,
  notFoundMessage: string
): Promise<void> {
  if (axios.isAxiosError(err) && err.response) {
    const { status, data } = err.response;
    if (status === 404) {
      const d = await detailFromResponseData(data);
      notifyError(d ?? notFoundMessage);
      return;
    }
  }
  if (axios.isAxiosError(err) && err.request && !err.response) {
    notifyError("Не удалось связаться с сервером.");
    return;
  }
  notifyError("Не удалось скачать файл.");
}

/**
 * Ошибки загрузки файла (POST /api/upload): 400/413 и тело FastAPI `detail`.
 */
export async function notifyAxiosUploadError(err: unknown): Promise<void> {
  if (axios.isAxiosError(err) && err.response) {
    const { status, data } = err.response;
    if (status === 401) {
      return;
    }
    const d = await detailFromResponseData(data);
    if (d) {
      notifyError(d);
      return;
    }
    if (status === 413) {
      notifyError("Файл слишком большой для сервера.");
      return;
    }
    if (status === 400) {
      notifyError("Некорректный запрос загрузки.");
      return;
    }
  }
  if (axios.isAxiosError(err) && err.request && !err.response) {
    notifyError("Не удалось связаться с сервером.");
    return;
  }
  notifyError("Не удалось загрузить файл.");
}
