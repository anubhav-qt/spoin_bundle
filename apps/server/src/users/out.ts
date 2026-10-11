import type { PreferencesOut, UserOut } from "@spoin/shared";
import type { appUser } from "../db/schema.ts";

type UserRow = typeof appUser.$inferSelect;

/**
 * The one builder of `UserOut`. A guest's row carries Better Auth's placeholder
 * address, which is nobody's: the wire says null.
 */
export function toUserOut(user: UserRow, preferences: PreferencesOut | null = null): UserOut {
  return {
    id: user.id,
    email: user.isAnonymous ? null : user.email,
    display_name: user.name,
    is_guest: user.isAnonymous,
    onboarding_complete: user.onboardingComplete,
    age: user.age,
    gender: user.gender,
    avatar_icon: user.avatarIcon,
    has_avatar_image: user.hasAvatarImage,
    daily_card_goal: user.dailyCardGoal,
    preferences,
    is_admin: user.role === "admin",
  };
}
