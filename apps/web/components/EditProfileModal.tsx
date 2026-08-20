"use client";

import { useState, useRef } from "react";
import { type User, api } from "@/lib/api";

const PRESET_ICONS = ["◉", "◇", "△", "✦", "▣", "⌁", "◎", "⬡"];

interface Props {
  user: User;
  onClose: () => void;
  onSaved: (user: User) => void;
}

export function EditProfileModal({ user, onClose, onSaved }: Props) {
  const [name, setName] = useState(user.display_name);
  const [age, setAge] = useState<number | "">(user.age ?? "");
  const [gender, setGender] = useState(user.gender ?? "");
  const [avatarIcon, setAvatarIcon] = useState(user.avatar_icon ?? "");
  const [saving, setSaving] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updatedUser = await api.updateProfile({
        display_name: name,
        age: typeof age === "number" ? age : null,
        gender: gender || null,
        avatar_icon: avatarIcon || null,
      });
      onSaved(updatedUser);
    } catch (err) {
      console.error(err);
      alert("Failed to save profile.");
    } finally {
      setSaving(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setSaving(true);
    try {
      const updatedUser = await api.uploadAvatar(file);
      onSaved(updatedUser);
    } catch (err) {
      console.error(err);
      alert("Failed to upload photo.");
    } finally {
      setSaving(false);
    }
  };
  
  const handleRemovePhoto = async () => {
    setSaving(true);
    try {
      const updatedUser = await api.deleteAvatar();
      onSaved(updatedUser);
    } catch (err) {
      console.error(err);
      alert("Failed to remove photo.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="topic-modal-backdrop" onClick={onClose}>
      <div className="topic-modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="topic-modal-header">
          <h2 className="topic-modal-title mono">Edit Profile</h2>
        </div>

        <div className="topic-modal-content">
          <div className="profile-edit-field">
            <label className="mono">NAME</label>
            <input 
              type="text" 
              className="card-input" 
              value={name} 
              onChange={(e) => setName(e.target.value)} 
            />
          </div>

          <div className="profile-edit-field-row">
            <div className="profile-edit-field">
              <label className="mono">AGE</label>
              <input 
                type="number" 
                className="card-input" 
                value={age} 
                onChange={(e) => setAge(e.target.value ? parseInt(e.target.value, 10) : "")} 
              />
            </div>
            <div className="profile-edit-field">
              <label className="mono">GENDER</label>
              <select className="card-input" value={gender} onChange={(e) => setGender(e.target.value)}>
                <option value="">Select...</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Non-binary">Non-binary</option>
                <option value="Prefer not to say">Prefer not to say</option>
              </select>
            </div>
          </div>

          <div className="profile-edit-field">
            <label className="mono">PRESET ICON</label>
            <div className="profile-icon-grid">
              {PRESET_ICONS.map((icon) => (
                <button
                  key={icon}
                  type="button"
                  className={`profile-icon-preset ${avatarIcon === icon ? "active" : ""}`}
                  onClick={() => setAvatarIcon(icon)}
                >
                  {icon}
                </button>
              ))}
              {avatarIcon && (
                <button 
                  type="button" 
                  className="profile-icon-preset clear mono" 
                  onClick={() => setAvatarIcon("")}
                >
                  X
                </button>
              )}
            </div>
          </div>

          <div className="profile-edit-field">
            <label className="mono">CUSTOM PHOTO</label>
            <div className="profile-photo-actions">
              <input 
                type="file" 
                accept="image/jpeg, image/png, image/webp"
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={handleFileUpload}
              />
              <button 
                type="button" 
                className="auth-button primary" 
                onClick={() => fileInputRef.current?.click()}
                disabled={saving}
              >
                Upload Photo
              </button>
              {user.has_avatar_image && (
                <button 
                  type="button" 
                  className="auth-button secondary" 
                  onClick={handleRemovePhoto}
                  disabled={saving}
                >
                  Remove
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="topic-modal-footer">
          <button className="auth-button secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="auth-button primary" onClick={handleSave} disabled={saving}>Save Changes</button>
        </div>
      </div>
    </div>
  );
}
