// Which look the Publish dialog starts on. ONE small pure function, so the later home-vault integration (the person's preference and the tagged client contract)
// can replace it; profileSource.ts re-exports it next to findProfile and createProfile.
//
// Preferences:
//   auto    the client profile for this site, else the Agency profile, else Default (the default and the recommended choice)
//   agency  the Agency profile, else Default
//   default Default (the built-in look)
//   last    the look chosen last time, else the same as auto
// A choice that has no profile file yet ("not set up yet") is never preselected. The dialog still shows the select and the person can change it; `reason` is the one-line note.
export type DefaultLookPreference = 'auto' | 'agency' | 'default' | 'last';
export const DEFAULT_LOOK_PREFERENCES: Array<{ id: DefaultLookPreference; label: string }> = [
  { id: 'auto', label: 'Client profile for this site, else the Agency profile, else Default (recommended)' },
  { id: 'agency', label: 'Agency profile' },
  { id: 'default', label: 'Default look' },
  { id: 'last', label: 'Remember my last choice' },
];
export interface LookChoiceLike { id: string; missing?: boolean }

const norm = (s: unknown) => (typeof s === 'string' ? s : '').trim().toLowerCase();
export function isDefaultLookPreference(v: unknown): v is DefaultLookPreference { return v === 'auto' || v === 'agency' || v === 'default' || v === 'last'; }

export function resolveDefaultLook(input: { domain: string; choices: LookChoiceLike[]; preference?: unknown; lastId?: string }): { id: string; reason: string } {
  try {
    const have = (id: string) => input.choices.some((c) => c.id === id && !c.missing);
    const clientId = input.choices.find((c) => !c.missing && norm(c.id) === 'client:' + norm(input.domain) + '.json')?.id ?? null;
    const pref: DefaultLookPreference = isDefaultLookPreference(input.preference) ? input.preference : 'auto';
    const auto = (): { id: string; reason: string } => {
      if (clientId) return { id: clientId, reason: 'Chosen because a client profile is named after this site. Change it above if it is not the right look.' };
      if (have('agency')) return { id: 'agency', reason: 'Chosen because there is no client profile for this site, so the Agency profile is used. Change it above if it is not the right look.' };
      return { id: 'default', reason: 'No client or Agency profile yet, so the built-in look is used. Create one from the Look list.' };
    };
    if (pref === 'default') return { id: 'default', reason: 'Chosen because your setting is Default look. Change it above for this report.' };
    if (pref === 'agency') return have('agency') ? { id: 'agency', reason: 'Chosen because your setting is the Agency profile. Change it above for this report.' } : { id: 'default', reason: 'Your setting is the Agency profile, but there is none yet, so the built-in look is used.' };
    if (pref === 'last') {
      if (input.lastId && have(input.lastId)) return { id: input.lastId, reason: 'Chosen because it is the look you used last time. Change it above for this report.' };
      return auto();
    }
    return auto();
  } catch { return { id: 'default', reason: '' }; }
}
