"use client";

const KEY = "cam_user_id";

export const getUserId = (): string | null =>
  typeof window !== "undefined" ? localStorage.getItem(KEY) : null;

export const setUserId = (id: string): void =>
  localStorage.setItem(KEY, id);

export const clearUserId = (): void =>
  localStorage.removeItem(KEY);
