import { requestJson } from './http';

export const AVATARS = [
  { id: 'cat', label: 'Cat' },
  { id: 'fox', label: 'Fox' },
  { id: 'panda', label: 'Panda' },
  { id: 'rabbit', label: 'Rabbit' },
  { id: 'bear', label: 'Bear' },
  { id: 'owl', label: 'Owl' },
] as const;

export type AvatarId = (typeof AVATARS)[number]['id'];
export type CurrentUser = { displayName: string };
export type AvatarPreference = { avatarId: AvatarId };

export function avatarUrl(id: AvatarId) {
  return `/avatars/${id}.svg`;
}

export function getCurrentUser() {
  return requestJson<CurrentUser>('/api/me');
}

export function getAvatar() {
  return requestJson<AvatarPreference>('/api/me/avatar');
}

export function saveAvatar(avatarId: AvatarId) {
  return requestJson<AvatarPreference>('/api/me/avatar', {
    method: 'PUT',
    body: JSON.stringify({ avatarId }),
  });
}
