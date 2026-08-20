"use client";

import { useEffect, useState } from "react";
import { type User, type ProfileStatsOut, api } from "@/lib/api";
import { useAuth } from "./AuthProvider";
import { EditProfileModal } from "./EditProfileModal";

function getInitials(name: string) {
  return name.substring(0, 2).toUpperCase();
}

export function ProfileView() {
  const { user, refresh } = useAuth();
  const [stats, setStats] = useState<ProfileStatsOut | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [currentDate, setCurrentDate] = useState(new Date());

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth() + 1; // 1-indexed

  useEffect(() => {
    if (!user) return;
    api
      .getProfileStats(year, month)
      .then(setStats)
      .catch((err) => console.error(err));
  }, [user, year, month]);

  if (!user) return null;

  const handlePrevMonth = () => {
    setCurrentDate((d) => {
      const nd = new Date(d);
      nd.setMonth(nd.getMonth() - 1);
      return nd;
    });
  };

  const handleNextMonth = () => {
    const today = new Date();
    setCurrentDate((d) => {
      const nd = new Date(d);
      nd.setMonth(nd.getMonth() + 1);
      // Don't allow future months
      if (nd.getFullYear() > today.getFullYear() || (nd.getFullYear() === today.getFullYear() && nd.getMonth() > today.getMonth())) {
        return d;
      }
      return nd;
    });
  };

  const isNextDisabled = () => {
    const today = new Date();
    return year === today.getFullYear() && month === today.getMonth() + 1;
  };

  const handleSaved = async () => {
    await refresh(); // Refresh user from auth provider
    setIsEditing(false);
  };

  const monthName = currentDate.toLocaleString('default', { month: 'long', year: 'numeric' }).toUpperCase();

  // Generate heatmap grid
  const daysInMonth = new Date(year, month, 0).getDate();
  const firstDayOfWeek = new Date(year, month - 1, 1).getDay(); // 0 is Sunday
  // Adjust so Monday is 0, Sunday is 6
  const startOffset = (firstDayOfWeek + 6) % 7;
  
  const gridCells = Array.from({ length: 42 }, (_, i) => {
    const day = i - startOffset + 1;
    if (day < 1 || day > daysInMonth) return null;
    return day;
  });

  const getIntensity = (cards: number) => {
    if (cards === 0) return 0;
    if (cards <= 2) return 1;
    if (cards <= 5) return 2;
    if (cards <= 10) return 3;
    return 4;
  };

  const getActivityForDay = (day: number) => {
    if (!stats) return null;
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    return stats.monthly_activity.find(a => a.date === dateStr);
  };

  return (
    <div className="profile-view">
      <div className="profile-header">
        <div className="profile-avatar">
          {user.has_avatar_image ? (
            <img src={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/profile/me/avatar/image?t=${Date.now()}`} alt="Profile" />
          ) : user.avatar_icon ? (
            <span className="profile-avatar-icon">{user.avatar_icon}</span>
          ) : (
            <span className="profile-avatar-initials">{getInitials(user.display_name)}</span>
          )}
        </div>
        
        <h1 className="profile-name">{user.display_name}</h1>
        
        {(user.age || user.gender) && (
          <div className="profile-meta mono">
            {user.age && <span>{user.age} YEARS</span>}
            {user.age && user.gender && <span> · </span>}
            {user.gender && <span>{user.gender.toUpperCase()}</span>}
          </div>
        )}
        
        <button className="auth-button secondary profile-edit-btn" onClick={() => setIsEditing(true)}>
          EDIT PROFILE
        </button>
      </div>

      <div className="profile-section-divider"></div>

      <div className="profile-section">
        <h2 className="profile-section-title mono">ACTIVITY</h2>
        <div className="profile-stats-grid">
          <div className="profile-stat-box">
            <span className="profile-stat-value">{stats?.current_streak ?? "-"}</span>
            <span className="profile-stat-label mono">DAY STREAK</span>
            {stats && stats.current_streak > 0 && <div className="profile-streak-line" />}
          </div>
          <div className="profile-stat-box">
            <span className="profile-stat-value">{stats?.longest_streak ?? "-"}</span>
            <span className="profile-stat-label mono">BEST STREAK</span>
          </div>
          <div className="profile-stat-box">
            <span className="profile-stat-value">{stats?.total_cards_read ?? "-"}</span>
            <span className="profile-stat-label mono">CARDS READ</span>
          </div>
          <div className="profile-stat-box">
            <span className="profile-stat-value">{stats?.total_topics ?? "-"}</span>
            <span className="profile-stat-label mono">TOPICS EXPLORED</span>
          </div>
        </div>
      </div>

      <div className="profile-section-divider"></div>

      <div className="profile-section">
        <div className="profile-month-nav">
          <button className="profile-nav-btn mono" onClick={handlePrevMonth}>‹</button>
          <h2 className="profile-section-title mono">{monthName}</h2>
          <button className="profile-nav-btn mono" onClick={handleNextMonth} disabled={isNextDisabled()}>›</button>
        </div>

        <div className="profile-heatmap">
          <div className="profile-heatmap-days mono">
            <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span>
          </div>
          <div className="profile-heatmap-grid">
            {gridCells.map((day, i) => {
              if (day === null) {
                return <div key={`empty-${i}`} className="profile-heatmap-cell empty" />;
              }
              const activity = getActivityForDay(day);
              const count = activity ? activity.cards_read : 0;
              const intensity = getIntensity(count);
              return (
                <div 
                  key={`day-${day}`} 
                  className={`profile-heatmap-cell level-${intensity}`}
                  title={`${monthName.split(' ')[0]} ${day} — ${count} cards read`}
                >
                  <div className="profile-heatmap-tooltip mono">
                    {count} CARDS
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {isEditing && (
        <EditProfileModal 
          user={user} 
          onClose={() => setIsEditing(false)} 
          onSaved={handleSaved} 
        />
      )}
    </div>
  );
}
