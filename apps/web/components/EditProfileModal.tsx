"use client";

/**
 * Edit profile.
 *
 * Rebuilt onto the house modal pattern (portal + Escape + body-scroll-lock +
 * role="dialog"), which every other modal in the app already used and this one
 * did not. It was also styling itself with `topic-modal-*` and `card-input`
 * class names that have **no definition anywhere in globals.css** — so it
 * rendered as unstyled browser chrome: a bare div over the page, default
 * inputs, default select. That is the whole reason it read as "a generic HTML
 * form" rather than part of Spoin.
 *
 * Failures are inline and scoped to the control that caused them. The previous
 * version routed all three failure paths through `alert()`, which cannot carry
 * the field it belongs to and dumps the user out of the modal's own visual
 * language to do it.
 *
 * Upload validation is duplicated from the API on purpose (see UPLOAD_* below):
 * the server is still the authority and its 400 is surfaced verbatim, but a
 * 5MB round-trip to learn the file was too big is a bad interaction.
 */

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ApiError, type User, api } from "@/lib/api";
import { AVATAR_MARK_KEYS, AvatarMark, CloseIcon } from "./icons";

/** Mirrors api/routers/profile.py's `upload_avatar` checks. */
const UPLOAD_TYPES = ["image/jpeg", "image/png", "image/webp"];
const UPLOAD_MAX_BYTES = 5 * 1024 * 1024;

const GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"];

const NAME_MAX = 60;
const AGE_MIN = 13;
const AGE_MAX = 120;

interface Props {
  user: User;
  onClose: () => void;
  /** Every server-side change to the user, as it happens — a save, but also an
   *  avatar upload or removal, which commit immediately and independently of
   *  the Save button. Cancelling after an upload previously left the parent
   *  showing a stale avatar until a full reload. */
  onUserChanged: (user: User) => void;
}

export function EditProfileModal({ user, onClose, onUserChanged }: Props) {
  const [name, setName] = useState(user.display_name);
  const [age, setAge] = useState<string>(user.age != null ? String(user.age) : "");
  const [gender, setGender] = useState(user.gender ?? "");
  const [avatarIcon, setAvatarIcon] = useState(user.avatar_icon ?? "");

  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [formError, setFormError] = useState("");
  const [nameError, setNameError] = useState("");
  const [ageError, setAgeError] = useState("");
  const [photoError, setPhotoError] = useState("");

  /** Local object URL for a just-picked file, so the user sees what they chose
   *  before it is committed. Revoked on replace and on unmount — a leaked blob
   *  URL pins the whole image in memory for the life of the document. */
  const [preview, setPreview] = useState<string | null>(null);
  const [hasImage, setHasImage] = useState(Boolean(user.has_avatar_image));

  const fileInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const fieldId = useId();

  const busy = saving || uploading;

  // Escape to dismiss — matches TopicStatsModal / QuizModal / CustomThemeModal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The page scrolls at the window level, so without this the profile keeps
  // scrolling underneath the open modal.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  // Move focus in on open and hand it back to whatever opened this on close.
  useEffect(() => {
    previousFocus.current = document.activeElement as HTMLElement | null;
    nameInputRef.current?.focus();
    nameInputRef.current?.select();
    return () => previousFocus.current?.focus();
  }, []);

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const validate = () => {
    let ok = true;

    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setNameError("A name is required.");
      ok = false;
    } else if (trimmed.length > NAME_MAX) {
      setNameError(`${NAME_MAX} characters or fewer.`);
      ok = false;
    } else {
      setNameError("");
    }

    if (age !== "") {
      const parsed = Number(age);
      if (!Number.isInteger(parsed) || parsed < AGE_MIN || parsed > AGE_MAX) {
        setAgeError(`Between ${AGE_MIN} and ${AGE_MAX}, or leave it blank.`);
        ok = false;
      } else {
        setAgeError("");
      }
    } else {
      setAgeError("");
    }

    return ok;
  };

  const handleSave = async () => {
    if (busy) return;
    setFormError("");
    if (!validate()) return;

    setSaving(true);
    try {
      const updated = await api.updateProfile({
        display_name: name.trim(),
        age: age === "" ? null : Number(age),
        gender: gender || null,
        avatar_icon: avatarIcon || null,
      });
      onUserChanged(updated);
      onClose();
    } catch (cause) {
      setFormError(cause instanceof ApiError ? cause.message : "Couldn't save your changes.");
    } finally {
      setSaving(false);
    }
  };

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Reset immediately so picking the same file twice still fires a change.
    event.target.value = "";
    if (!file) return;

    setPhotoError("");

    if (!UPLOAD_TYPES.includes(file.type)) {
      setPhotoError("JPEG, PNG or WebP only.");
      return;
    }
    if (file.size > UPLOAD_MAX_BYTES) {
      setPhotoError(`That file is ${(file.size / 1024 / 1024).toFixed(1)}MB. The limit is 5MB.`);
      return;
    }

    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(file));

    setUploading(true);
    try {
      onUserChanged(await api.uploadAvatar(file));
      setHasImage(true);
    } catch (cause) {
      setPhotoError(cause instanceof ApiError ? cause.message : "Upload failed.");
      if (preview) URL.revokeObjectURL(preview);
      setPreview(null);
    } finally {
      setUploading(false);
    }
  };

  const handleRemovePhoto = async () => {
    if (busy) return;
    setPhotoError("");
    setUploading(true);
    try {
      onUserChanged(await api.deleteAvatar());
      if (preview) URL.revokeObjectURL(preview);
      setPreview(null);
      setHasImage(false);
    } catch (cause) {
      setPhotoError(cause instanceof ApiError ? cause.message : "Couldn't remove the photo.");
    } finally {
      setUploading(false);
    }
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel profile-edit-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${fieldId}-heading`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title" id={`${fieldId}-heading`}>
            Edit profile
          </h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        <form
          className="profile-edit-form"
          // Our own validation is the single authority here. Without this the
          // browser's constraint validation fires first on the age field's
          // min/max and shows an unstyled native bubble, so `validate()` never
          // runs and the designed inline error never renders. min/max stay on
          // the input as semantics for assistive tech and the spinner.
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void handleSave();
          }}
        >
          {/* ── Identity ─────────────────────────────────────────────────── */}
          <div className="profile-edit-field">
            <label className="profile-edit-label" htmlFor={`${fieldId}-name`}>
              NAME
            </label>
            <input
              id={`${fieldId}-name`}
              ref={nameInputRef}
              type="text"
              className="profile-edit-input"
              value={name}
              maxLength={NAME_MAX}
              autoComplete="name"
              aria-invalid={nameError !== ""}
              aria-describedby={nameError ? `${fieldId}-name-error` : undefined}
              onChange={(e) => {
                setName(e.target.value);
                if (nameError) setNameError("");
              }}
            />
            {nameError ? (
              <p className="profile-edit-error" id={`${fieldId}-name-error`}>
                {nameError}
              </p>
            ) : null}
          </div>

          <div className="profile-edit-row">
            <div className="profile-edit-field">
              <label className="profile-edit-label" htmlFor={`${fieldId}-age`}>
                AGE
              </label>
              <input
                id={`${fieldId}-age`}
                type="number"
                inputMode="numeric"
                className="profile-edit-input"
                value={age}
                min={AGE_MIN}
                max={AGE_MAX}
                placeholder="—"
                aria-invalid={ageError !== ""}
                aria-describedby={ageError ? `${fieldId}-age-error` : undefined}
                onChange={(e) => {
                  setAge(e.target.value);
                  if (ageError) setAgeError("");
                }}
              />
            </div>

            <div className="profile-edit-field">
              <label className="profile-edit-label" htmlFor={`${fieldId}-gender`}>
                GENDER
              </label>
              <select
                id={`${fieldId}-gender`}
                className="profile-edit-input profile-edit-select"
                value={gender}
                onChange={(e) => setGender(e.target.value)}
              >
                <option value="">—</option>
                {GENDERS.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {ageError ? (
            <p className="profile-edit-error" id={`${fieldId}-age-error`}>
              {ageError}
            </p>
          ) : null}

          {/* ── Avatar mark ──────────────────────────────────────────────── */}
          <fieldset className="profile-edit-field profile-edit-fieldset">
            <legend className="profile-edit-label">MARK</legend>
            <div className="profile-mark-grid" role="radiogroup" aria-label="Avatar mark">
              {AVATAR_MARK_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={avatarIcon === key}
                  aria-label={key}
                  className="profile-mark"
                  data-selected={avatarIcon === key}
                  onClick={() => setAvatarIcon(avatarIcon === key ? "" : key)}
                >
                  <AvatarMark mark={key} />
                </button>
              ))}
            </div>
            <p className="profile-edit-hint">
              {hasImage || preview
                ? "A photo is set — it takes precedence over the mark."
                : "Shown when no photo is set. Select again to clear."}
            </p>
          </fieldset>

          {/* ── Photo ────────────────────────────────────────────────────── */}
          <div className="profile-edit-field">
            <span className="profile-edit-label">PHOTO</span>
            <div className="profile-photo-row">
              <div className="profile-photo-preview" data-busy={uploading}>
                {preview ? (
                  <img src={preview} alt="Selected profile photo" />
                ) : hasImage ? (
                  <span className="profile-photo-set">SET</span>
                ) : (
                  <span className="profile-photo-none">NONE</span>
                )}
              </div>

              <div className="profile-photo-actions">
                <input
                  type="file"
                  ref={fileInputRef}
                  className="profile-photo-input"
                  accept={UPLOAD_TYPES.join(",")}
                  onChange={(e) => void handleFile(e)}
                />
                <button
                  type="button"
                  className="collection-action"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={busy}
                >
                  {uploading ? "WORKING…" : hasImage || preview ? "REPLACE" : "UPLOAD"}
                </button>
                {hasImage || preview ? (
                  <button
                    type="button"
                    className="collection-action collection-action-quiet"
                    onClick={() => void handleRemovePhoto()}
                    disabled={busy}
                  >
                    REMOVE
                  </button>
                ) : null}
                <p className="profile-edit-hint">JPEG, PNG or WebP · up to 5MB</p>
              </div>
            </div>
            {photoError ? <p className="profile-edit-error">{photoError}</p> : null}
          </div>

          {formError ? <p className="profile-edit-error">{formError}</p> : null}

          <div className="profile-edit-footer">
            <button
              type="button"
              className="collection-action collection-action-quiet"
              onClick={onClose}
              disabled={busy}
            >
              CANCEL
            </button>
            <button type="submit" className="collection-action collection-action-primary" disabled={busy}>
              {saving ? "SAVING…" : "SAVE"}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
